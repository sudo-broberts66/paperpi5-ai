#!/usr/bin/env python3
"""Generate a new picture with OnnxStream (SDXL Turbo).

Based on generate_picture.py from https://github.com/dylski/PaperPiAI
(MIT, Dylan Banarse), adapted for a Raspberry Pi 5.

Writes <images_dir>/<prompt>_seed_<n>_steps_<n>.png, a matching .txt with the
prompt, and copies the result to <images_dir>/output.png for display.
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402

SHARED_FILE = "output.png"
CURRENT_FILE = ".current"  # name of the image output.png was copied from


def choose_prompt(prompts_file, rng=random):
    """Build a prompt by picking one fragment from each list in the JSON file.

    This is the single place prompts come from, so other prompt sources
    (e.g. a local LLM) can be added here later.
    """
    with open(prompts_file) as f:
        parts = json.load(f)
    picks = (rng.choice(part).strip() for part in parts)
    return " ".join(p for p in picks if p)  # "" entries make a part optional


def safe_name(prompt, seed, steps):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", prompt).strip("_")[:64]
    return f"{slug}_seed_{seed}_steps_{steps}"


def build_command(sd_binary, model_dir, prompt, seed, steps, width, height,
                  output, ram_mode=True, low_mem=False, extra_args=()):
    cmd = [
        sd_binary,
        "--xl", "--turbo",
        "--models-path", model_dir,
        "--prompt", prompt,
        "--seed", str(seed),
        "--output", output,
        "--steps", str(steps),
        "--res", f"{width}x{height}",
    ]
    if low_mem:
        cmd.append("--rpi-lowmem")
    elif ram_mode:
        cmd.append("--ram")
    cmd.extend(extra_args)
    return cmd


def list_images(images_dir):
    """Generated PNGs, newest first, excluding output.png."""
    files = [
        os.path.join(images_dir, f)
        for f in os.listdir(images_dir)
        if f.endswith(".png") and f != SHARED_FILE
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def prune_images(images_dir, keep):
    """Delete all but the newest `keep` images (and their .txt files)."""
    if keep <= 0:
        return []
    removed = []
    for path in list_images(images_dir)[keep:]:
        os.remove(path)
        txt = os.path.splitext(path)[0] + ".txt"
        if os.path.exists(txt):
            os.remove(txt)
        removed.append(path)
    return removed


def main(argv=None):
    cfg = load_config()
    g, p = cfg["generate"], cfg["paths"]

    ap = argparse.ArgumentParser(description="Generate a new random picture.")
    ap.add_argument("output_dir", nargs="?", default=p["images_dir"],
                    help="Directory to save images (default from config)")
    ap.add_argument("--prompts", default=p["prompts_file"], help="Prompts JSON file")
    ap.add_argument("--prompt", default="", help="Use this exact prompt")
    ap.add_argument("--seed", type=int, default=None, help="Seed (default random)")
    ap.add_argument("--steps", type=int, default=g["steps"])
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--portrait", action="store_true",
                    default=cfg["display"]["portrait"],
                    help="Swap width and height")
    ap.add_argument("--sd", default=p["sd_binary"], help="OnnxStream sd binary")
    ap.add_argument("--model", default=p["model_dir"], help="Model directory")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the command without running it")
    args = ap.parse_args(argv)

    width = args.width or g["width"]
    height = args.height or g["height"]
    if args.portrait and args.width is None and args.height is None:
        width, height = min(width, height), max(width, height)

    output_dir = resolve(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    seed = args.seed if args.seed is not None else random.randint(1, 1_000_000)
    prompt = args.prompt or choose_prompt(resolve(args.prompts))
    fullpath = os.path.join(output_dir, safe_name(prompt, seed, args.steps) + ".png")

    cmd = build_command(
        resolve(args.sd), resolve(args.model), prompt, seed, args.steps,
        width, height, fullpath,
        ram_mode=g["ram_mode"], low_mem=g["low_mem"],
        extra_args=[str(a) for a in g["extra_sd_args"]],
    )

    print(f"Prompt: {prompt}")
    print(f"Seed: {seed}  Steps: {args.steps}  Size: {width}x{height}")
    print("Command: " + " ".join(cmd), flush=True)
    if args.dry_run:
        return 0

    if not os.path.exists(cmd[0]):
        print(f"ERROR: sd binary not found at {cmd[0]}. Run scripts/install.sh.",
              file=sys.stderr)
        return 1

    result = subprocess.run(cmd)
    if result.returncode != 0 or not os.path.exists(fullpath):
        print(f"ERROR: image generation failed (exit code {result.returncode}).",
              file=sys.stderr)
        return 1

    with open(os.path.splitext(fullpath)[0] + ".txt", "w") as f:
        f.write(f"{prompt}\nseed={seed} steps={args.steps} size={width}x{height}\n")

    shared = os.path.join(output_dir, SHARED_FILE)
    shutil.copy2(fullpath, shared)
    with open(os.path.join(output_dir, CURRENT_FILE), "w") as f:
        f.write(os.path.basename(fullpath))
    print(f"Saved {fullpath}\nCopied to {shared}")

    for removed in prune_images(output_dir, g["keep_images"]):
        print(f"Pruned {removed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
