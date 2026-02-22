"""Behavior tests for GameBT protocol guardrails and malformed payload handling."""

import types

from cactuscon.game.comms.game_bt import GameBTComms
from cactuscon.game.comms.protocol import (
    MAX_MESSAGE_SIZE,
    MSG_PLAYER_DATA,
    PLAYER_DATA_BADGE_ID,
    PLAYER_DATA_CARE_ACTIVITY,
    PLAYER_DATA_CHARACTER_ID,
    PLAYER_DATA_LEVEL,
    PLAYER_DATA_NAME,
    PLAYER_DATA_POWERS,
    PLAYER_DATA_WINS,
    SESSION_EXCHANGING_DATA,
)

def test_gamebt_send_player_data_enforces_protocol_limits(dummy_logger):
    sent_payloads = []
    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    comms.player_data_provider = None
    original_send_message = GameBTComms._send_message
    original_check_complete = GameBTComms._check_data_exchange_complete
    GameBTComms._send_message = lambda self, payload: sent_payloads.append(payload) or True
    GameBTComms._check_data_exchange_complete = lambda self: None
    comms.session = types.SimpleNamespace(
        our_player_data={
            PLAYER_DATA_CHARACTER_ID: 0,
            PLAYER_DATA_LEVEL: 9999999,
            PLAYER_DATA_WINS: 10**12,
            PLAYER_DATA_NAME: "X" * 300,
            PLAYER_DATA_BADGE_ID: b"\xAA" * 600,
            PLAYER_DATA_POWERS: "p" * 400,
        },
        our_data_sent=False,
    )

    try:
        comms._send_player_data()
    finally:
        GameBTComms._send_message = original_send_message
        GameBTComms._check_data_exchange_complete = original_check_complete

    assert comms.session.our_data_sent is True
    assert len(sent_payloads) == 1
    payload = sent_payloads[0]
    assert payload[0] == MSG_PLAYER_DATA
    assert len(payload) <= (MAX_MESSAGE_SIZE - 16)

    parsed = {}
    offset = 2
    for _ in range(payload[1]):
        field_id = payload[offset]
        field_len = payload[offset + 1]
        parsed[field_id] = payload[offset + 2 : offset + 2 + field_len]
        offset += 2 + field_len

    assert len(parsed[PLAYER_DATA_NAME]) <= 32
    assert len(parsed[PLAYER_DATA_BADGE_ID]) <= 255
    wins_raw = parsed[PLAYER_DATA_WINS]
    assert len(wins_raw) == 2
    assert int.from_bytes(wins_raw, "little") == 0xFFFF


def test_gamebt_handle_player_data_tolerates_malformed_fields_without_crash(dummy_logger):
    end_state = {"ended": False, "checked": False}
    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    original_send_error = GameBTComms._send_error
    original_handle_error = GameBTComms._handle_error
    original_end_session = GameBTComms.end_session
    original_check_complete = GameBTComms._check_data_exchange_complete
    GameBTComms._send_error = lambda self, *_args, **_kwargs: None
    GameBTComms._handle_error = lambda self, *_args, **_kwargs: None
    GameBTComms.end_session = lambda self: end_state.__setitem__("ended", True)
    GameBTComms._check_data_exchange_complete = lambda self: end_state.__setitem__(
        "checked", True
    )
    comms.session = types.SimpleNamespace(
        state=SESSION_EXCHANGING_DATA,
        opponent_player_data={},
        opponent_data_received=False,
    )

    packet = bytes(
        [
            MSG_PLAYER_DATA,
            3,
            PLAYER_DATA_CHARACTER_ID,
            1,
            0,
            PLAYER_DATA_WINS,
            0,
            PLAYER_DATA_NAME,
            3,
            0xFF,
            0xFE,
            0xFD,
        ]
    )
    try:
        comms._handle_player_data(packet)
    finally:
        GameBTComms._send_error = original_send_error
        GameBTComms._handle_error = original_handle_error
        GameBTComms.end_session = original_end_session
        GameBTComms._check_data_exchange_complete = original_check_complete

    assert end_state["ended"] is False
    assert end_state["checked"] is True
    assert comms.session.opponent_data_received is True
    assert comms.session.opponent_player_data[PLAYER_DATA_CHARACTER_ID] == 0
    assert PLAYER_DATA_WINS not in comms.session.opponent_player_data


def test_gamebt_handle_player_data_rejects_duplicate_care_fields(dummy_logger):
    end_state = {"ended": False}
    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    original_send_error = GameBTComms._send_error
    original_handle_error = GameBTComms._handle_error
    original_end_session = GameBTComms.end_session
    original_check_complete = GameBTComms._check_data_exchange_complete
    GameBTComms._send_error = lambda self, *_args, **_kwargs: None
    GameBTComms._handle_error = lambda self, *_args, **_kwargs: None
    GameBTComms.end_session = lambda self: end_state.__setitem__("ended", True)
    GameBTComms._check_data_exchange_complete = lambda self: None
    comms.session = types.SimpleNamespace(
        state=SESSION_EXCHANGING_DATA,
        opponent_player_data={},
        opponent_data_received=False,
    )

    packet = bytes(
        [
            MSG_PLAYER_DATA,
            3,
            PLAYER_DATA_CHARACTER_ID,
            1,
            0,
            PLAYER_DATA_CARE_ACTIVITY,
            5,
            ord("b"),
            ord("a"),
            ord("t"),
            ord("h"),
            ord("e"),
            PLAYER_DATA_CARE_ACTIVITY,
            5,
            ord("t"),
            ord("r"),
            ord("e"),
            ord("a"),
            ord("t"),
        ]
    )
    try:
        comms._handle_player_data(packet)
    finally:
        GameBTComms._send_error = original_send_error
        GameBTComms._handle_error = original_handle_error
        GameBTComms.end_session = original_end_session
        GameBTComms._check_data_exchange_complete = original_check_complete

    assert end_state["ended"] is True


def test_gamebt_send_message_stops_oversized_packets_before_ble_write(dummy_logger):
    writes = []

    class DummyBT:
        char_handle = 1

        def is_connected(self):
            return True

        def write_data(self, payload, wait_for_response=False):
            writes.append((payload, wait_for_response))
            return True

    comms = GameBTComms.__new__(GameBTComms)
    comms.logger = dummy_logger
    comms.bt = DummyBT()
    comms.server_mode = False
    comms.server_conn_handle = None
    comms.session = None

    too_large = b"x" * (MAX_MESSAGE_SIZE - 15)
    assert comms._send_message(too_large) is False
    assert writes == []

    boundary = b"y" * (MAX_MESSAGE_SIZE - 16)
    assert comms._send_message(boundary) is True
    assert writes and writes[-1][0] == boundary
