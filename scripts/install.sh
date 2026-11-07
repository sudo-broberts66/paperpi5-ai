#!/bin/bash
# PaperPi5-AI installer for Raspberry Pi 5 + Raspberry Pi OS Bookworm (64-bit)
# + Pimoroni Inky Impression 7.3" (Spectra 6).
#
# Safe to re-run: finished steps are skipped.
#
# Usage: scripts/install.sh [--services] [--skip-model] [--rebuild] [--help]
#   --services    only (re)install the systemd services and timer
#   --skip-model  don't download the ~8GB model now
#   --rebuild     rebuild OnnxStream even if it is already built
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO/venv"
PY="$VENV/bin/python"
ONNX_DIR="$REPO/OnnxStream"
SD_BIN="$ONNX_DIR/src/build/sd"
MODEL_REPO="https://huggingface.co/vitoplantamura/stable-diffusion-xl-turbo-1.0-anyshape-onnxstream"
BOOT_CONFIG="/boot/firmware/config.txt"
[[ -f "$BOOT_CONFIG" ]] || BOOT_CONFIG="/boot/config.txt"
RUN_USER="${SUDO_USER:-$USER}"

ONLY_SERVICES=0; SKIP_MODEL=0; REBUILD=0; REBOOT_NEEDED=0
for arg in "$@"; do
    case "$arg" in
        --services) ONLY_SERVICES=1 ;;
        --skip-model) SKIP_MODEL=1 ;;
        --rebuild) REBUILD=1 ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*"; exit 1; }

if [[ $EUID -eq 0 ]]; then
    die "Run this as your normal user (not with sudo). It will ask for sudo when needed."
fi

preflight() {
    step "Checking system"
    [[ "$(uname -m)" == "aarch64" ]] || warn "Expected a 64-bit OS (aarch64), found $(uname -m)."
    local model codename
    model="$(tr -d '\0' < /proc/device-tree/model 2>/dev/null || echo unknown)"
    codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-unknown}")"
    echo "Board: $model"
    echo "OS:    $codename"
    [[ "$model" == *"Raspberry Pi 5"* ]] || warn "This installer is written for a Raspberry Pi 5."
    [[ "$codename" == "bookworm" ]] || warn "This installer is tested on Bookworm; you have '$codename'."
    local free_gb
    free_gb=$(( $(df --output=avail -k "$REPO" | tail -1) / 1024 / 1024 ))
    echo "Free disk: ${free_gb} GB"
    if [[ $SKIP_MODEL -eq 0 && ! -d "$REPO/models" && $free_gb -lt 20 ]]; then
        die "Need about 20 GB free for the build and model download (have ${free_gb} GB)."
    fi
}

install_apt() {
    step "Installing system packages"
    sudo apt-get update
    sudo apt-get install -y build-essential cmake git git-lfs \
        python3-dev python3-venv python3-pip i2c-tools
}

enable_interfaces() {
    step "Enabling SPI and I2C for the Inky display"
    sudo raspi-config nonint do_spi 0
    sudo raspi-config nonint do_i2c 0
    # Lines Pimoroni's own inky installer adds. spi0-0cs stops the kernel
    # claiming GPIO8 (chip select), which the inky library drives itself.
    local line missing=()
    for line in "dtoverlay=spi0-0cs" "dtoverlay=i2c1-pi5"; do
        grep -qxF "$line" "$BOOT_CONFIG" || missing+=("$line")
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        sudo cp "$BOOT_CONFIG" "$BOOT_CONFIG.paperpi-backup-$(date +%Y%m%d%H%M%S)"
        echo "Adding ${missing[*]} to $BOOT_CONFIG"
        { printf '\n# Added by PaperPi5-AI for the Inky display\n[all]\n'
          printf '%s\n' "${missing[@]}"; } | sudo tee -a "$BOOT_CONFIG" > /dev/null
        REBOOT_NEEDED=1
    fi
    local group
    for group in spi i2c gpio; do
        if ! id -nG "$RUN_USER" | tr ' ' '\n' | grep -qx "$group"; then
            sudo usermod -aG "$group" "$RUN_USER"
            REBOOT_NEEDED=1
        fi
    done
}

install_python() {
    step "Setting up Python virtual environment"
    if [[ ! -x "$PY" ]]; then
        python3 -m venv --system-site-packages "$VENV"
    fi
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install --upgrade -r "$REPO/requirements.txt"
    "$PY" - <<'PYEOF'
from importlib.metadata import version
v = version("inky")
major, minor = (int(x) for x in v.split(".")[:2])
assert (major, minor) >= (2, 1), f"inky {v} is too old for Spectra 6 (need 2.1+)"
print(f"inky {v} installed")
PYEOF
}

