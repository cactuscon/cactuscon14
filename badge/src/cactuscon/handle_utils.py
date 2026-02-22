"""Shared helpers for player handle validation."""

import re

HANDLE_MIN_LEN = 3
# BLE scan response allows 31 bytes; reserve some for header/UI space.
HANDLE_MAX_LEN = 18
HANDLE_PATTERN = re.compile(r"^[a-zA-Z0-9]+[-_\sa-zA-Z0-9]*[a-zA-Z0-9]+$")


def normalize_handle(value):
    """Return a stripped string representation of a handle."""
    if value is None:
        return ""
    try:
        # Accept bytes or objects that can render to str
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        else:
            value = str(value)
    except Exception:
        return ""
    return value.strip()


def validate_handle(value):
    """
    Validate a handle string against length and character constraints.

    Returns:
        tuple: (is_valid: bool, normalized: str, error: str)
    """
    handle = normalize_handle(value)
    if not handle:
        return False, handle, "Please enter a handle"

    length = len(handle)
    if length < HANDLE_MIN_LEN:
        return False, handle, "Handle must be %d+ characters" % HANDLE_MIN_LEN
    if length > HANDLE_MAX_LEN:
        return False, handle, "Handle must be %d or fewer chars" % HANDLE_MAX_LEN

    if not HANDLE_PATTERN.match(handle):
        return False, handle, "Letters/numbers only; '-', '_', spaces in middle"

    return True, handle, ""
