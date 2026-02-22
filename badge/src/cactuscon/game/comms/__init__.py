"""Game Bluetooth communications package for badge battles.

This package provides the Bluetooth Low Energy protocol layer for
badge-to-badge battles. Split from the original monolithic comms.py
for maintainability.

Modules:
    protocol: Constants, message types, packet format definitions
    session: BattleSession class for tracking active battles
    game_bt: GameBTComms class for protocol implementation

Public API:
    - GameBTComms: Main protocol class for battle communications
    - BattleSession: Session state container
    - Protocol constants (MSG_*, SESSION_*, etc.)
"""

# Re-export public API for backwards compatibility
# Users can still do: from cactuscon.game.comms import GameBTComms, BattleSession

from cactuscon.game.comms.protocol import (
    # UUIDs
    GAME_SERVICE_UUID_TEMPLATE,
    GAME_CHAR_UUID,
    # Protocol version
    PROTOCOL_VERSION,
    # Message types
    MSG_CHALLENGE_REQUEST,
    MSG_CHALLENGE_ACCEPT,
    MSG_CHALLENGE_DECLINE,
    MSG_HANDSHAKE,
    MSG_HANDSHAKE_ACK,
    MSG_PLAYER_DATA,
    MSG_PLAYER_DATA_ACK,
    MSG_BATTLE_MOVE,
    MSG_BATTLE_STATUS,
    MSG_BATTLE_RESULT,
    MSG_BATTLE_FORFEIT,
    MSG_TURN_READY,
    MSG_TURN_RESOLVE,
    MSG_TURN_CONSENSUS,
    MSG_CONSENSUS_ACK,
    MSG_CONSENSUS_FAIL,
    MSG_TURN_ACK,
    MSG_BATTLE_READY,
    MSG_KEEPALIVE,
    MSG_ERROR,
    # Player data field IDs
    PLAYER_DATA_CHARACTER_ID,
    PLAYER_DATA_LEVEL,
    PLAYER_DATA_NAME,
    PLAYER_DATA_BADGE_ID,
    PLAYER_DATA_WINS,
    PLAYER_DATA_LOSSES,
    PLAYER_DATA_CARE_ACTIVITY,
    PLAYER_DATA_CARE_FOOD,
    PLAYER_DATA_POWERS,
    PLAYER_DATA_IS_STATION,
    # Character mappings
    CHARACTER_TO_ID,
    ID_TO_CHARACTER,
    # Session states
    SESSION_IDLE,
    SESSION_CHALLENGING,
    SESSION_CHALLENGED,
    SESSION_HANDSHAKING,
    SESSION_EXCHANGING_DATA,
    SESSION_BATTLING,
    SESSION_COMPLETE,
    SESSION_ERROR,
    # Turn states
    TURN_SELECTING,
    TURN_WAITING,
    TURN_RESOLVING,
    # Timeouts
    CHALLENGE_TIMEOUT_MS,
    HANDSHAKE_TIMEOUT_MS,
    BATTLE_INACTIVITY_TIMEOUT_MS,
    MOVE_TIMEOUT_MS,
    READY_GRACE_TIMEOUT_MS,
    KEEPALIVE_INTERVAL_MS,
    CONSENSUS_RESEND_INTERVAL_MS,
    CONSENSUS_MAX_SENDS,
    CONSENSUS_TIMEOUT_MS,
    MAX_MESSAGE_SIZE,
)

from cactuscon.game.comms.session import BattleSession
from cactuscon.game.comms.game_bt import GameBTComms
from cactuscon.hw.bluetooth import (
    AVAILABILITY_IDLE,
    AVAILABILITY_OPEN,
    AVAILABILITY_IN_BATTLE,
)

# Also export module-level GAME_SERVICE_UUID (set at runtime)
GAME_SERVICE_UUID = None

__all__ = [
    # Classes
    'GameBTComms',
    'BattleSession',
    # UUIDs
    'GAME_SERVICE_UUID_TEMPLATE',
    'GAME_CHAR_UUID',
    'GAME_SERVICE_UUID',
    # Protocol constants
    'PROTOCOL_VERSION',
    # Message types
    'MSG_CHALLENGE_REQUEST',
    'MSG_CHALLENGE_ACCEPT',
    'MSG_CHALLENGE_DECLINE',
    'MSG_HANDSHAKE',
    'MSG_HANDSHAKE_ACK',
    'MSG_PLAYER_DATA',
    'MSG_PLAYER_DATA_ACK',
    'MSG_BATTLE_MOVE',
    'MSG_BATTLE_STATUS',
    'MSG_BATTLE_RESULT',
    'MSG_BATTLE_FORFEIT',
    'MSG_TURN_READY',
    'MSG_TURN_RESOLVE',
    'MSG_TURN_CONSENSUS',
    'MSG_CONSENSUS_ACK',
    'MSG_CONSENSUS_FAIL',
    'MSG_TURN_ACK',
    'MSG_BATTLE_READY',
    'MSG_KEEPALIVE',
    'MSG_ERROR',
    # Player data fields
    'PLAYER_DATA_CHARACTER_ID',
    'PLAYER_DATA_LEVEL',
    'PLAYER_DATA_NAME',
    'PLAYER_DATA_BADGE_ID',
    'PLAYER_DATA_WINS',
    'PLAYER_DATA_LOSSES',
    'PLAYER_DATA_CARE_ACTIVITY',
    'PLAYER_DATA_CARE_FOOD',
    'PLAYER_DATA_POWERS',
    'PLAYER_DATA_IS_STATION',
    # Availability states
    'AVAILABILITY_IDLE',
    'AVAILABILITY_OPEN',
    'AVAILABILITY_IN_BATTLE',
    # Character mappings
    'CHARACTER_TO_ID',
    'ID_TO_CHARACTER',
    # Session states
    'SESSION_IDLE',
    'SESSION_CHALLENGING',
    'SESSION_CHALLENGED',
    'SESSION_HANDSHAKING',
    'SESSION_EXCHANGING_DATA',
    'SESSION_BATTLING',
    'SESSION_COMPLETE',
    'SESSION_ERROR',
    # Turn states
    'TURN_SELECTING',
    'TURN_WAITING',
    'TURN_RESOLVING',
    # Timeouts
    'CHALLENGE_TIMEOUT_MS',
    'HANDSHAKE_TIMEOUT_MS',
    'BATTLE_INACTIVITY_TIMEOUT_MS',
    'MOVE_TIMEOUT_MS',
    'READY_GRACE_TIMEOUT_MS',
    'KEEPALIVE_INTERVAL_MS',
    'CONSENSUS_RESEND_INTERVAL_MS',
    'CONSENSUS_MAX_SENDS',
    'CONSENSUS_TIMEOUT_MS',
    'MAX_MESSAGE_SIZE',
]
