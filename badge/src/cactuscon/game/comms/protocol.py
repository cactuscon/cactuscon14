"""Game Bluetooth protocol constants and message types.

This module defines the BLE protocol for badge-to-badge battle communications.
All badges must use the same protocol version and message format.
"""

import bluetooth
from micropython import const

from cactuscon import config
from cactuscon.game.engine.characters import (
    CHAR_ID_TO_CID,
    CID_TO_CHAR_ID,
)

# =============================================================================
# BLE Service UUIDs
# =============================================================================

_HEX_CHARS = "0123456789ABCDEF"


def _is_hex_chunk(value, expected_len):
    if not isinstance(value, str):
        return False
    if len(value) != expected_len:
        return False
    upper = value.upper()
    for ch in upper:
        if ch not in _HEX_CHARS:
            return False
    return True


def _is_uuid_string(value):
    if not isinstance(value, str):
        return False
    parts = value.split("-")
    if len(parts) != 5:
        return False
    expected = (8, 4, 4, 4, 12)
    for part, size in zip(parts, expected):
        if not _is_hex_chunk(part, size):
            return False
    return True


def _build_uuid_defaults():
    """
    Build service/character UUID values from config with safe fallbacks.
    """
    default_prefix = "CC14"
    default_suffix = "CAC71B072026"

    prefix = getattr(config, "BT_GAME_UUID_PREFIX", default_prefix)
    suffix = getattr(config, "BT_GAME_UUID_SUFFIX", default_suffix)
    if not _is_hex_chunk(prefix, 4):
        prefix = default_prefix
    else:
        prefix = prefix.upper()
    if not _is_hex_chunk(suffix, 12):
        suffix = default_suffix
    else:
        suffix = suffix.upper()

    service_template = "{}0001-0000-0000-0000-{}".format(prefix, suffix)
    char_uuid_str = "{}0002-C0DE-4BAD-9E14-{}".format(prefix, suffix)

    # Optional explicit full-string overrides (validated by bluetooth.UUID parse below).
    service_override = getattr(config, "BT_GAME_SERVICE_UUID_TEMPLATE", None)
    char_override = getattr(config, "BT_GAME_CHAR_UUID", None)
    if isinstance(service_override, str) and service_override and _is_uuid_string(service_override):
        service_template = service_override
    if isinstance(char_override, str) and char_override and _is_uuid_string(char_override):
        char_uuid_str = char_override

    return service_template, char_uuid_str


# Custom BLE UUIDs for game protocol.
# Base service template embeds MAC in middle 12 hex chars at runtime.
GAME_SERVICE_UUID_TEMPLATE, _GAME_CHAR_UUID_STR = _build_uuid_defaults()

# Characteristic UUID: Game command/data channel (shared by all peers).
try:
    GAME_CHAR_UUID = bluetooth.UUID(_GAME_CHAR_UUID_STR)
except Exception:
    GAME_CHAR_UUID = bluetooth.UUID("CC140002-C0DE-4BAD-9E14-CAC71B072026")

# =============================================================================
# Protocol Version
# =============================================================================

# Protocol version (major.minor) - used in handshake for compatibility check
PROTOCOL_VERSION = const(0x0100)  # 1.0

# =============================================================================
# Message Types
# =============================================================================

# Challenge flow
MSG_CHALLENGE_REQUEST = const(0x01)  # "I want to battle!"
MSG_CHALLENGE_ACCEPT = const(0x02)  # "I accept your challenge!"
MSG_CHALLENGE_DECLINE = const(0x03)  # "Not now"

# Handshake flow
MSG_HANDSHAKE = const(0x10)  # Exchange session info
MSG_HANDSHAKE_ACK = const(0x11)  # Handshake confirmed

# Player data exchange
MSG_PLAYER_DATA = const(0x12)  # Player data exchange (after handshake)
MSG_PLAYER_DATA_ACK = const(0x13)  # Player data received acknowledgment

# Battle flow
MSG_BATTLE_MOVE = const(0x20)  # Reserved (legacy)
MSG_BATTLE_STATUS = const(0x21)  # HP, status effects
MSG_BATTLE_RESULT = const(0x22)  # Battle outcome
MSG_BATTLE_FORFEIT = const(0x23)  # Give up

