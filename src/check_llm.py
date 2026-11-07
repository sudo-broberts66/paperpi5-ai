#!/usr/bin/env python3
"""Check the local LLM is installed: llama-cpp-python imports and the GGUF
model file is complete. Exit code 0 = OK, 1 = problem (details printed)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import load_config, resolve  # noqa: E402

MIN_BYTES = 500 * 1024**2  # small 1-4B models are 0.7-3 GB


def check_model_file(path, min_bytes=MIN_BYTES):
    """Return a list of problems with the GGUF model file."""
    if not os.path.exists(path):
        if os.path.exists(path + ".part"):
            return [f"download not finished: {path}.part"]
        return [f"model file not found: {path}"]
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic != b"GGUF":
        return [f"{path} is not a GGUF model file (maybe an error page was downloaded)"]
    size = os.path.getsize(path)
    if size < min_bytes:
        return [f"{path} is only {size / 1024**2:.0f} MB; download may be incomplete"]
    return []


def check(cfg):
    problems = []
    try:
        import llama_cpp  # noqa: F401
    except ImportError:
        problems.append("llama-cpp-python is not installed (scripts/install.sh --llm)")
    problems += check_model_file(resolve(cfg["llm"]["model"]))
    return problems


if __name__ == "__main__":
    cfg = load_config()
    issues = check(cfg)
    for issue in issues:
        print(f"ERROR: {issue}")
    if not issues:
        path = resolve(cfg["llm"]["model"])
        print(f"LLM OK: {os.path.basename(path)} ({os.path.getsize(path) / 1024**3:.1f} GB)")
    sys.exit(1 if issues else 0)
