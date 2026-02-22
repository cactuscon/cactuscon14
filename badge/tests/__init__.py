"""
CactusCon Badge Test Suite

This directory contains unit tests for core badge functionality.
Tests are designed to run on desktop Python to verify logic before
deploying to hardware.

Run all tests:
    python3 -m pytest tests/

Run specific test:
    python3 -m tests.test_uuid_conversion
"""

import sys
import os

# Automatically add parent directory to path for all tests
# This allows tests to import from src/ without boilerplate in each test file
_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Also add src/ so tests can import cactuscon.* modules
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
if os.path.isdir(_SRC_DIR) and _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
