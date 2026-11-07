#!/usr/bin/env python3
"""Check that the OnnxStream model was really downloaded.

A `git clone` from HuggingFace without git-lfs leaves tiny "pointer" text files
instead of the real weights. This finds them.

Exit code 0 = OK, 1 = problem (details printed).
"""

import os
import sys

LFS_HEADER = b"version https://git-lfs"
MIN_TOTAL_BYTES = 5 * 1024**3  # the SDXL Turbo model is ~8GB


def find_lfs_pointers(model_dir):
    pointers = []
    for root, dirs, files in os.walk(model_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > 1024:
                    continue
                with open(path, "rb") as f:
                    if f.read(len(LFS_HEADER)) == LFS_HEADER:
                        pointers.append(path)
            except OSError:
                continue
    return pointers


def total_size(model_dir):
    size = 0
    for root, dirs, files in os.walk(model_dir):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            try:
                size += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return size


def check(model_dir, min_bytes=MIN_TOTAL_BYTES):
    """Return a list of problems (empty when the model looks complete)."""
    if not os.path.isdir(model_dir):
        return [f"model directory not found: {model_dir}"]
    problems = []
    pointers = find_lfs_pointers(model_dir)
    if pointers:
        problems.append(
            f"{len(pointers)} file(s) are git-lfs pointers, not real weights "
            f"(e.g. {os.path.relpath(pointers[0], model_dir)}). "
            "Run: git lfs install && git -C <model_dir> lfs pull"
        )
    size = total_size(model_dir)
    if size < min_bytes:
        problems.append(f"model is only {size / 1024**3:.1f} GB; expected ~8 GB")
    return problems


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from config import load_config, resolve

    target = sys.argv[1] if len(sys.argv) > 1 else resolve(load_config()["paths"]["model_dir"])
    issues = check(target)
    for issue in issues:
        print(f"ERROR: {issue}")
    if not issues:
        print(f"Model OK: {target} ({total_size(target) / 1024**3:.1f} GB)")
    sys.exit(1 if issues else 0)
