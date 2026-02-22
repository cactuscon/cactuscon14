#!/usr/bin/env bash
# Flash a combined ESP32-S3 firmware binary at 0x0.
# For split image layouts, use flash_esp32s3.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

BIN_NAME="ESP32_GENERIC_S3-20241129-v1.24.1.bin"

if [[ ! -f "${BIN_NAME}" ]]; then
    echo "Error: ${BIN_NAME} not found in ${SCRIPT_DIR}"
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: Python not found in PATH"
    exit 1
fi

if ! "${PYTHON_BIN}" -m esptool version >/dev/null 2>&1; then
    echo "Error: esptool is required. Install with: ${PYTHON_BIN} -m pip install esptool"
    exit 1
fi

if [[ -z "${PORT:-}" ]]; then
    for candidate in /dev/ttyUSB0 /dev/ttyACM0 /dev/cu.usbserial-* /dev/cu.usbmodem*; do
        if compgen -G "${candidate}" >/dev/null 2>&1 || [[ -e "${candidate}" ]]; then
            PORT="${candidate}"
            break
        fi
    done
fi

if [[ -z "${PORT:-}" ]]; then
    echo "Error: could not auto-detect serial port."
    echo "Set PORT manually, e.g.: PORT=/dev/ttyUSB0 ./flash_bin.sh"
    exit 1
fi

echo "Flashing combined ESP32-S3 firmware"
echo "  binary: ${BIN_NAME}"
echo "  port:   ${PORT}"
echo

"${PYTHON_BIN}" -m esptool --chip esp32s3 --port "${PORT}" --baud 460800 write_flash 0x0 "${BIN_NAME}"

echo
echo "Flash complete."
echo "If this image does not match your board layout, use ./flash_esp32s3.sh."
