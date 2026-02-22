"""Authentication/signing behavior tests for GameBTComms."""

import hashlib
import types

from cactuscon.game.comms.game_bt import GameBTComms
from cactuscon.game.comms.protocol import MSG_BATTLE_STATUS, MSG_KEEPALIVE


def test_validate_message_accepts_valid_hmac_and_rejects_invalid(dummy_logger):
    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    comms.session = types.SimpleNamespace(session_token=b"0123456789abcdef")

    payload = bytes([MSG_BATTLE_STATUS, 100, 0, 0])
    sig = hashlib.sha1(payload + comms.session.session_token).digest()[:16]
    assert comms._validate_message(payload + sig) is True

    tampered = payload + (b"\x00" * 16)
    assert comms._validate_message(tampered) is False


def test_validate_message_rejects_missing_session_or_too_short(dummy_logger):
    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    comms.session = None
    assert comms._validate_message(b"\x01" * 20) is False

    comms.session = types.SimpleNamespace(session_token=b"tok")
    assert comms._validate_message(b"\x01" * 16) is False


def test_send_message_signs_battle_messages_only(dummy_logger):
    writes = []

    class DummyBT:
        char_handle = 1

        def is_connected(self):
            return True

        def write_data(self, payload, wait_for_response=False):
            writes.append(payload)
            return True

    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    comms.bt = DummyBT()
    comms.server_mode = False
    comms.server_conn_handle = None
    comms.session = types.SimpleNamespace(session_token=b"0123456789abcdef")

    battle_payload = bytes([MSG_BATTLE_STATUS, 50, 0, 0])
    keepalive_payload = bytes([MSG_KEEPALIVE])

    assert comms._send_message(battle_payload) is True
    assert writes[-1] != battle_payload
    assert len(writes[-1]) == len(battle_payload) + 16

    assert comms._send_message(keepalive_payload) is True
    assert writes[-1] == keepalive_payload
