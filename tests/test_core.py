import json
import os
import random
import time

import pytest
from PIL import Image

import check_model
import config
import display_buttons
import display_picture
import generate_picture


def test_defaults_match_example_config():
    example = config.load_config(os.path.join(config.REPO_ROOT, "config.example.toml"))
    assert example == config.DEFAULTS


def test_config_override(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[display]\nsaturation = 0.8\n')
    cfg = config.load_config(str(p))
    assert cfg["display"]["saturation"] == 0.8
    assert cfg["display"]["portrait"] is False  # untouched default
    assert cfg["generate"]["width"] == 800


def test_resolve_relative_and_absolute():
    assert config.resolve("images") == os.path.join(config.REPO_ROOT, "images")
    assert config.resolve("/tmp/x") == "/tmp/x"


def test_choose_prompt_picks_one_from_each_part(tmp_path):
    p = tmp_path / "p.json"
    p.write_text(json.dumps([["a rose"], ["as a woodcut", "as a poster"]]))
    prompt = generate_picture.choose_prompt(str(p), random.Random(1))
    assert prompt.startswith("a rose as a ")


@pytest.mark.parametrize("name", sorted(os.listdir(os.path.join(config.REPO_ROOT, "prompts"))))
def test_bundled_prompts_files_are_valid(name):
    path = os.path.join(config.REPO_ROOT, "prompts", name)
    with open(path) as f:
        parts = json.load(f)
    assert parts and all(isinstance(p, list) and p for p in parts)
    assert all(isinstance(x, str) for p in parts for x in p)
    for _ in range(20):
        prompt = generate_picture.choose_prompt(path)
        assert prompt.strip() and len(prompt.split()) < 60


def test_safe_name():
    name = generate_picture.safe_name("a rose, 'as a poster'/x", 3, 2)
    assert name == "a_rose_as_a_poster_x_seed_3_steps_2"


def test_build_command_modes():
    base = ("sd", "m", "p", 1, 3, 800, 480, "o.png")
    cmd = generate_picture.build_command(*base)
    assert "--ram" in cmd and "--rpi-lowmem" not in cmd
    assert cmd[cmd.index("--res") + 1] == "800x480"
    low = generate_picture.build_command(*base, low_mem=True)
    assert "--rpi-lowmem" in low and "--ram" not in low
    plain = generate_picture.build_command(*base, ram_mode=False, extra_args=["--threads", "-1"])
    assert "--ram" not in plain and plain[-2:] == ["--threads", "-1"]


def _make_images(d, names):
    now = time.time()
    for i, name in enumerate(names):
        path = d / name
        Image.new("RGB", (8, 8)).save(path)
        (d / (path.stem + ".txt")).write_text("x")
        os.utime(path, (now - 100 + i, now - 100 + i))  # later in list = newer


def test_list_images(tmp_path):
    _make_images(tmp_path, ["old.png", "mid.png", "new.png", "output.png"])
    assert [os.path.basename(p) for p in generate_picture.list_images(tmp_path)] == \
        ["new.png", "mid.png", "old.png"]


def test_generate_dry_run(capsys):
    assert generate_picture.main(["--dry-run", "--prompt", "test", "--seed", "5"]) == 0
    out = capsys.readouterr().out
    assert "--res 800x480" in out and "--seed 5" in out


def test_generate_portrait_swaps_size(capsys):
    generate_picture.main(["--dry-run", "--prompt", "t", "--portrait"])
    assert "--res 480x800" in capsys.readouterr().out


def test_prepare_landscape_and_portrait(tmp_path):
    src = tmp_path / "in.png"
    Image.new("RGB", (512, 512), "red").save(src)
    assert display_picture.prepare(str(src), 800, 480).size == (800, 480)
    for mode in ("resize", "crop", "pad"):
        assert display_picture.prepare(str(src), 800, 480, mode=mode).size == (800, 480)
    # Portrait content is rotated onto the landscape panel.
    assert display_picture.prepare(str(src), 800, 480, portrait=True).size == (800, 480)


def test_display_simulate_writes_output(tmp_path):
    src, out = tmp_path / "in.png", tmp_path / "out.png"
    Image.new("RGB", (480, 800), "blue").save(src)
    assert display_picture.main([str(src), "-s", "-o", str(out)]) == 0
    assert Image.open(out).size == (800, 480)


def test_display_missing_image(tmp_path):
    assert display_picture.main([str(tmp_path / "nope.png"), "-s"]) == 1


def test_lfs_pointer_detection(tmp_path):
    (tmp_path / "unet").mkdir()
    (tmp_path / "unet" / "w.bin").write_text(
        "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 123\n")
    (tmp_path / "model.txt").write_text("real small file")
    pointers = check_model.find_lfs_pointers(str(tmp_path))
    assert [os.path.basename(p) for p in pointers] == ["w.bin"]
    problems = check_model.check(str(tmp_path))
    assert any("lfs pointers" in p for p in problems)


def test_model_check_ok_and_missing(tmp_path):
    (tmp_path / "w.bin").write_bytes(b"\0" * 4096)
    assert check_model.check(str(tmp_path), min_bytes=1000) == []
    assert check_model.check(str(tmp_path), min_bytes=10**9)  # too small
    assert check_model.check(str(tmp_path / "missing"))


@pytest.mark.parametrize("action,current,count,expected", [
    ("latest", 3, 5, 0),
    ("older", 0, 5, 1),
    ("older", 4, 5, None),
    ("newer", 2, 5, 1),
    ("newer", 0, 5, None),
    ("latest", 0, 0, None),
])
def test_button_target_index(action, current, count, expected):
    assert display_buttons.target_index(action, current, count) == expected


def test_button_current_index(tmp_path):
    images = [str(tmp_path / n) for n in ("c.png", "b.png", "a.png")]
    assert display_buttons.current_index(str(tmp_path), images) == 0  # no state file
    (tmp_path / ".current").write_text("b.png")
    assert display_buttons.current_index(str(tmp_path), images) == 1


def test_button_show_steps_through_images(tmp_path, monkeypatch):
    _make_images(tmp_path, ["a.png", "b.png", "c.png"])
    calls = []
    monkeypatch.setattr(display_buttons.subprocess, "run", lambda cmd: calls.append(cmd))
    cfg = config.load_config()
    cfg["paths"]["images_dir"] = str(tmp_path)
    frame = display_buttons.Frame(cfg)
    frame.show("latest")
    assert (tmp_path / ".current").read_text() == "c.png"
    frame.show("older")
    assert (tmp_path / ".current").read_text() == "b.png"
    frame.show("newer")
    assert (tmp_path / ".current").read_text() == "c.png"
    frame.show("newer")  # already newest: nothing happens
    assert len(calls) == 3
    assert (tmp_path / "output.png").exists()
