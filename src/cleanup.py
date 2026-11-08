#!/usr/bin/env python3
"""Delete old pictures so the SD card never fills up.

Three rules, set under [storage] in config.toml. A picture is deleted if any
rule says so:

  keep_images  keep only the newest N pictures            (0 = no limit)
  keep_days    delete pictures older than N days          (0 = no limit)
  min_free_gb  if free space drops below this, delete the oldest pictures
               until it's back above it                   (0 = off)

The newest picture is never deleted. Each picture's .txt prompt file goes with it.

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


def list_images(images_dir):
    """Generated PNGs, newest first, excluding output.png."""
    if not os.path.isdir(images_dir):
        return []
    files = [
        os.path.join(images_dir, f)
        for f in os.listdir(images_dir)
        if f.endswith(".png") and f != "output.png"
    ]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


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
    images = list_images(images_dir)
    if not images:
        return []
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
    return doomed


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
