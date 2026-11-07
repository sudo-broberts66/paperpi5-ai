#!/usr/bin/env python3
"""Draw colour bars and some text on the Inky display to check it works."""

import argparse
import os
import socket
import sys
import time

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config  # noqa: E402

COLOURS = [
    ("black", (0, 0, 0)),
    ("white", (255, 255, 255)),
    ("red", (255, 0, 0)),
    ("yellow", (255, 255, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
]


def make_test_image(width, height):
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    bar_w = width / len(COLOURS)
    bar_h = int(height * 0.7)
    for i, (name, rgb) in enumerate(COLOURS):
        x0, x1 = int(i * bar_w), int((i + 1) * bar_w)
        draw.rectangle([x0, 0, x1, bar_h], fill=rgb, outline=(0, 0, 0))
        draw.text((x0 + 8, bar_h + 8), name, fill=(0, 0, 0))
    lines = [
        "PaperPi5-AI display test",
        f"{width}x{height}  host: {socket.gethostname()}",
        time.strftime("%Y-%m-%d %H:%M:%S"),
    ]
    for n, line in enumerate(lines):
        draw.text((10, bar_h + 30 + n * 16), line, fill=(0, 0, 0))
    return image


def main(argv=None):
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--type", default=cfg["display"]["type"],
                    help="Force display type, e.g. spectra73")
    ap.add_argument("-o", "--output", help="Save the test image instead of displaying it")
    args = ap.parse_args(argv)

    if args.output:
        make_test_image(800, 480).save(args.output)
        print(f"Saved {args.output}")
        return 0

    from inky_display import open_inky

    try:
        inky = open_inky(args.type)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    w, h = inky.resolution
    print(f"Found {type(inky).__module__} at {w}x{h}. Drawing test pattern...", flush=True)
    inky.set_image(make_test_image(w, h), saturation=cfg["display"]["saturation"])
    inky.show()
    print("Done. You should see six colour bars.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
