#!/usr/bin/env python3
"""
Development OTA Server for CactusCon Badge

This server uses saguarota.py3utils to serve OTA endpoints for development:
    - /ota/versions.json - Returns the generated manifest
    - /ota/<file_path>   - Serves files from src/ directory
"""

import argparse
import sys
from pathlib import Path
sys.path.insert(0, str((Path(__file__).parent / "src").resolve()))
from saguarota.saguarota.py3utils import OTAManifestBuilder, OTAManifestServer

def main():
    parser = argparse.ArgumentParser(
        description="Development OTA Server for CactusCon Badge"
    )
    parser.add_argument(
        "--src-dir", default="src", help="Source directory to watch (default: src)"
    )
    parser.add_argument(
        "--host", default="localhost", help="Host to bind to (default: localhost)"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to bind to (default: 8000)"
    )

    args = parser.parse_args()
    script_dir = Path(__file__).parent
    src_dir = (script_dir / args.src_dir).resolve()

    try:
        server = OTAManifestServer(str(src_dir), host=args.host, port=args.port)
        server.start()
    except Exception as e:
        print(f"Error starting OTA server: {e}")
        return 1
    return 0

if __name__ == "__main__":
    exit(main())
