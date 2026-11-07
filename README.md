# PaperPi5-AI

A self-contained AI picture frame: a **Raspberry Pi 5** runs Stable Diffusion
(SDXL Turbo via [OnnxStream](https://github.com/vitoplantamura/OnnxStream))
entirely offline and shows a new picture every day on a **Pimoroni Inky
Impression 7.3" (2025 Edition, Spectra 6)** e-paper display.

Based on [dylski/PaperPiAI](https://github.com/dylski/PaperPiAI) by Dylan
Banarse (MIT), which targets a Pi Zero 2 on Bullseye. This fork is reworked
for the Pi 5 and Raspberry Pi OS Bookworm.

![Examples](assets/paperpiai_examples.jpg)

## What's different from upstream

| Problem with upstream on a Pi 5 | Fix here |
| --- | --- |
| `inky==1.5.0` uses RPi.GPIO, which doesn't work on a Pi 5, and doesn't know the Spectra 6 panel | Uses `inky>=2.1` (gpiod-based, supports Spectra 6 / E673) |
| SPI claims GPIO8, so the display fails with *"GPIO8 claimed by spi0 CS0"* | Installer adds `dtoverlay=spi0-0cs` (and `i2c1-pi5`) to `/boot/firmware/config.txt`, as Pimoroni's installer does |
| Model cloned without `git lfs install`, so you get tiny pointer files and have to fetch weights by hand | Installer runs `git lfs` properly, resumes broken downloads, and **verifies** the weights |
| `--rpi-lowmem` (Pi Zero mode) makes generation very slow | Uses `--ram` (whole UNET in RAM) on the Pi 5 |
| cron + hard-coded `/home/dylski` paths | `config.toml` + systemd timer and button service |
| Easy to shut down by accident with button D | Hold D for 3 seconds to shut down |

## Hardware

* Raspberry Pi 5 (tested design: 16 GB; 8 GB should be fine)
* Pimoroni Inky Impression 7.3" **2025 Edition (Spectra 6)**, pressed fully onto the 40-pin header
* Good power supply (official 27 W USB-C)
* Active cooler recommended: generation uses all four cores for a few minutes
* microSD card or SSD with **at least 32 GB** (the model is ~8 GB, the build needs a few more)

## Install

1. Flash **Raspberry Pi OS Lite (64-bit, Bookworm)** with Raspberry Pi
   Imager. Set the hostname, user, Wi-Fi and SSH in the Imager settings.
2. SSH in, then:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/sudo-broberts66/paperpi5-ai.git
cd paperpi5-ai
scripts/install.sh
```

The installer does everything: system packages, SPI/I2C, the boot config
lines, a Python venv, the OnnxStream build (~10-20 min on a Pi 5), the ~8 GB
model download, `config.toml`, and the systemd services. It can be re-run
safely: finished steps are skipped and an interrupted model download resumes.

3. Reboot when it tells you to, then check everything:

```bash
sudo reboot
```

```bash
cd ~/paperpi5-ai && scripts/doctor.sh
```

Every line should say **PASS**. Each **FAIL** comes with a suggested fix.

4. Test the display (six colour bars):

```bash
venv/bin/python src/test_display.py
```

5. Make the first picture now instead of waiting for the timer:

```bash
sudo systemctl start paperpi.service
```

```bash
journalctl -fu paperpi.service
```

## Daily use

* A new picture is made on the schedule in `config.toml` (default 06:00 every day).
* Buttons on the side of the display:
  * **A**: latest picture
  * **B**: older picture
  * **C**: newer picture
  * **D**: hold for 3 s to shut down safely
* Pictures (and a `.txt` with each prompt) are saved in `images/`.

## Configuration

Edit `config.toml` (created from `config.example.toml`). The main settings:

| Setting | Default | Notes |
| --- | --- | --- |
| `generate.steps` | 3 | SDXL Turbo looks good at 1-4 |
| `generate.ram_mode` | true | Fast. Set false if you run out of memory |
| `generate.keep_images` | 0 | Keep only the newest N images (0 = all) |
| `display.portrait` | false | Portrait images, rotated onto the panel |
| `display.saturation` | 0.5 | Colour saturation used when dithering to the 6 inks |
| `display.delay_seconds` | 120 | Let the Pi cool before refreshing the panel |
| `display.type` | "" | Auto-detect. Set `"spectra73"` if detection fails |
| `schedule.on_calendar` | `*-*-* 06:00:00` | systemd [OnCalendar](https://www.freedesktop.org/software/systemd/man/systemd.time.html#Calendar%20Events) format |

After changing `schedule.on_calendar`, run `scripts/install.sh --services`.

See [Prompt libraries](#prompt-libraries) to change what gets drawn.

## Prompt libraries

A prompt library is a JSON file in `prompts/`. It holds a **list of lists**.
Each picture's prompt is built by picking one random entry from each inner
list and joining them with spaces, in order.

```json
[
    ["single stem rose", "bouquet of tulips"],
    ["as a woodblock print", "as a vintage postcard"]
]
```

That small example can produce "bouquet of tulips as a woodblock print".

Bundled libraries:

| File | Lists | Example prompt |
| --- | --- | --- |
| `prompts/flowers.json` | subject, style | single iris as a vintage postcard |
| `prompts/planets.json` | landscape, sky, detail, style | crystal canyon under two suns a crashed spaceship as a linocut print |

### Switching library

Set `paths.prompts_file` in `config.toml`. The change applies from the next picture:

```toml
[paths]
prompts_file = "prompts/planets.json"
```

To try one library once without changing the config:

```bash
venv/bin/python src/generate_picture.py --prompts prompts/planets.json && venv/bin/python src/display_picture.py
```

### Editing or writing a library

* Add or remove entries in any list. Keep the commas between entries and the quotes around each one.
* Add a whole new list (for example lighting or mood); it becomes another part of every prompt.
* Use `""` entries to make a part optional. In `planets.json`, three of the detail entries are empty, so about a quarter of pictures have no extra detail.
* Keep the total prompt short (under about 60 words). SDXL ignores text past its limit.
* Flat, bold, low-colour styles (prints, posters, flat illustration) look best on the 6-colour panel. Photo-realistic and soft gradient styles dither into noise.
* Check your file before the next scheduled run:

```bash
venv/bin/python -m json.tool prompts/planets.json > /dev/null && echo OK
```

## Manual commands

```bash
venv/bin/python src/generate_picture.py --help
```

```bash
venv/bin/python src/generate_picture.py --prompt "a lighthouse at dusk, woodcut print"
```

```bash
venv/bin/python src/display_picture.py images/output.png
```

```bash
scripts/doctor.sh --generate
```

The last command also makes a quick 1-step test image and reports how long it took.

## Troubleshooting

**`GPIO8 ... currently claimed by spi0 CS0`**: `dtoverlay=spi0-0cs` is missing
from `/boot/firmware/config.txt`. Re-run `scripts/install.sh`, then reboot.

**`No EEPROM detected`**: the board isn't being seen on I2C. Power off and
reseat the display on all 40 pins, and check `sudo raspi-config nonint do_i2c 0`.
If it still fails, set `display.type = "spectra73"` in `config.toml` to skip
detection.

**`inky ... too old`** or **`RPi.GPIO` errors**: an old inky is being used.
Always run scripts with `venv/bin/python`, and run `venv/bin/pip install -U -r requirements.txt`.

**Model errors / `git-lfs pointers`**: the weights didn't fully download.
Re-run `scripts/install.sh` to resume, then `venv/bin/python src/check_model.py`.

**Generation crashes or produces garbage**: rebuild OnnxStream with
`scripts/install.sh --rebuild`. If it's out of memory, set `generate.ram_mode = false`.

**Washed-out or odd colours**: try `display.saturation` between 0.3 and 0.8.
E-paper is also temperature-sensitive, so increase `display.delay_seconds` if
the Pi runs hot.

Logs:

```bash
journalctl -u paperpi.service -n 100
```

```bash
journalctl -u paperpi-buttons.service -n 50
```

## Development

The non-hardware parts have tests (no Pi needed):

```bash
pip install pytest pillow numpy && python -m pytest tests
```

## Planned

* Local LLM prompt generation (llama.cpp): the Pi 5's 16 GB makes this
  practical. Prompts all come from `choose_prompt()` in
  `src/generate_picture.py`, which is where it will plug in.

## Credits

* [dylski/PaperPiAI](https://github.com/dylski/PaperPiAI): the original project
* [vitoplantamura/OnnxStream](https://github.com/vitoplantamura/OnnxStream): Stable Diffusion on the Raspberry Pi
* [pimoroni/inky](https://github.com/pimoroni/inky): display driver
