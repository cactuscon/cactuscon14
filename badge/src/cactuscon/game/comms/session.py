"""BattleSession class for tracking active badge battles.

This module contains the BattleSession class which represents the state
of an active battle between two badges.
"""

import time
import ubinascii

from cactuscon.game.comms.protocol import (
    PROTOCOL_VERSION,
    SESSION_IDLE,
    TURN_SELECTING,
)


class BattleSession:
    """
    Represents an active battle session between two badges.

    Tracks session state, timing, and exchanged data for one battle.
    Includes session token for message authentication.
    """

    __slots__ = (
        "session_id",
        "opponent_addr",
        "opponent_name",
        "state",
        "started_at",
        "last_activity",
        "is_challenger",
        "protocol_version",
        "session_token",
        "battle_data",
        "turn_number",
        "turn_state",
        "our_move",
        "opponent_move",
        "our_consensus_hash",
        "their_consensus_hash",
        "our_player_data",
        "opponent_player_data",
        "our_data_sent",
        "opponent_data_received",
        "turn_move_sent",
        "turn_move_acked",
        "last_turn_ready_ts",
        "ready_sent",
        "ready_received",
        "disconnect_grace_until",
        "consensus_turn",
        "last_consensus_send_ts",
        "consensus_send_attempts",
    )

    def __init__(self, session_id, opponent_addr, is_challenger=True):
        """
        Initialize a battle session.

        Args:
            session_id: Unique session identifier (bytes)
            opponent_addr: Opponent's BLE MAC address (bytes)
            is_challenger: True if we initiated the challenge
        """
        self.session_id = session_id
        self.opponent_addr = opponent_addr
        self.opponent_name = "Unknown"
        self.state = SESSION_IDLE
        self.started_at = time.ticks_ms()
        self.last_activity = self.started_at
        self.is_challenger = is_challenger
        self.protocol_version = PROTOCOL_VERSION
        self.session_token = None  # Set during handshake
        self.battle_data = {}  # Game-specific battle state

        # Turn-based battle state
        self.turn_number = 0
        self.turn_state = TURN_SELECTING
        self.our_move = None  # (move_id, move_data) when we've selected
        self.opponent_move = None  # (move_id, move_data) when opponent has selected
        self.last_turn_ready_ts = 0  # ticks_ms when we last sent TURN_READY

        # Consensus tracking - hashes for turn verification
        self.our_consensus_hash = None
        self.their_consensus_hash = None

        # Player data exchange (after handshake, before battle)
        # Dict of field_id -> value for our data to send
        self.our_player_data = {}
        # Dict of field_id -> value for received opponent data
        self.opponent_player_data = {}
        # Exchange completion flags
        self.our_data_sent = False
        self.opponent_data_received = False

        # Turn synchronization flags
        self.turn_move_sent = False
        self.turn_move_acked = False
        # UI readiness handshake flags
        self.ready_sent = False
        self.ready_received = False
        self.disconnect_grace_until = 0  # ticks_ms when grace expires
        # Consensus resend tracking (in case hash is lost)
        self.consensus_turn = None
        self.last_consensus_send_ts = 0
        self.consensus_send_attempts = 0

    def update_activity(self):
        """
        Update last activity timestamp (call on any message).

        Returns:
            None
        """
        self.last_activity = time.ticks_ms()

    def age_ms(self):
        """
        Return milliseconds since last activity.

        Returns:
            int: Milliseconds since last activity.
        """
        return time.ticks_diff(time.ticks_ms(), self.last_activity)

    def duration_ms(self):
        """
        Return total session duration in milliseconds.

        Returns:
            int: Total session duration in milliseconds.
        """
        return time.ticks_diff(time.ticks_ms(), self.started_at)

    def is_expired(self, timeout_ms):
        """
        Check if session has exceeded inactivity timeout.

        Args:
            timeout_ms (int): Timeout in milliseconds.

        Returns:
            bool: True if expired, False otherwise.
        """
        return self.age_ms() > timeout_ms

    def __repr__(self):
        """
        Return string representation of the BattleSession.

        Returns:
            str: String representation.
        """
        return f"<BattleSession {ubinascii.hexlify(self.session_id).decode()} state={self.state}>"
