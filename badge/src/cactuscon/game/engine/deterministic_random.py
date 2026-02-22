"""Deterministic RNG for battle consensus - Identical sequences on both devices."""

import struct
from micropython import const


class DeterministicRNG:
    """
    Seeded pseudo-random number generator for battle consensus.
    
    Uses a simple Linear Congruential Generator (LCG) algorithm
    that produces identical sequences when initialized with the
    same seed. Both devices must use the same seed per turn.
    
    Thread Safety: NOT thread-safe. Create one instance per battle.
    
    Attributes:
        _state (int): Current internal state (32-bit).
        _initial_seed (bytes): Original seed for verification.
    
    Algorithm: LCG with parameters from Numerical Recipes
        state = (state * 1664525 + 1013904223) mod 2^32
    """
    
    __slots__ = ('_state', '_initial_seed')
    
    # LCG parameters (from Numerical Recipes)
    # Note: Using plain ints, not const() - const() only works at module level in MicroPython
    _MULTIPLIER = 1664525
    _INCREMENT = 1013904223
    _MODULUS = 0x100000000  # 2^32
    
    def __init__(self, seed=None):
        """
        Initialize RNG with a seed.
        
        Args:
            seed (bytes, int, or None): Seed value.
                - bytes: Converted to 32-bit int via hash
                - int: Used directly (mod 2^32)
                - None: Uses 0 (for testing)
        """
        if seed is None:
            self._state = 0
            self._initial_seed = b'\x00\x00\x00\x00'
        elif isinstance(seed, bytes):
            # Hash bytes to 32-bit int
            self._initial_seed = seed
            self._state = self._hash_seed(seed)
        elif isinstance(seed, int):
            self._state = seed & 0xFFFFFFFF
            self._initial_seed = struct.pack('<I', self._state)
        else:
            raise TypeError(f"Seed must be bytes, int, or None, got {type(seed)}")
    
    def _hash_seed(self, seed_bytes):
        """
        Convert arbitrary bytes to a 32-bit seed.
        
        Uses a simple hash that both devices will compute identically.
        
        Args:
            seed_bytes (bytes): Input bytes.
            
        Returns:
            int: 32-bit hash value.
        """
        # Simple DJB2 hash for deterministic results
        h = 5381
        for b in seed_bytes:
            h = ((h << 5) + h + b) & 0xFFFFFFFF
        return h
    
    def _next(self):
        """
        Generate next random 32-bit value and update state.
        
        Returns:
            int: Random value 0 to 2^32-1.
        """
        self._state = (self._state * self._MULTIPLIER + self._INCREMENT) & 0xFFFFFFFF
        return self._state
    
    def random(self):
        """
        Generate random float in [0.0, 1.0).
        
        Returns:
            float: Random value.
        """
        return self._next() / self._MODULUS
    
    def uniform(self, low, high):
        """
        Generate random float in [low, high).
        
        Args:
            low (float): Lower bound (inclusive).
            high (float): Upper bound (exclusive).
            
        Returns:
            float: Random value in range.
        """
        return low + (high - low) * self.random()
    
    def randint(self, low, high):
        """
        Generate random integer in [low, high] (inclusive).
        
        Args:
            low (int): Lower bound.
            high (int): Upper bound.
            
        Returns:
            int: Random integer in range.
        """
        if low > high:
            low, high = high, low
        return low + (self._next() % (high - low + 1))
    
    def choice(self, seq):
        """
        Choose random element from sequence.
        
        Args:
            seq: Sequence to choose from.
            
        Returns:
            Random element.
        """
        if not seq:
            raise IndexError("Cannot choose from empty sequence")
        return seq[self._next() % len(seq)]
    
    def get_state(self):
        """
        Get current RNG state for verification.
        
        Returns:
            bytes: 4-byte state value.
        """
        return struct.pack('<I', self._state)
    
    def get_seed(self):
        """
        Get original seed.
        
        Returns:
            bytes: Initial seed.
        """
        return self._initial_seed


def create_turn_seed(session_token, turn_number, player_move_id, opponent_move_id):
    """
    Create deterministic seed for a battle turn.
    
    Both devices compute this identically from shared data:
    - Session token (established during handshake)
    - Turn number
    - Both players' move selections
    
    Args:
        session_token (bytes): Session authentication token.
        turn_number (int): Current turn (0-indexed).
        player_move_id (int): Player's selected move.
        opponent_move_id (int): Opponent's selected move.
        
    Returns:
        bytes: 8-byte deterministic seed.
    """
    # Combine all inputs into seed material
    # Order matters: use min/max of move IDs for consistency
    move_a = min(player_move_id, opponent_move_id)
    move_b = max(player_move_id, opponent_move_id)
    
    seed_data = struct.pack('<16sHHH', 
                           session_token[:16] if len(session_token) >= 16 else session_token.ljust(16, b'\x00'),
                           turn_number,
                           move_a,
                           move_b)
    
    # Use DJB2 to create 8-byte seed
    h1 = 5381
    h2 = 5387
    for i, b in enumerate(seed_data):
        if i % 2 == 0:
            h1 = ((h1 << 5) + h1 + b) & 0xFFFFFFFF
        else:
            h2 = ((h2 << 5) + h2 + b) & 0xFFFFFFFF
    
    return struct.pack('<II', h1, h2)


def verify_rng_state(rng, expected_state):
    """
    Verify RNG state matches expected value.
    
    Used for consensus checking - if states don't match,
    devices have diverged and battle should be voided.
    
    Args:
        rng (DeterministicRNG): RNG instance.
        expected_state (bytes): Expected 4-byte state.
        
    Returns:
        bool: True if states match.
    """
    return rng.get_state() == expected_state