build_onnxstream() {
    step "Building OnnxStream (Stable Diffusion engine)"
    if [[ ! -d "$ONNX_DIR/.git" ]]; then
        git clone https://github.com/vitoplantamura/OnnxStream.git "$ONNX_DIR"
    elif [[ $REBUILD -eq 1 ]]; then
        git -C "$ONNX_DIR" pull --ff-only || warn "Could not update OnnxStream; building existing copy."
    fi
    if [[ -x "$SD_BIN" && $REBUILD -eq 0 ]]; then
        echo "Already built: $SD_BIN (use --rebuild to rebuild)"
        return
    fi
    mkdir -p "$ONNX_DIR/src/build"
    cd "$ONNX_DIR/src/build"
    # XNNPACK is downloaded automatically by OnnxStream's CMake.
    if ! { cmake .. -DCMAKE_BUILD_TYPE=Release && cmake --build . --config Release -j"$(nproc)"; }; then
        warn "Build failed with MAX_SPEED=ON; retrying with -DMAX_SPEED=OFF"
        cmake .. -DCMAKE_BUILD_TYPE=Release -DMAX_SPEED=OFF
        cmake --build . --config Release -j"$(nproc)"
    fi
    cd "$REPO"
    [[ -x "$SD_BIN" ]] || die "OnnxStream build finished but $SD_BIN is missing."
    echo "Built $SD_BIN"
}

download_model() {
    step "Downloading SDXL Turbo model (~8 GB)"
    local model_dir
    model_dir="$("$PY" "$REPO/src/config.py" paths.model_dir)"
    if [[ -d "$model_dir" ]] && "$PY" "$REPO/src/check_model.py" "$model_dir"; then
        return
    fi
    git lfs install
    if [[ ! -d "$model_dir/.git" ]]; then
        mkdir -p "$(dirname "$model_dir")"
        # Clone the small files first, then fetch the large ones explicitly so a
        # dropped connection can be resumed by re-running this script.
        GIT_LFS_SKIP_SMUDGE=1 git clone --depth=1 "$MODEL_REPO" "$model_dir"
    fi
    local attempt
    for attempt in 1 2 3; do
        if git -C "$model_dir" lfs pull; then break; fi
        warn "git lfs pull failed (attempt $attempt); retrying in 10s"
        sleep 10
    done
    "$PY" "$REPO/src/check_model.py" "$model_dir" \
        || die "Model download incomplete. Re-run scripts/install.sh to resume."
    # The weights now exist twice (working files + .git/lfs cache). Drop the
    # cache to save ~8 GB; re-running this script re-downloads if ever needed.
    rm -rf "$model_dir/.git/lfs/objects"
}

setup_config() {
    step "Configuration"
    if [[ ! -f "$REPO/config.toml" ]]; then
        cp "$REPO/config.example.toml" "$REPO/config.toml"
        echo "Created config.toml (edit it to change size, schedule, etc.)"
    else
        echo "Using existing config.toml"
    fi
    mkdir -p "$("$PY" "$REPO/src/config.py" paths.images_dir)"
}

install_services() {
    step "Installing systemd services"
    local on_calendar unit
    on_calendar="$("$PY" "$REPO/src/config.py" schedule.on_calendar)"
    # A bad schedule silently disables the timer, so check it before installing.
    if ! systemd-analyze calendar "$on_calendar" > /dev/null 2>&1; then
        systemd-analyze calendar "$on_calendar" 2>&1 | sed 's/^/    /' || true
        die "schedule.on_calendar = \"$on_calendar\" in config.toml is not a valid schedule.
See 'Changing the schedule' in README.md for examples, e.g. \"*-*-* *:00/30:00\" for every 30 minutes.
The previous schedule is still installed."
    fi
    for unit in paperpi.service paperpi.timer paperpi-buttons.service; do
        sed -e "s|@USER@|$RUN_USER|g" -e "s|@REPO@|$REPO|g" -e "s|@ON_CALENDAR@|$on_calendar|g" \
            "$REPO/scripts/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
    done
    # Let the button service shut the Pi down (and nothing else) without a password.
    echo "$RUN_USER ALL=(root) NOPASSWD: /usr/sbin/shutdown" \
        | sudo tee /etc/sudoers.d/paperpi-shutdown > /dev/null
    sudo chmod 0440 /etc/sudoers.d/paperpi-shutdown
    sudo visudo -cf /etc/sudoers.d/paperpi-shutdown > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now paperpi.timer
    sudo systemctl enable paperpi-buttons.service
    if [[ $REBOOT_NEEDED -eq 0 ]]; then
        sudo systemctl restart paperpi-buttons.service
    fi
    echo "New picture schedule: $on_calendar"
    systemctl list-timers paperpi.timer --no-pager || true
}

cd "$REPO"
if [[ $ONLY_SERVICES -eq 1 ]]; then
    [[ -x "$PY" ]] || die "Run the full install first."
    install_services
    exit 0
fi

preflight
install_apt
enable_interfaces
install_python
setup_config
build_onnxstream
if [[ $SKIP_MODEL -eq 0 ]]; then download_model; else warn "Skipping model download (--skip-model)"; fi
install_services

step "Done"
if [[ $REBOOT_NEEDED -eq 1 ]]; then
    cat <<MSG
SPI/I2C settings changed. Reboot now, then run the checks:

    sudo reboot
    cd $REPO && scripts/doctor.sh
MSG
else
    "$REPO/scripts/doctor.sh" || true
fi
cat <<MSG

Next steps:
  Test the display:       venv/bin/python src/test_display.py
  Make a picture now:     sudo systemctl start paperpi.service
  Watch progress:         journalctl -fu paperpi.service
MSG
