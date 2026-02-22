# ESP32-S3 Flashing Guide

This directory contains multiple options for flashing ESP32-S3 devices with MicroPython firmware.

For development environment setup, first hardware-program tutorial (NeoPixel),
and community links from CactusCon attendees, see `README.md` in this directory.

## Quick Start

### For 8MB ESP32-S3 (Recommended)
Use the separate binary files approach:

**Windows:**
```cmd
set PORT=COM5 && flash_esp32s3.bat
```

**Linux/macOS:**
```bash
PORT=/dev/ttyUSB0 ./flash_esp32s3.sh
```

### For Generic ESP32-S3
Use the combined firmware approach:

**Windows:**
```cmd
set PORT=COM5 && flash_bin.bat
```

**Linux/macOS:**
```bash
PORT=/dev/ttyUSB0 ./flash_bin.sh
```

Note: the flashing scripts can attempt auto-detection, but for safety you should
explicitly set `PORT` so you always flash the intended device.

## Manual Commands

### 8MB ESP32-S3 with Separate Binaries
```bash
# Erase flash
python3 -m esptool --chip esp32s3 --port COM3 erase_flash

# Flash binaries
python3 -m esptool --chip esp32s3 \
    --port COM3 \
    --baud 460800 \
    write_flash \
    --flash_mode dio \
    --flash_freq 80m \
    --flash_size 8MB \
    0x0 lvgl_micropy_ESP32_GENERIC_S3-8MB.bin
```

### Generic ESP32-S3 with Combined Firmware
```bash
python3 -m esptool --port COM3 write_flash 0 ESP32_GENERIC_S3-20241129-v1.24.1.bin
```

## flash_args.txt (CI-Generated Layout)

Some release bundles include a `flash_args.txt` file that lists the offsets and
binary filenames to flash. When present, `flash_esp32s3.*` reads it and flashes
exactly what it specifies.

If you use `flash_args.txt`, you still should set `PORT` explicitly:

```bash
PORT=/dev/ttyUSB0 ./flash_esp32s3.sh
```

## Binary Files

| File | Address | Purpose |
|------|---------|---------|
| `lvgl_micropy_ESP32_GENERIC_S3-8MB.bin` | 0x0 | LVGL MicroPython firmware for ESP32-S3 8MB layouts |
| `ESP32_GENERIC_S3-20241129-v1.24.1.bin` | 0x0 | Combined firmware (all-in-one), used by `flash_bin.*` |

## Troubleshooting

### Port Detection Issues
- **Windows**: Ports are usually `COM3`, `COM4`, etc.
- **Linux**: Ports are usually `/dev/ttyUSB0`, `/dev/ttyACM0`
- **macOS**: Ports are usually `/dev/cu.usbserial-*`

Set the port manually:
```bash
# Windows
set PORT=COM3 && flash_esp32s3.bat

# Linux/macOS
PORT=/dev/ttyUSB0 ./flash_esp32s3.sh
```

### Skipping Erase

The scripts erase flash by default. If you need to preserve parts of flash or
are iterating rapidly, you can skip erase:

- Linux/macOS: `ERASE_FIRST=0 PORT=/dev/ttyUSB0 ./flash_esp32s3.sh`
- Windows: `set ERASE_FIRST=0` before running the script

### Flash Size Mismatch
If you get flash size errors, your chip might not be 8MB. Try:
1. Use the generic firmware: `flash_bin.bat` or `flash_bin.sh`
2. Check your chip specifications
3. Try different flash size settings (4MB, 16MB)

### Permission Errors (Linux/macOS)
Add your user to the dialout group:
```bash
sudo usermod -a -G dialout $USER
```
Then log out and back in.

### Install esptool
If esptool is not installed:
```bash
python3 -m pip install esptool

# OR

pipx install esptool
```

## After Flashing

1. **Reset** the ESP32-S3 device
2. **Connect** via serial terminal at 115200 baud
3. **Test** Python REPL: You should see `>>>`
4. **Upload** your project files using tools like `mpremote`, `ampy`, or Thonny
