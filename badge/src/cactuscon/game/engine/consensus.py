from cactuscon.utils import Logger
from cactuscon import config
logger = Logger(config.LOG_LEVEL)

"""Battle consensus system - Ensures both devices agree on battle outcomes."""

import struct
import uhashlib
from micropython import const

from cactuscon.game.engine.deterministic_random import DeterministicRNG, create_turn_seed


# Consensus result constants
CONSENSUS_PENDING = const(0)    # Waiting for opponent's hash
CONSENSUS_AGREED = const(1)     # Hashes match - proceed
CONSENSUS_FAILED = const(2)     # Hashes differ - void battle


class TurnOutcome:
    """
    Immutable record of a turn's outcome for consensus verification.
    
    Captures all state changes from a turn for hashing. Both devices
    must produce identical TurnOutcome objects for consensus.
    
    Attributes:
        turn_number (int): Turn this outcome applies to.
        player_move_id (int): Player's move used.
        opponent_move_id (int): Opponent's move used.
        player_went_first (bool): Who acted first.
        player_damage_dealt (int): Damage player dealt.
        opponent_damage_dealt (int): Damage opponent dealt.
        player_hp_after (int): Player HP after turn.
        opponent_hp_after (int): Opponent HP after turn.
        player_healed (int): HP player recovered.
        opponent_healed (int): HP opponent recovered.
        player_crit (bool): Player scored critical hit.
        opponent_crit (bool): Opponent scored critical hit.
        player_effects_applied (list): Status effects applied to player.
        opponent_effects_applied (list): Status effects applied to opponent.
        rng_state (bytes): RNG state after all rolls.
    """
    
    __slots__ = ('turn_number', 'player_move_id', 'opponent_move_id',
                 'player_went_first', 'player_damage_dealt', 'opponent_damage_dealt',
                 'player_hp_after', 'opponent_hp_after', 'player_healed', 'opponent_healed',
                 'player_crit', 'opponent_crit', 'player_effects_applied', 
                 'opponent_effects_applied', 'rng_state')
    
    def __init__(self):
        """Initialize empty outcome (populate via record_* methods)."""
        self.turn_number = 0
        self.player_move_id = 0
        self.opponent_move_id = 0
        self.player_went_first = True
        self.player_damage_dealt = 0
        self.opponent_damage_dealt = 0
        self.player_hp_after = 0
        self.opponent_hp_after = 0
        self.player_healed = 0
        self.opponent_healed = 0
        self.player_crit = False
        self.opponent_crit = False
        self.player_effects_applied = []
        self.opponent_effects_applied = []
        self.rng_state = b'\x00\x00\x00\x00'
    
    def compute_hash(self):
        """
        Compute deterministic hash of this outcome.
        
        NOTE: Outcome data is already in CANONICAL form (challenger = "player",
        challenged = "opponent"). No normalization needed here - BattleManager
        ensures both devices record identical values.
        
        Returns:
            bytes: 16-byte hash for consensus comparison.
        """
        # Pack all numeric fields into bytes
        # Data is already canonical: player = challenger, opponent = challenged
        data = struct.pack('<HHHBHHHHHHBB',
                          self.turn_number,
                          self.player_move_id,
                          self.opponent_move_id,
                          1 if self.player_went_first else 0,
                          self.player_damage_dealt,
                          self.opponent_damage_dealt,
                          self.player_hp_after,
                          self.opponent_hp_after,
                          self.player_healed,
                          self.opponent_healed,
                          1 if self.player_crit else 0,
                          1 if self.opponent_crit else 0)
        
        # Add effect lists
        data += struct.pack('<BB', 
                           len(self.player_effects_applied),
                           len(self.opponent_effects_applied))
        
        # Add RNG state
        data += self.rng_state
        
        # Debug: show what we're hashing
        logger.debug(f"[HASH] turn={self.turn_number}, moves=({self.player_move_id},{self.opponent_move_id}), first={self.player_went_first}, dmg=({self.player_damage_dealt},{self.opponent_damage_dealt}), hp=({self.player_hp_after},{self.opponent_hp_after}), rng={self.rng_state.hex()}")
        
        # SHA-1 and truncate to 16 bytes
        return uhashlib.sha1(data).digest()[:16]
    
    def to_dict(self):
        """Convert to dict for debugging/logging."""
        return {
            'turn': self.turn_number,
            'player_move': self.player_move_id,
            'opponent_move': self.opponent_move_id,
            'first': 'player' if self.player_went_first else 'opponent',
            'player_dmg': self.player_damage_dealt,
            'opponent_dmg': self.opponent_damage_dealt,
            'player_hp': self.player_hp_after,
            'opponent_hp': self.opponent_hp_after,
            'player_heal': self.player_healed,
            'opponent_heal': self.opponent_healed,
            'player_crit': self.player_crit,
            'opponent_crit': self.opponent_crit,
        }


