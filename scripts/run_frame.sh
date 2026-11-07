#!/bin/bash
# Generate a new picture, wait for the Pi to cool, then show it.
# Run by paperpi.service; you can also run it by hand.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/venv/bin/python"
cd "$REPO"

"$PY" src/generate_picture.py "$@"

DELAY="$("$PY" src/config.py display.delay_seconds)"
if [[ "$DELAY" -gt 0 ]]; then
    echo "Waiting ${DELAY}s before refreshing the display..."
    sleep "$DELAY"
fi

"$PY" src/display_picture.py
