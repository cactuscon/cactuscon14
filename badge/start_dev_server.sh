#!/usr/bin/env bash

# Development OTA Server Runner for CactusCon Badge
# This script starts the development OTA server that watches src/ for changes

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

HOST="${DEV_SERVER_HOST:-127.0.0.1}"
PORT="${DEV_SERVER_PORT:-8000}"

echo "Starting CactusCon Badge Development OTA Server..."
echo "This will serve files from src/ directory on http://${HOST}:${PORT}/ota/"
echo ""

# Check if we're in the badge directory
if [ ! -d "src" ]; then
    echo "Error: src/ directory not found. Please run this script from the badge directory."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
    echo "Error: Python not found in PATH."
    exit 1
fi

PYTHON_BIN="$(command -v python3 || command -v python)"

if [ ! -f "dev_ota_server.py" ]; then
    echo "Error: dev_ota_server.py not found in ${SCRIPT_DIR}"
    exit 1
fi

# Start the development server
"${PYTHON_BIN}" dev_ota_server.py --src-dir src --host "${HOST}" --port "${PORT}"

echo "Server stopped."