class ConsensusTracker:
    """
    Tracks consensus state across a battle.
    
    Manages turn-by-turn consensus verification and detects
    any desync between devices.
    
    Usage:
        tracker = ConsensusTracker(session_token)
        
        # Each turn:
        rng = tracker.begin_turn(turn_num, my_move, their_move)
        # ... execute moves using rng ...
        outcome = TurnOutcome()
        outcome.rng_state = rng.get_state()
        # ... populate outcome ...
        
        my_hash = tracker.compute_turn_hash(outcome)
        send_consensus_hash(my_hash)
        
        # When opponent hash received:
        result = tracker.verify_consensus(their_hash)
        if result == CONSENSUS_AGREED:
            tracker.commit_turn(outcome)
        elif result == CONSENSUS_FAILED:
            void_battle()
    
    Attributes:
        session_token (bytes): Battle session token.
        current_turn (int): Current turn number.
        pending_outcome (TurnOutcome): Outcome awaiting consensus.
        our_hash (bytes): Our computed hash.
        their_hash (bytes): Opponent's hash (when received).
        history (list): Committed turn outcomes.
    """
    
    __slots__ = ('session_token', 'current_turn', 'pending_outcome',
                 'our_hash', 'their_hash', 'history', '_rng')
    
    def __init__(self, session_token):
        """
        Initialize consensus tracker.
        
        Args:
            session_token (bytes): Session token from handshake.
        """
        self.session_token = session_token
        self.current_turn = 0
        self.pending_outcome = None
        self.our_hash = None
        self.their_hash = None
        self.history = []
        self._rng = None
    
    def begin_turn(self, turn_number, player_move_id, opponent_move_id):
        """
        Begin a new turn and create deterministic RNG.
        
        Call this when both moves are known. Returns RNG that
        both devices will use for this turn.
        
        Args:
            turn_number (int): Turn number (must match current_turn).
            player_move_id (int): Our selected move.
            opponent_move_id (int): Opponent's selected move.
            
        Returns:
            DeterministicRNG: Seeded RNG for this turn.
            
        Raises:
            ValueError: If turn_number doesn't match expected.
        """
        if turn_number != self.current_turn:
            raise ValueError(f"Turn mismatch: expected {self.current_turn}, got {turn_number}")
        
        # Create deterministic seed from shared data
        seed = create_turn_seed(self.session_token, turn_number, 
                               player_move_id, opponent_move_id)
        
        token_hex = self.session_token[:8].hex() if self.session_token else "None"
        logger.debug(f"[CONSENSUS] token={token_hex}..., turn={turn_number}, player={player_move_id}, opp={opponent_move_id}, seed={seed.hex()}")
        
        self._rng = DeterministicRNG(seed)
        
        # Initialize pending outcome
        self.pending_outcome = TurnOutcome()
        self.pending_outcome.turn_number = turn_number
        self.pending_outcome.player_move_id = player_move_id
        self.pending_outcome.opponent_move_id = opponent_move_id
        self.our_hash = None
        self.their_hash = None
        
        return self._rng
    
    def get_rng(self):
        """
        Get current turn's RNG.
        
        Returns:
            DeterministicRNG: Current RNG or None if no turn in progress.
        """
        return self._rng
    
    def record_outcome(self, outcome):
        """
        Record the turn outcome and compute our hash.
        
        Args:
            outcome (TurnOutcome): Completed outcome with all fields set.
        """
        # Capture final RNG state
        if self._rng:
            outcome.rng_state = self._rng.get_state()
        
        self.pending_outcome = outcome
        self.our_hash = outcome.compute_hash()
    
    def get_our_hash(self):
        """
        Get our computed hash for this turn.
        
        Returns:
            bytes: 16-byte hash, or None if not computed.
        """
        return self.our_hash
    
    def receive_opponent_hash(self, their_hash):
        """
        Receive opponent's hash and check consensus.
        
        Args:
            their_hash (bytes): Opponent's 16-byte outcome hash.
            
        Returns:
            int: CONSENSUS_PENDING, CONSENSUS_AGREED, or CONSENSUS_FAILED.
        """
        self.their_hash = their_hash
        
        if self.our_hash is None:
            return CONSENSUS_PENDING
        
        return self._check_consensus()
    
    def _check_consensus(self):
        """
        Check if hashes match.
        
        Returns:
            int: CONSENSUS_AGREED or CONSENSUS_FAILED.
        """
        if self.our_hash == self.their_hash:
            return CONSENSUS_AGREED
        else:
            return CONSENSUS_FAILED
    
    def commit_turn(self):
        """
        Commit the turn after consensus achieved.
        
        Call this after CONSENSUS_AGREED to advance to next turn.
        
        Returns:
            TurnOutcome: The committed outcome.
            
        Raises:
            RuntimeError: If consensus not achieved.
        """
        if self.our_hash is None or self.their_hash is None:
            raise RuntimeError("Cannot commit: consensus not verified")
        
        if self.our_hash != self.their_hash:
            raise RuntimeError("Cannot commit: consensus failed")
        
        outcome = self.pending_outcome
        self.history.append(outcome)
        
        # Advance to next turn
        self.current_turn += 1
        self.pending_outcome = None
        self.our_hash = None
        self.their_hash = None
        self._rng = None
        
        return outcome
    
    def get_battle_hash(self):
        """
        Get hash of entire battle history.
        
        Useful for post-battle verification.
        
        Returns:
            bytes: 16-byte hash of all committed turns.
        """
        data = struct.pack('<H', len(self.history))
        for outcome in self.history:
            data += outcome.compute_hash()
        
        return uhashlib.sha1(data).digest()[:16]
    
    def void_battle(self, reason="consensus_failed"):
        """
        Mark battle as void due to consensus failure.
        
        Args:
            reason (str): Reason for voiding.
            
        Returns:
            dict: Void info including turn number and reason.
        """
        return {
            'voided': True,
            'reason': reason,
            'turn': self.current_turn,
            'our_hash': self.our_hash.hex() if self.our_hash else None,
            'their_hash': self.their_hash.hex() if self.their_hash else None,
        }
