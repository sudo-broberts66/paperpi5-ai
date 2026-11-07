#!/bin/bash
# PaperPi5-AI diagnostics. Checks the display wiring/config, the Python
# environment, the Stable Diffusion build and the model.
#
# Usage: scripts/doctor.sh [--generate] [--llm]
#   --generate  also make a small 1-step test image (takes a minute or two)
#   --llm       also ask the local LLM for a test prompt (takes up to a minute)

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/venv/bin/python"
BOOT_CONFIG="/boot/firmware/config.txt"
[[ -f "$BOOT_CONFIG" ]] || BOOT_CONFIG="/boot/config.txt"
FAILS=0
TEST_GENERATE=0; TEST_LLM=0
for arg in "$@"; do
    case "$arg" in
        --generate) TEST_GENERATE=1 ;;
        --llm) TEST_LLM=1 ;;
    esac
done

pass() { printf '\033[1;32mPASS\033[0m %s\n' "$1"; }
fail() { printf '\033[1;31mFAIL\033[0m %s\n     fix: %s\n' "$1" "$2"; FAILS=$((FAILS + 1)); }
info() { printf '     %s\n' "$1"; }

echo "Board: $(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)"
echo "OS:    $(. /etc/os-release && echo "$PRETTY_NAME")"
echo

# --- Display --------------------------------------------------------------
if [[ -e /dev/spidev0.0 ]]; then pass "SPI enabled (/dev/spidev0.0)"
else fail "SPI not enabled" "sudo raspi-config nonint do_spi 0 && sudo reboot"; fi

if ls /dev/i2c-* > /dev/null 2>&1; then pass "I2C enabled ($(ls /dev/i2c-* | tr '\n' ' '))"
else fail "I2C not enabled" "sudo raspi-config nonint do_i2c 0 && sudo reboot"; fi

if grep -qxF "dtoverlay=spi0-0cs" "$BOOT_CONFIG" 2>/dev/null; then pass "dtoverlay=spi0-0cs in $BOOT_CONFIG"
else fail "dtoverlay=spi0-0cs missing from $BOOT_CONFIG (GPIO8 chip-select conflict)" \
    "run scripts/install.sh, or add the line under [all] and reboot"; fi

if command -v i2cdetect > /dev/null; then
    found=""
    for bus in /dev/i2c-*; do
        n="${bus##*-}"
        if i2cdetect -y "$n" 0x50 0x50 2>/dev/null | grep -q " 50"; then found="$n"; break; fi
    done
    if [[ -n "$found" ]]; then pass "Inky EEPROM found at 0x50 on i2c-$found"
    else fail "Inky EEPROM not found on I2C (address 0x50)" \
        "check the display is pressed fully onto all 40 GPIO pins, and that I2C is enabled"; fi
fi

for group in spi i2c gpio; do
    if ! id -nG | tr ' ' '\n' | grep -qx "$group"; then
        fail "user $USER is not in group '$group'" "sudo usermod -aG $group $USER && sudo reboot"
    fi
done

