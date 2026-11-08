#!/usr/bin/env python3
"""Inky Impression button handler.

  A: show the latest image
  B: step back to an older image
  C: step forward to a newer image
  D: hold (3 s by default) to shut down

Test the buttons without changing the display (stop the service first):
  sudo systemctl stop paperpi-buttons.service
  venv/bin/python src/display_buttons.py --test

Based on display_buttons.py from https://github.com/dylski/PaperPiAI
(MIT, Dylan Banarse). Paths and pins now come from config.toml.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402
from generate_picture import CURRENT_FILE, SHARED_FILE, list_images  # noqa: E402

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
DEBOUNCE_S = 0.3  # ignore repeat edges on the same button within this time


def log(msg):
    print(msg, flush=True)  # flush so messages reach the journal immediately


def collect_presses(events, labels, last_seen, debounce_s=DEBOUNCE_S):
    """Turn raw edge events into button presses, dropping contact bounce.

    events: objects with .line_offset and .timestamp_ns (kernel time).
    labels: {line_offset: "A".."D"}. last_seen is updated in place.
    Returns the labels pressed, oldest first.
    """
    presses = []
    for event in events:
        label = labels.get(event.line_offset)
        if label is None:
            continue
        t = event.timestamp_ns / 1e9
        if t - last_seen.get(label, float("-inf")) < debounce_s:
            continue
        last_seen[label] = t
        presses.append(label)
    return presses


def current_index(images_dir, images):
    """Index in `images` (newest first) of the image currently shown."""
    try:
        with open(os.path.join(images_dir, CURRENT_FILE)) as f:
            name = f.read().strip()
    except FileNotFoundError:
        return 0
    for i, path in enumerate(images):
        if os.path.basename(path) == name:
            return i
    return 0


def target_index(action, current, count):
    """New index for one button action, or None if there's nowhere to go."""
    key = {"latest": "A", "older": "B", "newer": "C"}[action]
    return navigate([key], current, count)


def navigate(presses, current, count):
    """Index to show after a sequence of A/B/C presses, or None for no change.

    A jumps to the newest picture (index 0) and always redraws it. B steps one
    older (+1) and C one newer (-1); steps past either end stop at the end.
    """
    if count == 0:
        return None
    target = current
    for p in presses:
        if p == "A":
            target = 0
        elif p == "B":
            target = min(target + 1, count - 1)
        elif p == "C":
            target = max(target - 1, 0)
    if target == current and "A" not in presses:
        return None
    return target


class Frame:
    def __init__(self, cfg):
        self.cfg = cfg
        self.images_dir = resolve(cfg["paths"]["images_dir"])

    def show(self, presses):
        """Handle A/B/C presses (a list, oldest first). Returns True if the display changed."""
        if isinstance(presses, str):  # single action name, e.g. "latest"
            presses = [{"latest": "A", "older": "B", "newer": "C"}[presses]]
        images = list_images(self.images_dir) if os.path.isdir(self.images_dir) else []
        current = current_index(self.images_dir, images)
        new = navigate(presses, current, len(images))
        if new is None:
            if not images:
                log("No pictures yet")
            elif current == 0 and presses[-1] in "AC":
                log("Already showing the newest picture")
            else:
                log("Already showing the oldest picture")
            return False
        path = images[new]
        log(f"Showing picture {new + 1} of {len(images)} (1 = newest): {os.path.basename(path)}")
        shutil.copy2(path, os.path.join(self.images_dir, SHARED_FILE))
        with open(os.path.join(self.images_dir, CURRENT_FILE), "w") as f:
            f.write(os.path.basename(path))
        subprocess.run([sys.executable, os.path.join(SRC_DIR, "display_picture.py")])
        return True

    def shutdown(self):
        log("Shutting down")
        subprocess.run(["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Inky Impression button handler.")
    ap.add_argument("--test", action="store_true",
                    help="Just print button presses; don't change the display or shut down")
    args = ap.parse_args(argv)

    import gpiod
    import gpiodevice
    from gpiod.line import Bias, Direction, Edge, Value

    cfg = load_config()
    b = cfg["buttons"]
    frame = Frame(cfg)
    pins = {"A": b["pin_a"], "B": b["pin_b"], "C": b["pin_c"], "D": b["pin_d"]}

    settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,
                                  edge_detection=Edge.FALLING)
    chip = gpiodevice.find_chip_by_platform()
    labels = {chip.line_offset_from_id(pin): label for label, pin in pins.items()}
    offsets = {label: offset for offset, label in labels.items()}
    request = chip.request_lines(consumer="paperpi-buttons",
                                 config=dict.fromkeys(labels, settings))

    def pressed(label):
        # Pulled up, so a pressed button reads low (INACTIVE).
        return request.get_value(offsets[label]) == Value.INACTIVE

    def held_for(label, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not pressed(label):
                return False
            time.sleep(0.05)
        return True

    hold = b["shutdown_hold_seconds"]
    log(f"Watching buttons {pins}" + (" (test mode)" if args.test else ""))
    last_seen = {}
    try:
        while True:
            if not request.wait_edge_events(1.0):
                continue
            presses = collect_presses(request.read_edge_events(), labels, last_seen)
            if not presses:
                continue
            log(f"Pressed: {' '.join(presses)}")
            if args.test:
                continue
            if presses[-1] == "D":
                if held_for("D", hold):
                    frame.shutdown()
                else:
                    log(f"D: hold for {hold}s to shut down")
                continue
            # Presses made while the screen was refreshing arrive together
            # here and are combined (e.g. B B = back two) into one refresh.
            frame.show([p for p in presses if p != "D"])
    except KeyboardInterrupt:
        pass
    finally:
        request.release()


if __name__ == "__main__":
    main()
