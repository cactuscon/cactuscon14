"""
Test reversibility of the XOR helper _loop_swoop_pull.

Ensures:
- Applying the function twice with the same key restores original bytes.
- Empty key is a no-op.
"""

from cactuscon.prefs import _loop_swoop_pull

def _assert_roundtrip(data: bytes, key: bytes):
    encoded = _loop_swoop_pull(data, key)
    decoded = _loop_swoop_pull(encoded, key)
    assert decoded == data, f"Round-trip failed for key={key!r}"
    return encoded, decoded


def test_roundtrip_basic():
    data = b"CactusConBadge!"
    key = b"secretkey"
    encoded, decoded = _assert_roundtrip(data, key)
    # Ensure it actually changed the bytes (not identity)
    assert encoded != data, "Encoding should alter data when key is non-empty"


def test_roundtrip_long_data_short_key():
    data = bytes(range(256))
    key = b"k"
    _assert_roundtrip(data, key)


def test_noop_when_key_empty():
    data = b"unchanged"
    key = b""
    encoded = _loop_swoop_pull(data, key)
    assert encoded == data, "Empty key must not alter data"
    decoded = _loop_swoop_pull(encoded, key)
    assert decoded == data, "Round-trip with empty key should remain unchanged"
