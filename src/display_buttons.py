#!/usr/bin/env python3
"""Inky Impression button handler.

  A: show the latest image
  B: step back to an older image
  C: step forward to a newer image
  D: hold (3 s by default) to shut down

Based on display_buttons.py from https://github.com/dylski/PaperPiAI
(MIT, Dylan Banarse). Paths and pins now come from config.toml.
"""

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402
from generate_picture import CURRENT_FILE, SHARED_FILE, list_images  # noqa: E402

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
DEBOUNCE_S = 0.05


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
    """New index for a button action, or None if there's nowhere to go."""
    if count == 0:
        return None
    if action == "latest":
        new = 0
    elif action == "older":
        new = current + 1
    elif action == "newer":
        new = current - 1
    else:
        raise ValueError(action)
    if new < 0 or new >= count:
        return None
    return new


class Frame:
    def __init__(self, cfg):
        self.cfg = cfg
        self.images_dir = resolve(cfg["paths"]["images_dir"])

    def show(self, action):
        images = list_images(self.images_dir) if os.path.isdir(self.images_dir) else []
        new = target_index(action, current_index(self.images_dir, images), len(images))
        if new is None:
            print(f"{action}: no image to show")
            return
        path = images[new]
        print(f"{action}: showing {os.path.basename(path)}", flush=True)
        shutil.copy2(path, os.path.join(self.images_dir, SHARED_FILE))
        with open(os.path.join(self.images_dir, CURRENT_FILE), "w") as f:
            f.write(os.path.basename(path))
        subprocess.run([sys.executable, os.path.join(SRC_DIR, "display_picture.py")])

    def shutdown(self):
        print("Shutting down", flush=True)
        subprocess.run(["sudo", "-n", "/usr/sbin/shutdown", "-h", "now"])


def main():
    import gpiod
    import gpiodevice
    from gpiod.line import Bias, Direction, Edge, Value

    cfg = load_config()
    b = cfg["buttons"]
    frame = Frame(cfg)
    pins = {"A": b["pin_a"], "B": b["pin_b"], "C": b["pin_c"], "D": b["pin_d"]}
    actions = {"A": "latest", "B": "older", "C": "newer"}

    settings = gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,
                                  edge_detection=Edge.FALLING)
    chip = gpiodevice.find_chip_by_platform()
    offsets = {chip.line_offset_from_id(pin): label for label, pin in pins.items()}
    request = chip.request_lines(consumer="paperpi-buttons",
                                 config=dict.fromkeys(offsets, settings))

    def pressed(offset):
        return request.get_value(offset) == Value.INACTIVE  # pulled up; low = pressed

    def held_for(offset, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if not pressed(offset):
                return False
            time.sleep(0.05)
        return True

    print(f"Watching buttons {pins}", flush=True)
    try:
        while True:
            if not request.wait_edge_events(1.0):
                continue
            for event in request.read_edge_events():
                offset = event.line_offset
                time.sleep(DEBOUNCE_S)
                if not pressed(offset):
                    continue  # bounce
                label = offsets[offset]
                if label == "D":
                    if held_for(offset, b["shutdown_hold_seconds"]):
                        frame.shutdown()
                    else:
                        print(f"D: hold for {b['shutdown_hold_seconds']}s to shut down")
                else:
                    frame.show(actions[label])
                # Drop any events queued while we were busy (e.g. during a refresh).
                while request.wait_edge_events(0):
                    request.read_edge_events()
    except KeyboardInterrupt:
        pass
    finally:
        request.release()


if __name__ == "__main__":
    main()
