"""Shared configuration loader for PaperPi5-AI.

Values come from (lowest to highest priority): built-in DEFAULTS,
config.toml in the repository root (or the file named by $PAPERPI_CONFIG),
then command-line arguments in each script.
"""

import copy
import os
import tomllib

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "paths": {
        "images_dir": "images",
        "sd_binary": "OnnxStream/src/build/sd",
        "model_dir": "models/stable-diffusion-xl-turbo-1.0-anyshape-onnxstream",
        "prompts_file": "prompts/flowers.json",
    },
    "generate": {
        "width": 800,
        "height": 480,
        "steps": 3,
        "ram_mode": True,
        "low_mem": False,
        "keep_images": 0,
        "extra_sd_args": [],
    },
    "llm": {
        "enabled": True,
        "theme": "a sci-fi landscape on an alien planet",
        "inspiration_file": "prompts/planets.json",
        "keep_style": True,
        "temperature": 0.9,
        "max_words": 35,
        "recent_count": 8,
        "threads": 4,
        "timeout_seconds": 300,
        "model": "models/llm/qwen2.5-3b-instruct-q4_k_m.gguf",
        "model_url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
    },
    "display": {
        "portrait": False,
        "saturation": 0.5,
        "delay_seconds": 120,
        "type": "",
    },
    "schedule": {
        "on_calendar": "*-*-* 06:00:00",
    },
    "buttons": {
        "pin_a": 5,
        "pin_b": 6,
        "pin_c": 16,
        "pin_d": 24,
        "shutdown_hold_seconds": 3,
    },
}


def _merge(base, override):
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def config_path():
    return os.environ.get("PAPERPI_CONFIG", os.path.join(REPO_ROOT, "config.toml"))


def load_config(path=None):
    """Return the merged configuration dict."""
    cfg = copy.deepcopy(DEFAULTS)
    path = path or config_path()
    if os.path.exists(path):
        with open(path, "rb") as f:
            _merge(cfg, tomllib.load(f))
    return cfg


def resolve(path):
    """Resolve a config path relative to the repository root."""
    path = os.path.expanduser(path)
    if os.path.isabs(path):
        return path
    return os.path.join(REPO_ROOT, path)


def get(cfg, dotted):
    """get(cfg, "display.saturation") -> value. Used by shell scripts."""
    node = cfg
    for part in dotted.split("."):
        node = node[part]
    return node


if __name__ == "__main__":
    # Usage: python src/config.py display.saturation
    import sys

    value = get(load_config(), sys.argv[1])
    if sys.argv[1].startswith("paths."):
        value = resolve(value)
    print(str(value).lower() if isinstance(value, bool) else value)
