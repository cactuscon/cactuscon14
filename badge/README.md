# Badge Firmware Guide

This directory contains the firmware code, OTA tooling, and local utility scripts used for the CactusCon 14 badge.

Thanks for participating in CactusCon 14 with us!

## Community Projects and Write-Ups

- @puzzlepeaches: [cactusflash](https://github.com/puzzlepeaches/cactusflash)
- @jordanlanham52: [CC14 Badge Write-Up](https://github.com/jordanlanham52/CactusCon-14-Badge-Writeup-Walkthrough) [CC14 Badge Manager](https://github.com/jordanlanham52/CactusCon-14-Badge-Manager)

## Directory Layout

```
badge/
├── src/
│   ├── boot.py                  # OTA/bootstrap entry point
│   ├── main.py                  # Runtime app entry point
│   ├── config.py                # Badge configuration defaults
│   ├── cactuscon/               # Badge runtime modules (UI, game, hardware)
│   ├── cactiotpad/              # Submodule: API/chat client library
│   ├── saguarota/               # Submodule: OTA client library
│   └── thirdparty/              # Third-party drivers/helpers
├── bins/                        # Firmware images and flash argument files
├── flash_*.sh / flash_*.bat     # Flash utility scripts
├── start_dev_server.*           # Local OTA dev-server launchers
├── dev_ota_server.py            # Dev OTA file server
└── tests/                       # Desktop unit tests for badge code
```

## Submodules and Third-Party

- `src/cactiotpad/` is maintained as a submodule.
- `src/saguarota/` is maintained as a submodule.
- `src/thirdparty/` contains vendor/library code used by badge runtime.

Initialize/update submodules from repo root:

```bash
git submodule update --init --recursive
```

## Development Environment Setup

If you are developing on badge firmware, set up these baseline tools first:

1. Install Python 3.10+.
2. Install `esptool`:
   ```bash
   python3 -m pip install esptool
   ```
3. Install Thonny (recommended for MicroPython REPL and file transfer).
4. Install USB serial drivers for your board/adapter chipset if needed:
   - CP210x (Silicon Labs)
   - CH340/CH34x (WCH)
   - FTDI (FT232 family)
5. Confirm the board appears as a serial device:
   - Windows: `COMx`
   - Linux: `/dev/ttyUSBx` or `/dev/ttyACMx`
   - macOS: `/dev/cu.usbserial-*` or `/dev/cu.usbmodem*`

### Thonny Quick Configuration

1. Open Thonny.
2. Set interpreter to "MicroPython (ESP32)".
3. Select the board serial port explicitly.
4. Open the shell and confirm REPL works (`>>>` prompt).

## Flashing Utilities

Use scripts in this directory:

- `flash_esp32s3.sh` / `flash_esp32s3.bat`:
  - primary flashing scripts
  - support `flash_args.txt` when present
  - can auto-detect a serial port, but for safety you should explicitly set `PORT`
- `flash_bin.sh` / `flash_bin.bat`:
  - flash a single combined binary at `0x0`

Before flashing:

1. Put the board in download mode.
2. Confirm `python` and `esptool` are installed.
3. Set `PORT` to the exact device you intend to flash (recommended).

Examples:

```bash
# Linux
PORT=/dev/ttyUSB0 ./flash_esp32s3.sh

# macOS
PORT=/dev/cu.usbserial-XXXX ./flash_esp32s3.sh
```

```bat
REM Windows
set PORT=COM5
flash_esp32s3.bat
```

Detailed notes remain in `FLASHING_GUIDE.md`.

## Basic Hardware Smoke Tests (No Badge App Required)

These checks validate basic board operation before loading badge software.

### 1. REPL and runtime sanity

At the MicroPython REPL:

```python
import sys
print(sys.platform)
```

You should see `esp32`.

### 2. NeoPixel LED tutorial (first hardware program)

This is the quickest "hello hardware" test for the badge. It verifies that:

1. the board is running your MicroPython code,
2. the NeoPixel data pin works,
3. all six LEDs can be addressed.

At the REPL (default badge mapping: GPIO18, 6 LEDs), paste:

```python
from machine import Pin
import neopixel, time

np = neopixel.NeoPixel(Pin(18), 6)
for color in ((32,0,0), (0,32,0), (0,0,32), (0,0,0)):
    for i in range(6):
        np[i] = color
    np.write()
    time.sleep(0.4)
```

You should see all LEDs cycle red, green, blue, then off. If this runs, your
board/driver path is good and you can move on to full badge firmware workflows.

### 3. Optional basic reset check

```python
import machine
machine.reset()
```

If the device reconnects and returns to REPL, boot/reset behavior is functioning.

## Development OTA Server

Local OTA workflow is driven by:

- `dev_ota_server.py`
- `start_dev_server.sh` / `start_dev_server.bat`

Defaults:

- host: `127.0.0.1`
- port: `8000`
- source directory: `src/`

Override with environment variables:

- `DEV_SERVER_HOST`
- `DEV_SERVER_PORT`

Detailed notes remain in `DEV_SERVER_README.md`.

## CI/CD Workflows (Manual Dispatch)

Firmware and infrastructure pipelines are defined in:

- [`.github/workflows/badge-ci.yml`](../.github/workflows/badge-ci.yml)
- [`.github/workflows/terraform.yml`](../.github/workflows/terraform.yml)

These workflows are set to **manual run only** via `workflow_dispatch`.

Run them from GitHub: **Actions tab** -> select workflow -> **Run workflow**.

### Badge Firmware Pipeline Overview

`badge-ci.yml` is organized as a staged pipeline:

1. `build-manifest`: assembles OTA payload files and generates `versions.json`.
2. `select-flash-sizes`: chooses matrix targets (main branch: `8,16`; non-main: `8`).
3. `build-image`: builds standard firmware + VFS images and uploads artifacts.
4. `build-station-image`: builds STATION firmware variants and uploads artifacts.
5. `deploy` (optional): publishes OTA files/firmware to OTA host when `publish_outputs=true` on `main`.
6. `release` (optional): creates/updates GitHub Release assets when `publish_outputs=true` on `main`.

### Terraform Pipeline Overview

`terraform.yml` runs `init`, `fmt`, and `plan` on manual invocation.

`terraform apply` is opt-in and only runs when:

- branch is `main`, and
- workflow input `apply_changes=true`.

### Reuse Notes

Both workflow files include inline comments and explicit step names describing:

- why each job exists,
- what each major step is preparing/building, and
- which steps are intentionally gated for safe reuse.

## Testing

Run badge tests from this directory:

```bash
PYTHONPATH=src pytest -q tests
```
