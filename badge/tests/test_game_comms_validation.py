"""Behavior tests for GameBTComms message and input validation helpers."""

from cactuscon.game import comms as comms_mod


def test_ble_message_validation_and_sanitization_helpers(dummy_logger):
    """Validate protocol length checks, name cleanup, and character-id bounds."""
    comms = comms_mod.GameBTComms.__new__(comms_mod.GameBTComms)
    comms.logger = dummy_logger

    short_turn_ready = bytes([comms_mod.MSG_TURN_READY, 0x01, 0x00, 0x02])
    valid_turn_ready = bytes([comms_mod.MSG_TURN_READY, 0x01, 0x00, 0x02, 0x00])
    assert not comms._validate_message_length(comms_mod.MSG_TURN_READY, short_turn_ready)
    assert comms._validate_message_length(comms_mod.MSG_TURN_READY, valid_turn_ready)

    dirty = b"Player\x00\x1f\xff\nName"
    sanitized = comms._sanitize_name(dirty, max_len=16)
    assert "\x00" not in sanitized
    assert "\x1f" not in sanitized
    assert len(sanitized) <= 16
    assert sanitized

    assert comms._validate_character_id(0) == comms_mod.ID_TO_CHARACTER.get(0)
    assert comms._validate_character_id(-1) is None
    assert comms._validate_character_id(999) is None