# --- Python ---------------------------------------------------------------
if [[ -x "$PY" ]]; then
    if v=$("$PY" -c 'from importlib.metadata import version; print(version("inky"))' 2>/dev/null); then
        if "$PY" -c "import sys; v=tuple(int(x) for x in '$v'.split('.')[:2]); sys.exit(v < (2, 1))"; then
            pass "inky $v installed"
        else
            fail "inky $v is too old for the Spectra 6 display / Pi 5" "venv/bin/pip install -U 'inky>=2.1'"
        fi
    else
        fail "inky not installed in venv" "venv/bin/pip install -r requirements.txt"
    fi
    if out=$(cd "$REPO/src" && "$PY" -c '
from config import load_config
from inky_display import open_inky
d = open_inky(load_config()["display"]["type"])
print(type(d).__module__, "%dx%d" % d.resolution)' 2>&1); then
        pass "Inky display detected: $(echo "$out" | tail -1)"
        [[ "$out" == *inky_e673* ]] || info "(expected inky.inky_e673 for the Impression 7.3\" Spectra 6)"
    else
        fail "Could not open the Inky display" "see error below; then run scripts/doctor.sh again"
        echo "$out" | sed 's/^/     | /' | tail -8
    fi
else
    fail "Python venv missing ($PY)" "scripts/install.sh"
fi

# --- Stable Diffusion -----------------------------------------------------
if [[ -x "$PY" ]]; then
    SD_BIN="$("$PY" "$REPO/src/config.py" paths.sd_binary)"
    MODEL_DIR="$("$PY" "$REPO/src/config.py" paths.model_dir)"
    if [[ -x "$SD_BIN" ]]; then pass "OnnxStream built ($SD_BIN)"
    else fail "OnnxStream sd binary missing ($SD_BIN)" "scripts/install.sh"; fi
    if out=$("$PY" "$REPO/src/check_model.py" "$MODEL_DIR" 2>&1); then pass "$out"
    else fail "Model problem: $out" "re-run scripts/install.sh to resume the download"; fi

    # --- Local LLM ---------------------------------------------------------
    LLM_ENABLED="$("$PY" "$REPO/src/config.py" llm.enabled)"
    if [[ "$LLM_ENABLED" == "true" ]]; then
        if out=$("$PY" "$REPO/src/check_llm.py" 2>&1); then pass "$out"
        else fail "LLM problem: $(echo "$out" | tr '\n' ' ')" "scripts/install.sh --llm"; fi
    else
        info "Local LLM prompts are off (llm.enabled = false); using the prompt library"
    fi
fi

free_gb=$(( $(df --output=avail -k "$REPO" | tail -1) / 1024 / 1024 ))
if [[ $free_gb -ge 2 ]]; then pass "Disk space: ${free_gb} GB free"
else fail "Only ${free_gb} GB free" "set generate.keep_images in config.toml or delete old images"; fi

if [[ -x "$PY" ]]; then
    ON_CAL="$("$PY" "$REPO/src/config.py" schedule.on_calendar)"
    if systemd-analyze calendar "$ON_CAL" > /dev/null 2>&1; then pass "Schedule \"$ON_CAL\" is valid"
    else fail "schedule.on_calendar \"$ON_CAL\" is not a valid schedule" \
        "fix it in config.toml (see README 'Changing the schedule'), then scripts/install.sh --services"; fi
fi
if systemctl is-enabled paperpi.timer > /dev/null 2>&1; then
    pass "paperpi.timer enabled (next: $(systemctl show paperpi.timer -p NextElapseUSecRealtime --value))"
else fail "paperpi.timer not enabled" "scripts/install.sh --services"; fi
if systemctl is-active paperpi-buttons.service > /dev/null 2>&1; then pass "paperpi-buttons.service running"
else fail "paperpi-buttons.service not running" "journalctl -u paperpi-buttons.service -n 30"; fi

# --- Optional generation test --------------------------------------------
if [[ $TEST_LLM -eq 1 && $FAILS -eq 0 ]]; then
    echo; echo "Asking the local LLM for a test prompt..."
    if "$PY" "$REPO/src/llm_prompt.py"; then pass "LLM wrote a prompt"
    else fail "LLM test failed" "see the error above; scripts/install.sh --llm --rebuild"; fi
fi

if [[ $TEST_GENERATE -eq 1 && $FAILS -eq 0 ]]; then
    echo; echo "Generating a 1-step 512x512 test image..."
    tmp="$(mktemp -d)"
    start=$(date +%s)
    if "$PY" "$REPO/src/generate_picture.py" "$tmp" --steps 1 --width 512 --height 512 \
        --no-llm --prompt "a red apple on a white table, flat illustration"; then
        pass "Test image generated in $(( $(date +%s) - start ))s: $(ls "$tmp"/*.png | head -1)"
    else
        fail "Test generation failed" "try scripts/install.sh --rebuild; see output above"
    fi
fi

echo
if [[ $FAILS -eq 0 ]]; then echo "All checks passed."; else echo "$FAILS check(s) failed."; fi
exit $(( FAILS > 0 ))
