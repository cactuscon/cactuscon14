"""Key and blob behavior tests for Preferences helpers."""

from cactuscon.prefs import Preferences, make_key


def test_make_key_is_deterministic_and_bounded():
    key1 = make_key("verylongprefix", "verylongnamepart", max_len=15)
    key2 = make_key("verylongprefix", "verylongnamepart", max_len=15)

    assert key1 == key2
    assert len(key1) <= 15


def test_set_and_get_blob_with_len_roundtrip():
    prefs = Preferences()
    blob_key = "tb_blob_a"
    len_key = "tb_len_a"
    payload = b"\x01\x02\x03\x04"

    assert prefs.set_blob_with_len(blob_key, len_key, payload) is True
    assert prefs.get_blob_with_len(blob_key, len_key, default=b"") == payload


def test_get_blob_with_len_returns_actual_when_length_mismatch():
    prefs = Preferences()
    blob_key = "tb_blob_b"
    len_key = "tb_len_b"
    payload = b"\xAA\xBB\xCC"

    assert prefs.set_blob(blob_key, payload) is True
    assert prefs.set_int32(len_key, 8) is True
    assert prefs.get_blob_with_len(blob_key, len_key, default=b"") == payload


def test_get_blob_with_len_uses_default_when_length_missing_or_zero():
    prefs = Preferences()
    blob_key = "tb_blob_c"
    len_key = "tb_len_c"

    assert prefs.set_blob(blob_key, b"\xFF") is True
    assert prefs.get_blob_with_len(blob_key, len_key, default=b"default") == b"default"

    assert prefs.set_int32(len_key, 0) is True
    assert prefs.get_blob_with_len(blob_key, len_key, default=b"default") == b"default"
