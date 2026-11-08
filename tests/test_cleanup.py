import os
import time

import cleanup
import config

DAY = 86400


def _images(d, ages_days, size=1000):
    """Create pictures aged `ages_days` (+ .txt), return them newest first."""
    now = time.time()
    paths = []
    for i, age in enumerate(ages_days):
        p = d / f"img{i}.png"
        p.write_bytes(b"x" * size)
        (d / f"img{i}.txt").write_text("prompt")
        t = now - age * DAY
        os.utime(p, (t, t))
        paths.append(str(p))
    (d / "output.png").write_bytes(b"x")
    return sorted(paths, key=os.path.getmtime, reverse=True)


def names(paths):
    return sorted(os.path.basename(p) for p in paths)


def test_no_rules_deletes_nothing(tmp_path):
    imgs = _images(tmp_path, [0, 10, 100])
    assert cleanup.plan(imgs) == []


def test_keep_images(tmp_path):
    imgs = _images(tmp_path, [0, 1, 2, 3])
    assert names(cleanup.plan(imgs, keep_images=2)) == ["img2.png", "img3.png"]


def test_keep_days(tmp_path):
    imgs = _images(tmp_path, [0, 5, 31, 60])
    assert names(cleanup.plan(imgs, keep_days=30)) == ["img2.png", "img3.png"]


def test_newest_is_always_kept(tmp_path):
    imgs = _images(tmp_path, [40, 50])  # both older than the limit
    assert names(cleanup.plan(imgs, keep_days=30)) == ["img1.png"]
    assert names(cleanup.plan(imgs, min_free_bytes=10**12, free_now=0)) == ["img1.png"]


def test_min_free_deletes_oldest_until_enough(tmp_path):
    imgs = _images(tmp_path, [0, 1, 2, 3, 4], size=1000)
    # 500 bytes free, need 2600: delete the 3 oldest (3000 bytes).
    assert names(cleanup.plan(imgs, min_free_bytes=2600, free_now=500)) == \
        ["img2.png", "img3.png", "img4.png"]
    assert cleanup.plan(imgs, min_free_bytes=2600, free_now=5000) == []


def test_min_free_counts_space_from_other_rules(tmp_path):
    imgs = _images(tmp_path, [0, 1, 2, 3], size=1000)
    # keep_images removes 2 (2000 bytes), which is already enough space.
    assert names(cleanup.plan(imgs, keep_images=2, min_free_bytes=2500, free_now=600)) == \
        ["img2.png", "img3.png"]


def _cfg(tmp_path, **storage):
    cfg = config.load_config(os.path.join(config.REPO_ROOT, "config.example.toml"))
    cfg["paths"]["images_dir"] = str(tmp_path)
    cfg["storage"].update(min_free_gb=0, **storage)
    return cfg


def test_cleanup_removes_files_and_txt(tmp_path):
    _images(tmp_path, [0, 10, 40])
    removed = cleanup.cleanup(_cfg(tmp_path, keep_days=30), log=lambda m: None)
    assert names(removed) == ["img2.png"]
    assert not (tmp_path / "img2.png").exists() and not (tmp_path / "img2.txt").exists()
    assert (tmp_path / "img1.png").exists() and (tmp_path / "output.png").exists()


def test_cleanup_dry_run_keeps_files(tmp_path):
    _images(tmp_path, [0, 40])
    removed = cleanup.cleanup(_cfg(tmp_path, keep_days=30), dry_run=True, log=lambda m: None)
    assert names(removed) == ["img1.png"] and (tmp_path / "img1.png").exists()


def test_cleanup_empty_or_missing_dir(tmp_path):
    assert cleanup.cleanup(_cfg(tmp_path), log=lambda m: None) == []
    assert cleanup.cleanup(_cfg(tmp_path), str(tmp_path / "nope"), log=lambda m: None) == []


def test_legacy_generate_keep_images(tmp_path):
    cfg = _cfg(tmp_path)
    cfg["generate"]["keep_images"] = 50
    assert cleanup.storage_settings(cfg)[0] == 50
    cfg["storage"]["keep_images"] = 10
    assert cleanup.storage_settings(cfg)[0] == 10


def test_defaults():
    assert config.DEFAULTS["storage"] == {"keep_images": 0, "keep_days": 30, "min_free_gb": 2}
