#!/usr/bin/env python3
"""Delete old pictures so the SD card never fills up.

Three rules, set under [storage] in config.toml. A picture is deleted if any
rule says so:

  keep_images  keep only the newest N pictures            (0 = no limit)
  keep_days    delete pictures older than N days          (0 = no limit)
  min_free_gb  if free space drops below this, delete the oldest pictures
               until it's back above it                   (0 = off)

The newest picture is never deleted. Each picture's .txt prompt file goes with it.
Broken picture files (not valid PNGs, e.g. left by a run interrupted by a
power cut) are always deleted.

generate_picture.py runs this before and after every picture. Run it by hand
to see what it would do:  venv/bin/python src/cleanup.py --dry-run
"""

import argparse
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402

GB = 1024**3
MIN_KEEP = 1  # never delete the newest picture


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BROKEN_MIN_AGE_S = 600  # leave very new files alone in case they're still being written
STALE_PARTIAL_S = 2 * 3600  # hidden in-progress files this old were interrupted


def is_png(path):
    """True for a complete PNG: right signature at the start, IEND chunk at the end.

    Empty, garbled or cut-off files (e.g. from a power cut mid-write) fail.
    """
    try:
        with open(path, "rb") as f:
            if f.read(8) != PNG_SIGNATURE:
                return False
            f.seek(-12, os.SEEK_END)
            return f.read(12)[4:8] == b"IEND"
    except OSError:
        return False


def _picture_files(images_dir):
    """All picture PNGs except output.png and hidden in-progress files."""
    if not os.path.isdir(images_dir):
        return []
    return [
        os.path.join(images_dir, f)
        for f in os.listdir(images_dir)
        if f.endswith(".png") and f != "output.png" and not f.startswith(".")
    ]


def list_images(images_dir):
    """Valid generated PNGs, newest first."""
    files = [p for p in _picture_files(images_dir) if is_png(p)]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def broken_images(images_dir, min_age_s=BROKEN_MIN_AGE_S, now=None):
    """Files to throw away: picture files that aren't complete PNGs, and hidden
    in-progress files left behind by an interrupted run."""
    now = time.time() if now is None else now
    broken = [p for p in _picture_files(images_dir)
              if not is_png(p) and now - os.path.getmtime(p) > min_age_s]
    if os.path.isdir(images_dir):
        for f in os.listdir(images_dir):
            p = os.path.join(images_dir, f)
            if f.startswith(".generating-") and now - os.path.getmtime(p) > STALE_PARTIAL_S:
                broken.append(p)
    return broken


def storage_settings(cfg):
    """(keep_images, keep_days, min_free_gb) from config.

    Older configs set generate.keep_images; it's still honoured.
    """
    s = cfg["storage"]
    keep_images = s["keep_images"] or cfg["generate"].get("keep_images", 0)
    return keep_images, s["keep_days"], s["min_free_gb"]


def free_bytes(path):
    return shutil.disk_usage(path).free


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def plan(images, keep_images=0, keep_days=0, min_free_bytes=0, free_now=None, now=None):
    """Return the images (from `images`, newest first) that should be deleted.

    Pure function: decides, doesn't touch any files.
    """
    now = time.time() if now is None else now
    keep = list(images)
    delete = []

    if keep_images > 0:
        cut = max(keep_images, MIN_KEEP)
        delete += keep[cut:]
        keep = keep[:cut]

    if keep_days > 0:
        cutoff = now - keep_days * 86400
        old = [p for p in keep[MIN_KEEP:] if os.path.getmtime(p) < cutoff]
        delete += old
        keep = [p for p in keep if p not in old]

    if min_free_bytes > 0 and free_now is not None:
        free = free_now + sum(_size(p) for p in delete)
        while free < min_free_bytes and len(keep) > MIN_KEEP:
            oldest = keep.pop()
            delete.append(oldest)
            free += _size(oldest)

    return delete


def remove(path):
    """Delete a picture and its .txt. Returns bytes freed."""
    freed = 0
    for p in (path, os.path.splitext(path)[0] + ".txt"):
        if os.path.exists(p):
            freed += _size(p)
            os.remove(p)
    return freed


def cleanup(cfg, images_dir=None, dry_run=False, log=print):
    """Apply the [storage] rules. Returns the list of deleted (or would-be) paths."""
    images_dir = images_dir or resolve(cfg["paths"]["images_dir"])
    broken = broken_images(images_dir)
    for path in broken:
        if not dry_run:
            remove(path)
        log(f"{'Would delete' if dry_run else 'Deleted'} broken picture {os.path.basename(path)}")
    images = list_images(images_dir)
    if not images:
        return broken
    keep_images, keep_days, min_free_gb = storage_settings(cfg)
    doomed = plan(images, keep_images, keep_days, int(min_free_gb * GB),
                  free_bytes(images_dir))
    freed = 0
    for path in doomed:
        freed += _size(path) if dry_run else remove(path)
        log(f"{'Would delete' if dry_run else 'Deleted'} {os.path.basename(path)}")
    if doomed:
        log(f"{'Would free' if dry_run else 'Freed'} {freed / 1024**2:.0f} MB "
            f"({len(doomed)} picture(s))")
    return broken + doomed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Delete old pictures per [storage] in config.toml.")
    ap.add_argument("--dry-run", action="store_true", help="Only show what would be deleted")
    args = ap.parse_args(argv)

    cfg = load_config()
    images_dir = resolve(cfg["paths"]["images_dir"])
    keep_images, keep_days, min_free_gb = storage_settings(cfg)
    images = list_images(images_dir)
    used = sum(_size(p) for p in images)
    print(f"Pictures: {len(images)} using {used / 1024**2:.0f} MB in {images_dir}")
    if os.path.isdir(images_dir):
        print(f"Free space: {free_bytes(images_dir) / GB:.1f} GB")
    print(f"Rules: keep_images={keep_images or 'no limit'}  keep_days={keep_days or 'no limit'}  "
          f"min_free_gb={min_free_gb or 'off'}")
    if not cleanup(cfg, images_dir, dry_run=args.dry_run):
        print("Nothing to delete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