# Turn-based protocol
MSG_TURN_READY = const(0x24)  # "I've selected my move, waiting for you"
MSG_TURN_RESOLVE = const(0x25)  # "Both ready, here's turn resolution"
MSG_TURN_CONSENSUS = const(0x26)  # Outcome hash for consensus verification
MSG_CONSENSUS_ACK = const(0x27)  # Consensus acknowledged
MSG_CONSENSUS_FAIL = const(0x28)  # Consensus failed - void battle
MSG_TURN_ACK = const(0x29)  # Acknowledge receipt of turn move
MSG_BATTLE_READY = const(0x2A)  # UI/asset load ready - gate timers until both set

# Utility messages
MSG_KEEPALIVE = const(0xF0)  # Connection health check
MSG_ERROR = const(0xFF)  # Error notification

# =============================================================================
# Player Data Field IDs
# =============================================================================

# For MSG_PLAYER_DATA packets
# Each field: [field_id: 1 byte][length: 1 byte][data: N bytes]

PLAYER_DATA_CHARACTER_ID = const(0x01)  # Character ID (1 byte)
PLAYER_DATA_LEVEL = const(0x02)  # Character level (1 byte)
PLAYER_DATA_NAME = const(0x03)  # Player display name (string)
PLAYER_DATA_BADGE_ID = const(0x04)  # Badge unique ID (8 bytes)
PLAYER_DATA_WINS = const(0x05)  # Total wins (2 bytes)
PLAYER_DATA_LOSSES = const(0x06)  # Total losses (2 bytes)

# Care modifiers (string IDs, optional)
PLAYER_DATA_CARE_ACTIVITY = const(0x10)  # Active activity effect ID
PLAYER_DATA_CARE_FOOD = const(0x11)  # Active food effect ID
PLAYER_DATA_POWERS = const(0x12)  # CSV of active achievement power IDs

# Station mode flag
PLAYER_DATA_IS_STATION = const(0x20)  # Flag: 1 if opponent is a station, 0 otherwise (1 byte)

# Future extensibility: add more field IDs as needed (0x21-0xFF available)

# =============================================================================
# Character ID Mappings
# =============================================================================

# Character IDs derive from the character registry order to avoid divergent
# hardcoded enums. This ensures both peers share the same numeric mapping as the
# authoritative character list evolves.
CHARACTER_TO_ID = CHAR_ID_TO_CID
ID_TO_CHARACTER = CID_TO_CHAR_ID

# =============================================================================
# Session States
# =============================================================================

SESSION_IDLE = const(0)
SESSION_CHALLENGING = const(1)
SESSION_CHALLENGED = const(2)
SESSION_HANDSHAKING = const(3)
SESSION_EXCHANGING_DATA = const(4)  # New state: exchanging player data
SESSION_BATTLING = const(5)
SESSION_COMPLETE = const(6)
SESSION_ERROR = const(6)

# =============================================================================
# Turn States (within SESSION_BATTLING)
# =============================================================================

TURN_SELECTING = const(0)  # Player selecting move
TURN_WAITING = const(1)  # Waiting for opponent's move selection
TURN_RESOLVING = const(2)  # Both moves selected, resolving turn

# =============================================================================
# Timeouts (milliseconds)
# =============================================================================

CHALLENGE_TIMEOUT_MS = const(10000)  # 10 seconds to respond to challenge
HANDSHAKE_TIMEOUT_MS = const(5000)  # 5 seconds for handshake

# Config-driven timeouts (plain ints to satisfy MicroPython const requirements)
BATTLE_INACTIVITY_TIMEOUT_MS = getattr(config, "BATTLE_INACTIVITY_TIMEOUT_MS", 40000)
MOVE_TIMEOUT_MS = getattr(config, "BATTLE_MOVE_TIMEOUT_MS", 30000)

# Asset loading grace period
READY_GRACE_TIMEOUT_MS = const(12000)  # Grace period during asset load before treating disconnect as fatal

# Keepalive interval
KEEPALIVE_INTERVAL_MS = const(5000)  # Send keepalive every 5 seconds

# Consensus protocol timing
CONSENSUS_RESEND_INTERVAL_MS = const(1500)  # Retry consensus hash every 1.5s
CONSENSUS_MAX_SENDS = const(6)  # Max consensus hash sends before abort
CONSENSUS_TIMEOUT_MS = const(9000)  # Abort if consensus not reached in time

# =============================================================================
# Packet Size Limits
# =============================================================================

# Maximum message size (MTU - overhead)
MAX_MESSAGE_SIZE = const(512)
