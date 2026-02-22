"""Tests for production UUID conversion in BluetoothManager."""

import pytest

class MockUUID:
    def __init__(self, uuid_str):
        self._uuid = uuid_str

    def __str__(self):
        # Simulate MicroPython bluetooth.UUID string format.
        return f"UUID('{self._uuid}')"

from cactuscon.hw.bluetooth import BluetoothManager


def test_16bit_uuid():
    """Converts 16-bit UUIDs to little-endian bytes."""
    uuid = MockUUID("0x1801")
    result = BluetoothManager.uuid_to_bytes(uuid)

    assert result == b"\x01\x18"


def test_128bit_uuid():
    """Converts 128-bit UUIDs to BLE byte order."""
    uuid = MockUUID("cc140001-c0de-4bad-9e14-cac71b072026")
    result = BluetoothManager.uuid_to_bytes(uuid)
    expected_hex = "cc140001c0de4bad9e14cac71b072026"
    assert result == bytes(reversed(bytes.fromhex(expected_hex)))


def test_uppercase_uuid():
    """Accepts uppercase hex UUID strings."""
    upper_uuid = MockUUID("CC140001-C0DE-4BAD-9E14-CAC71B072026")
    lower_uuid = MockUUID("cc140001-c0de-4bad-9e14-cac71b072026")
    upper_result = BluetoothManager.uuid_to_bytes(upper_uuid)
    lower_result = BluetoothManager.uuid_to_bytes(lower_uuid)

    expected_hex = "cc140001c0de4bad9e14cac71b072026"
    expected_bytes = bytes(reversed(bytes.fromhex(expected_hex)))

    assert upper_result == lower_result
    assert upper_result == expected_bytes


def test_invalid_uuid():
    """Rejects malformed UUID strings."""
    uuid = MockUUID("invalid-uuid")
    with pytest.raises(ValueError):
        BluetoothManager.uuid_to_bytes(uuid)
