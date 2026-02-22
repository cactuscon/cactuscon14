"""Status effect system for battle mechanics."""

import struct
import urandom
from micropython import const


# Status effect type constants
class StatusEffectType:
    """Status effect type identifiers."""
    NONE = const(0x00)
    BURN = const(0x01)       # Reduces attack, deals damage over time
    POISON = const(0x02)     # Deals damage over time
    PARALYZE = const(0x04)   # Reduces speed, may prevent action
    FREEZE = const(0x08)     # Prevents action until thawed
    SLEEP = const(0x10)      # Prevents action for N turns
    CONFUSE = const(0x20)    # May attack self
    FLINCH = const(0x40)     # Prevents action this turn only


class StatusEffect:
    """
    Represents a status effect applied to a battle entity.
    
    Status effects can:
    - Modify stats (burn reduces attack)
    - Deal periodic damage (poison, burn)
    - Prevent actions (paralysis, sleep, freeze)
    - Cause self-damage (confusion)
    
    Example:
        burn = StatusEffect(
            effect_type=StatusEffectType.BURN,
            duration=5,
            damage_per_turn=10,
            stat_modifier={'attack': 0.5}
        )
    """
    
    __slots__ = ('effect_type', 'duration', 'remaining_turns', 'damage_per_turn',
                 'stat_modifier', 'metadata')
    
    def __init__(self, effect_type, duration=-1, damage_per_turn=0, 
                 stat_modifier=None, metadata=None):
        """
        Initialize a status effect.

        Args:
            effect_type (int): StatusEffectType constant.
            duration (int): Number of turns effect lasts (-1 = permanent until cured).
            damage_per_turn (int): Damage dealt each turn (0 = none).
            stat_modifier (dict, optional): Dict of stat multipliers (e.g., {'attack': 0.5}).
            metadata (dict, optional): Additional effect data.
        """
        self.effect_type = effect_type
        self.duration = duration
        self.remaining_turns = duration
        self.damage_per_turn = damage_per_turn
        self.stat_modifier = stat_modifier or {}
        self.metadata = metadata or {}
    
    def apply_to_stats(self, stats):
        """
        Apply this effect's stat modifiers to entity stats.

        Args:
            stats (dict): Entity stats dict (modified in-place).
        """
        for stat, multiplier in self.stat_modifier.items():
            if stat in stats:
                stats[stat] = int(stats[stat] * multiplier)
    
    def tick(self, stats):
        """
        Process one turn of this effect.

        Args:
            stats (dict): Entity stats dict (modified for damage).

        Returns:
            tuple: (damage_dealt (int), message (str or None), expired (bool)).
        """
        damage = 0
        message = None
        
        # Deal periodic damage
        if self.damage_per_turn > 0:
            damage = self.damage_per_turn
            stats['hp'] = max(0, stats.get('hp', 0) - damage)
            message = f"Took {damage} damage from {self.get_name()}"
        
        # Decrement duration
        if self.duration > 0:
            self.remaining_turns -= 1
            expired = self.remaining_turns <= 0
        else:
            expired = False
        
        return (damage, message, expired)
    
    def prevents_action(self, rng=None):
        """
        Check if this effect prevents the entity from acting this turn.
        
        For consensus battles, pass the deterministic RNG to ensure
        both devices produce identical results.

        Args:
            rng: Optional DeterministicRNG or callable returning float 0-1.
                 If None, uses urandom.random().

        Returns:
            tuple: (prevents (bool), message (str or None)).
        """
        # Helper to get random value
        def get_rand():
            if rng is not None:
                if callable(rng):
                    return rng()
                return rng.random()
            return urandom.random()
        
        if self.effect_type == StatusEffectType.FREEZE:
            # 20% chance to thaw each turn
            if get_rand() < 0.2:
                return (False, "Thawed out!")
            return (True, "Frozen solid!")
        
        elif self.effect_type == StatusEffectType.SLEEP:
            if self.remaining_turns > 0:
                return (True, "Fast asleep!")
            return (False, "Woke up!")
        
        elif self.effect_type == StatusEffectType.PARALYZE:
            # 25% chance to be fully paralyzed
            if get_rand() < 0.25:
                return (True, "Paralyzed!")
            return (False, None)
        
        elif self.effect_type == StatusEffectType.FLINCH:
            # Flinch only lasts one turn
            return (True, "Flinched!")
        
        return (False, None)
    
    def get_name(self):
        """
        Get human-readable effect name.

        Returns:
            str: Name of the status effect.
        """
        names = {
            StatusEffectType.BURN: "burn",
            StatusEffectType.POISON: "poison",
            StatusEffectType.PARALYZE: "paralysis",
            StatusEffectType.FREEZE: "freeze",
            StatusEffectType.SLEEP: "sleep",
            StatusEffectType.CONFUSE: "confusion",
            StatusEffectType.FLINCH: "flinch"
        }
        return names.get(self.effect_type, "unknown")
    
    def serialize(self):
        """
        Serialize effect for network transmission.

        Returns:
            bytes: Packed effect data.
        """
        # Format: type(1), duration(1), remaining(1), damage(1)
        return struct.pack('<BBBB', 
                          self.effect_type, 
                          self.duration & 0xFF,
                          self.remaining_turns & 0xFF,
                          self.damage_per_turn & 0xFF)
    
    @classmethod
    def deserialize(cls, data):
        """
        Deserialize effect from network data.

        Args:
            data (bytes): Packed effect data.

        Returns:
            StatusEffect: Instance or None if invalid.
        """
        if len(data) < 4:
            return None
        
        effect_type, duration, remaining, damage = struct.unpack('<BBBB', data[:4])
        
        effect = cls(
            effect_type=effect_type,
            duration=duration,
            damage_per_turn=damage
        )
        effect.remaining_turns = remaining
        return effect


# Factory functions for common status effects

def create_burn_effect():
    """
    Create a burn status effect (reduces attack, 10 damage/turn).

    Returns:
        StatusEffect: Burn effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.BURN,
        duration=-1,  # Lasts until cured
        damage_per_turn=10,
        stat_modifier={'attack': 0.5}
    )


def create_poison_effect():
    """
    Create a poison status effect (15 damage/turn).

    Returns:
        StatusEffect: Poison effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.POISON,
        duration=-1,
        damage_per_turn=15
    )


def create_paralyze_effect():
    """
    Create a paralysis status effect (reduces speed, may prevent action).

    Returns:
        StatusEffect: Paralyze effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.PARALYZE,
        duration=-1,
        stat_modifier={'speed': 0.25}
    )


def create_sleep_effect(turns=3):
    """
    Create a sleep status effect (prevents action for N turns).

    Args:
        turns (int): Number of turns to sleep.

    Returns:
        StatusEffect: Sleep effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.SLEEP,
        duration=turns
    )


def create_freeze_effect():
    """
    Create a freeze status effect (prevents action until thawed).

    Returns:
        StatusEffect: Freeze effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.FREEZE,
        duration=-1
    )


def create_confuse_effect(turns=3):
    """
    Create a confusion status effect (may attack self).

    Args:
        turns (int): Number of turns confused.

    Returns:
        StatusEffect: Confusion effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.CONFUSE,
        duration=turns
    )


def create_flinch_effect():
    """
    Create a flinch status effect (prevents action this turn only).

    Returns:
        StatusEffect: Flinch effect instance.
    """
    return StatusEffect(
        effect_type=StatusEffectType.FLINCH,
        duration=1
    )
