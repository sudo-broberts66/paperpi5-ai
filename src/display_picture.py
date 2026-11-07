#!/usr/bin/env python3
"""Show an image on the Inky Impression.

Based on display_picture.py from https://github.com/dylski/PaperPiAI
(MIT, Dylan Banarse), adapted for inky 2.x / Raspberry Pi 5 / Spectra 6.
"""

import argparse
import fcntl
import os
import sys

from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402

DEFAULT_RESOLUTION = (800, 480)


def fit_image(image, width, height, mode="resize"):
    """Fit image to width x height.

    mode "resize": stretch to fit (fine when generated at display size).
    mode "crop":   scale to cover, then centre crop (keeps aspect ratio).
    mode "pad":    scale to fit inside, then pad with white.
    """
    image = image.convert("RGB")
    if image.size == (width, height):
        return image
    if mode == "crop":
        return ImageOps.fit(image, (width, height), Image.LANCZOS)
    if mode == "pad":
        return ImageOps.pad(image, (width, height), Image.LANCZOS, color="white")
    return image.resize((width, height), Image.LANCZOS)


def prepare(image_path, panel_w, panel_h, portrait=False, mode="resize"):
    """Return an image sized for the panel's native (landscape) orientation."""
    target_w, target_h = (panel_h, panel_w) if portrait else (panel_w, panel_h)
    image = fit_image(Image.open(image_path), target_w, target_h, mode)
    if image.height > image.width:
        # Panel is natively landscape: rotate portrait content onto it.
        image = image.rotate(90, expand=True)
    return image


def main(argv=None):
    cfg = load_config()
    d = cfg["display"]

    ap = argparse.ArgumentParser(description="Show an image on the Inky display.")
    ap.add_argument("image", nargs="?",
                    default=os.path.join(cfg["paths"]["images_dir"], "output.png"),
                    help="Image to show (default: <images_dir>/output.png)")
    ap.add_argument("-p", "--portrait", action="store_true", default=d["portrait"],
                    help="Portrait orientation")
    ap.add_argument("-m", "--mode", choices=["resize", "crop", "pad"], default="resize",
                    help="How to fit images that aren't the display size")
    ap.add_argument("-r", "--resize_only", action="store_true",
                    help="(kept for compatibility; same as --mode resize)")
    ap.add_argument("-c", "--centre_crop", action="store_true",
                    help="(kept for compatibility; same as --mode crop)")
    ap.add_argument("--saturation", type=float, default=d["saturation"])
    ap.add_argument("--type", default=d["type"],
                    help="Force the display type, e.g. spectra73 (default: auto-detect)")
    ap.add_argument("-s", "--simulate_display", action="store_true",
                    help="Don't touch the display; use --width/--height")
    ap.add_argument("--width", type=int, default=DEFAULT_RESOLUTION[0])
    ap.add_argument("--height", type=int, default=DEFAULT_RESOLUTION[1])
    ap.add_argument("-o", "--output", default="",
                    help="Also save the prepared image here")
    args = ap.parse_args(argv)

    mode = "crop" if args.centre_crop else args.mode
    image_path = resolve(args.image)
    if not os.path.exists(image_path):
        print(f"ERROR: image not found: {image_path}", file=sys.stderr)
        return 1

    inky = None
    panel_w, panel_h = args.width, args.height
    if not args.simulate_display:
        from inky_display import open_inky

        try:
            inky = open_inky(args.type)
        except RuntimeError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        panel_w, panel_h = inky.resolution
        print(f"Display: {type(inky).__module__} {panel_w}x{panel_h}")

    image = prepare(image_path, panel_w, panel_h, args.portrait, mode)

    if args.output:
        image.save(resolve(args.output))
        print(f"Saved prepared image to {args.output}")

    if inky is not None:
        # Only one process may drive the panel at a time (timer vs buttons).
        with open("/tmp/paperpi-display.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            print("Updating display (takes ~30 seconds)...", flush=True)
            inky.set_image(image, saturation=args.saturation)
            inky.show()
        print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
