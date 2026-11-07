#!/usr/bin/env python3
"""Write an image prompt with a small local LLM (llama.cpp via llama-cpp-python).

How it works:
  1. Pick random "inspiration" fragments from a prompt library
     (one per list, e.g. a landscape, a sky and a detail from planets.json).
  2. Ask the LLM for one short scene description on the configured theme,
     inspired by those fragments and different from recent prompts.
  3. Clean the reply into a single line of a sensible length.
  4. Append an art style from the library's last list (when keep_style = true),
     so every picture keeps an e-paper-friendly style.

generate_picture.py runs this file as a separate process with a timeout, so the
LLM's memory is freed before Stable Diffusion starts and a hang or crash can
never cost a picture: it falls back to the plain prompt library instead.

Run it by hand to try prompts:  venv/bin/python src/llm_prompt.py --count 3
"""

import argparse
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402

SYSTEM_PROMPT = (
    "You write prompts for an AI image generator that makes pictures for a "
    "small e-paper art frame. The frame shows only six flat inks (black, white, "
    "red, yellow, green, blue), so scenes with bold shapes, strong silhouettes, "
    "clear horizons and a few large areas of colour look best. "
    "Reply with the prompt only: one line, no quotes, no title, no explanation."
)


def load_library(path):
    with open(path) as f:
        parts = json.load(f)
    return [[x.strip() for x in part] for part in parts]


def pick_inspiration(parts, rng=random, keep_style=True):
    """Return (inspiration fragments, style or "").

    With keep_style, the library's last list is treated as the art style and
    kept out of the LLM's hands so it can be appended unchanged.
    """
    style = ""
    scene_parts = parts
    if keep_style and len(parts) > 1:
        scene_parts, style = parts[:-1], rng.choice(parts[-1])
    picks = [rng.choice(part) for part in scene_parts]
    return [p for p in picks if p], style


def recent_prompts(images_dir, count):
    """First line of the newest `count` prompt .txt files."""
    if count <= 0 or not os.path.isdir(images_dir):
        return []
    txts = [os.path.join(images_dir, f) for f in os.listdir(images_dir) if f.endswith(".txt")]
    txts.sort(key=os.path.getmtime, reverse=True)
    prompts = []
    for path in txts[:count]:
        try:
            with open(path) as f:
                line = f.readline().strip()
        except OSError:
            continue
        if line:
            prompts.append(line)
    return prompts


def build_messages(theme, inspiration, recent=(), max_words=35, style=""):
    lines = [
        f"Write one image prompt describing {theme}.",
        f"Use at most {max_words} words.",
    ]
    if inspiration:
        lines.append("Take inspiration from: " + "; ".join(inspiration) + ".")
    if style:
        lines.append(f"Describe only the scene. Don't mention an art style or medium; "
                     f"\"{style}\" will be added afterwards.")
    if recent:
        lines.append("Make it clearly different from these recent prompts:")
        lines.extend(f"- {r}" for r in recent)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


_PREFIX = re.compile(r"^(image\s+)?prompt\s*[:\-]\s*", re.IGNORECASE)


def clean_prompt(text, max_words=35, min_words=4):
    """Turn a raw LLM reply into one usable prompt line, or None."""
    if not text:
        return None
    # Drop any <think>...</think> block from reasoning models.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    line = re.sub(r"[*_`#]+", "", line)          # markdown
    line = _PREFIX.sub("", line).strip()
    line = line.strip("\"'“”‘’ ").strip()
    line = re.sub(r"\s+", " ", line)
    words = line.split()
    if len(words) < min_words:
        return None
    if len(words) > max_words:
        line = " ".join(words[:max_words])
    return line.rstrip(" ,;:.") or None


def combine(scene, style):
    return f"{scene}, {style}" if style else scene


def run_llm(model_path, messages, temperature=0.9, max_tokens=120, threads=4,
            seed=None, n_ctx=2048):
    """Load the GGUF model, ask it once, return the reply text."""
    from llama_cpp import Llama

    llm = Llama(
        model_path=model_path,
        n_ctx=n_ctx,
        n_threads=threads,
        seed=seed if seed is not None else random.randint(1, 2**31 - 1),
        verbose=False,
    )
    out = llm.create_chat_completion(
        messages=messages,
        temperature=temperature,
        top_p=0.95,
        repeat_penalty=1.1,
        max_tokens=max_tokens,
    )
    return out["choices"][0]["message"]["content"]


def generate(cfg, rng=random, llm_fn=run_llm, attempts=2):
    """Return a dict with the final prompt and how it was made.

    Raises RuntimeError if the LLM can't produce a usable prompt.
    """
    c = cfg["llm"]
    model_path = resolve(c["model"])
    if not os.path.exists(model_path):
        raise RuntimeError(f"LLM model not found: {model_path} (run scripts/install.sh)")

    parts = load_library(resolve(c["inspiration_file"]))
    recent = recent_prompts(resolve(cfg["paths"]["images_dir"]), c["recent_count"])
    last_reply = ""
    for _ in range(attempts):
        inspiration, style = pick_inspiration(parts, rng, c["keep_style"])
        messages = build_messages(c["theme"], inspiration, recent, c["max_words"], style)
        last_reply = llm_fn(model_path, messages, temperature=c["temperature"],
                            threads=c["threads"])
        scene = clean_prompt(last_reply, c["max_words"])
        if scene:
            return {
                "prompt": combine(scene, style),
                "scene": scene,
                "style": style,
                "inspiration": inspiration,
            }
    raise RuntimeError(f"LLM reply was not a usable prompt: {last_reply!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write image prompts with the local LLM.")
    ap.add_argument("--count", type=int, default=1, help="How many prompts to write")
    ap.add_argument("--json", action="store_true",
                    help="Print one JSON result (used by generate_picture.py)")
    ap.add_argument("--theme", help="Override llm.theme from config.toml")
    args = ap.parse_args(argv)

    cfg = load_config()
    if args.theme:
        cfg["llm"]["theme"] = args.theme

    for i in range(args.count):
        start = time.monotonic()
        try:
            result = generate(cfg)
        except Exception as e:  # report any failure to the caller cleanly
            if args.json:
                print(json.dumps({"error": str(e)}))
            else:
                print(f"ERROR: {e}", file=sys.stderr)
            return 1
        result["seconds"] = round(time.monotonic() - start, 1)
        if args.json:
            print(json.dumps(result))
            return 0
        print(f"[{i + 1}] {result['prompt']}")
        print(f"    inspiration: {', '.join(result['inspiration'])}  ({result['seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
