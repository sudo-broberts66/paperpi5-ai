import json
import os
import random
import sys
import time

import pytest

import check_llm
import config
import generate_picture
import llm_prompt

PLANETS = os.path.join(config.REPO_ROOT, "prompts", "planets.json")


@pytest.mark.parametrize("raw,expected", [
    ("A crystal canyon under two suns, a lone rover", "A crystal canyon under two suns, a lone rover"),
    ('"A crystal canyon under two suns."', "A crystal canyon under two suns"),
    ("Prompt: frozen ocean beneath a ringed planet", "frozen ocean beneath a ringed planet"),
    ("**Image prompt:** red dunes and a black sky\n\nThis prompt evokes...", "red dunes and a black sky"),
    ("<think>hmm</think>\nViolet salt flats with three moons", "Violet salt flats with three moons"),
    ("\n\n  Lava rivers   across   a plain  \n", "Lava rivers across a plain"),
    ("Sure!", None),
    ("", None),
])
def test_clean_prompt(raw, expected):
    assert llm_prompt.clean_prompt(raw) == expected


def test_clean_prompt_truncates():
    raw = " ".join(f"w{i}" for i in range(50))
    assert len(llm_prompt.clean_prompt(raw, max_words=10).split()) == 10


def test_pick_inspiration_keeps_style_out():
    parts = llm_prompt.load_library(PLANETS)
    for seed in range(20):
        inspiration, style = llm_prompt.pick_inspiration(parts, random.Random(seed))
        assert style in parts[-1]
        assert all(x not in parts[-1] for x in inspiration)
        assert "" not in inspiration
    inspiration, style = llm_prompt.pick_inspiration(parts, random.Random(1), keep_style=False)
    assert style == ""


def test_build_messages_mentions_everything():
    msgs = llm_prompt.build_messages("alien planets", ["crystal canyon", "under two suns"],
                                     ["old prompt one"], 30, "as a linocut print")
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    user = msgs[1]["content"]
    for text in ("alien planets", "crystal canyon; under two suns", "old prompt one",
                 "30 words", "as a linocut print"):
        assert text in user


def test_recent_prompts(tmp_path):
    now = time.time()
    for i in range(5):
        p = tmp_path / f"{i}.txt"
        p.write_text(f"prompt {i}\nseed=1\n")
        os.utime(p, (now + i, now + i))
    assert llm_prompt.recent_prompts(str(tmp_path), 2) == ["prompt 4", "prompt 3"]
    assert llm_prompt.recent_prompts(str(tmp_path), 0) == []
    assert llm_prompt.recent_prompts(str(tmp_path / "missing"), 3) == []


def _cfg(tmp_path):
    cfg = config.load_config(os.path.join(config.REPO_ROOT, "config.example.toml"))
    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF" + b"\0" * 16)
    cfg["llm"]["model"] = str(model)
    cfg["paths"]["images_dir"] = str(tmp_path)
    return cfg


def test_generate_appends_style(tmp_path):
    seen = {}

    def fake_llm(model_path, messages, **kw):
        seen["messages"] = messages
        return "A frozen sea of methane under a cracked moon"

    result = llm_prompt.generate(_cfg(tmp_path), random.Random(3), fake_llm)
    assert result["prompt"] == f"A frozen sea of methane under a cracked moon, {result['style']}"
    assert result["style"]
    assert "sci-fi landscape on an alien planet" in seen["messages"][1]["content"]


def test_generate_retries_then_fails(tmp_path):
    replies = iter(["Sure!", "Lava plains with two suns overhead"])
    result = llm_prompt.generate(_cfg(tmp_path), random.Random(1), lambda *a, **k: next(replies))
    assert result["scene"] == "Lava plains with two suns overhead"
    with pytest.raises(RuntimeError, match="not a usable prompt"):
        llm_prompt.generate(_cfg(tmp_path), random.Random(1), lambda *a, **k: "ok")


def test_generate_missing_model(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["llm"]["model"] = str(tmp_path / "nope.gguf")
    with pytest.raises(RuntimeError, match="not found"):
        llm_prompt.generate(cfg, llm_fn=lambda *a, **k: "x")


def test_get_prompt_sources():
    cfg = config.load_config(os.path.join(config.REPO_ROOT, "config.example.toml"))
    assert generate_picture.get_prompt(cfg, "given one") == ("given one", "given")
    ok = lambda timeout: ("llm prompt", {"inspiration": ["a"], "seconds": 1})  # noqa: E731
    assert generate_picture.get_prompt(cfg, llm_fn=ok) == ("llm prompt", "llm")
    bad = lambda timeout: (None, "timed out")  # noqa: E731
    prompt, source = generate_picture.get_prompt(cfg, prompts_file=PLANETS, llm_fn=bad)
    assert source == "library" and prompt
    prompt, source = generate_picture.get_prompt(cfg, prompts_file=PLANETS, use_llm=False, llm_fn=ok)
    assert source == "library"


def _fake_python(tmp_path, body):
    script = tmp_path / "fakepy"
    script.write_text(f"#!{sys.executable}\nimport sys\n{body}\n")
    script.chmod(0o755)
    return str(script)


def test_llm_prompt_subprocess_parsing(tmp_path):
    good = _fake_python(tmp_path, 'print("llama log noise"); print(\'{"prompt": "red dunes", "seconds": 2}\')')
    assert generate_picture.llm_prompt(10, python=good) == ("red dunes", {"prompt": "red dunes", "seconds": 2})
    err = _fake_python(tmp_path, 'print(\'{"error": "model missing"}\'); sys.exit(1)')
    assert generate_picture.llm_prompt(10, python=err) == (None, "model missing")
    crash = _fake_python(tmp_path, 'sys.stderr.write("Segmentation fault\\n"); sys.exit(139)')
    prompt, reason = generate_picture.llm_prompt(10, python=crash)
    assert prompt is None and "Segmentation fault" in reason
    slow = _fake_python(tmp_path, "import time; time.sleep(5)")
    assert generate_picture.llm_prompt(0.5, python=slow) == (None, "timed out after 0.5s")


def test_check_llm_model_file(tmp_path):
    good = tmp_path / "good.gguf"
    good.write_bytes(b"GGUF" + b"\0" * 2000)
    assert check_llm.check_model_file(str(good), min_bytes=1000) == []
    assert check_llm.check_model_file(str(good), min_bytes=10**6)  # too small
    html = tmp_path / "html.gguf"
    html.write_bytes(b"<!DOCTYPE html>" + b"\0" * 2000)
    assert "not a GGUF" in check_llm.check_model_file(str(html), min_bytes=1000)[0]
    (tmp_path / "part.gguf.part").write_bytes(b"GGUF")
    assert "not finished" in check_llm.check_model_file(str(tmp_path / "part.gguf"))[0]
    assert "not found" in check_llm.check_model_file(str(tmp_path / "x.gguf"))[0]
