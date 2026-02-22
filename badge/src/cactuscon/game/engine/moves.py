"""Move definitions for the CactusCon badge battle system."""

from micropython import const


# Move type constants - determines damage calculation method
MOVE_TYPE_PHYSICAL = const(0)   # Uses Attack vs Defense
MOVE_TYPE_SPECIAL = const(1)    # Uses Sp.Attack vs Sp.Defense
MOVE_TYPE_STATUS = const(2)     # Applies status effect (no direct damage)
MOVE_TYPE_HEAL = const(3)       # Restores HP

# Move category constants - used for AI decision making
MOVE_CAT_DAMAGE = const(0)      # Primary damage move
MOVE_CAT_HEAVY = const(1)       # High damage, possibly low accuracy
MOVE_CAT_SUPPORT = const(2)     # Status effect or buff
MOVE_CAT_RECOVERY = const(3)    # HP recovery


class Move:
    """
    Base class for battle moves.
    
    A move is an action a character can take during battle. Each move has:
    - Power: Base damage (0 for non-damaging moves)
    - Accuracy: Chance to hit (0-100)
    - Type: How damage is calculated (physical, special, status, heal)
    - Category: AI classification for smart move selection
    - Priority: Turn order modifier (higher = goes first)
    
    Additional attributes can be set for special moves (heal_percent, effect, etc.)
    
    Example:
        tackle = Move(0, "Tackle", power=10, accuracy=100)
        heal = Move(3, "Patch", power=0, accuracy=100, move_type=MOVE_TYPE_HEAL, heal_percent=25)
    """
    
    __slots__ = ('id', 'name', 'power', 'accuracy', 'move_type', 'category', 
                 'priority', 'heal_percent', 'effect', 'extra')
    
    def __init__(self, move_id, name, power=0, accuracy=100, 
                 move_type=MOVE_TYPE_PHYSICAL, category=MOVE_CAT_DAMAGE,
                 priority=0, heal_percent=0, effect=None, **extra):
        """
        Initialize a move.
        
        Args:
            move_id (int): Unique move identifier.
            name (str): Display name.
            power (int): Base damage (0 for non-damaging).
            accuracy (int): Hit chance 0-100.
            move_type (int): MOVE_TYPE_* constant.
            category (int): MOVE_CAT_* constant for AI.
            priority (int): Turn order modifier.
            heal_percent (int): HP% restored (for heal moves).
            effect (str): Status effect name (for status moves).
            **extra: Additional attributes for special moves.
        """
        self.id = move_id
        self.name = name
        self.power = power
        self.accuracy = accuracy
        self.move_type = move_type
        self.category = category
        self.priority = priority
        self.heal_percent = heal_percent
        self.effect = effect
        self.extra = extra if extra else {}
    
    def is_damaging(self):
        """Check if move deals direct damage."""
        return self.move_type in (MOVE_TYPE_PHYSICAL, MOVE_TYPE_SPECIAL) and self.power > 0
    
    def is_healing(self):
        """Check if move restores HP."""
        return self.move_type == MOVE_TYPE_HEAL
    
    def is_status(self):
        """Check if move applies status effects."""
        return self.move_type == MOVE_TYPE_STATUS
    
    def to_dict(self):
        """
        Convert to dictionary format (for serialization/legacy compatibility).
        
        Returns:
            dict: Move data as dictionary.
        """
        data = {
            'id': self.id,
            'name': self.name,
            'power': self.power,
            'accuracy': self.accuracy,
            'type': self.move_type,
            'category': self.category,
            'priority': self.priority,
        }
        if self.heal_percent:
            data['heal_percent'] = self.heal_percent
        if self.effect:
            data['effect'] = self.effect
        if self.extra:
            data.update(self.extra)
        return data
    
    @classmethod
    def from_dict(cls, data):
        """
        Create Move from dictionary format.
        
        Args:
            data (dict): Move data dictionary.
            
        Returns:
            Move: New Move instance.
        """
        return cls(
            move_id=data.get('id', 0),
            name=data.get('name', 'Unknown'),
            power=data.get('power', 0),
            accuracy=data.get('accuracy', 100),
            move_type=data.get('type', MOVE_TYPE_PHYSICAL),
            category=data.get('category', MOVE_CAT_DAMAGE),
            priority=data.get('priority', 0),
            heal_percent=data.get('heal_percent', 0),
            effect=data.get('effect'),
        )
    
    def __repr__(self):
        return f"Move({self.id}, '{self.name}', power={self.power}, acc={self.accuracy})"


# ==================== Move Registry ====================
# All game moves defined as instances

class MoveRegistry:
    """
    Registry of all available moves in the game.
    
    Provides centralized access to move definitions by ID or name.
    Initialize with register_defaults() to load standard moves.
    
    Example:
        registry = MoveRegistry()
        registry.register_defaults()
        tackle = registry.get(0)
        byte_strike = registry.get_by_name("Byte Strike")
    """
    
    def __init__(self):
        self._moves_by_id = {}
        self._moves_by_name = {}
    
    def register(self, move):
        """
        Register a move in the registry.
        
        Args:
            move (Move): Move instance to register.
        """
        self._moves_by_id[move.id] = move
        self._moves_by_name[move.name.lower()] = move
    
    def get(self, move_id):
        """
        Get move by ID.
        
        Args:
            move_id (int): Move identifier.
            
        Returns:
            Move or None: Move instance if found.
        """
        return self._moves_by_id.get(move_id)
    
    def get_by_name(self, name):
        """
        Get move by name (case-insensitive).
        
        Args:
            name (str): Move name.
            
        Returns:
            Move or None: Move instance if found.
        """
        return self._moves_by_name.get(name.lower())
    
    def all(self):
        """
        Get all registered moves.
        
        Returns:
            list: All Move instances.
        """
        return list(self._moves_by_id.values())
    
    def ids(self):
        """
        Get all move IDs.
        
        Returns:
            list: All registered move IDs.
        """
        return list(self._moves_by_id.keys())
    
    def register_defaults(self):
        """
        Register all default game moves.
        
        Call this to populate registry with standard CactusCon moves.
        
        Elements:
        - Cacti (Hackachu line)
        - Electricity (Voltqueen line)
        - Poison (Cinderserp line)
        - Radiowaves (Glyphbat line)
        - Shadow/Stealth (Enigmox line)
        """
        defaults = [
            # ==================== HACKACHU LINE (Cacti Element) ====================
            # Physical Attack - shared across all evolutions
            Move(0, 'BrambleRush', power=9, accuracy=95, move_type=MOVE_TYPE_PHYSICAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='cacti'),
            # Physical Defense - shared across all evolutions
            Move(1, 'GaiterGuard', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='cacti'),
            # Special Attack - Hacktarchu (stage 0)
            Move(2, 'NeedleBurst', power=5, accuracy=90, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='cacti'),
            # Special Defense - Hacktarchu (stage 0)
            Move(3, 'PatchWeave', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='cacti'),
            # Special Attack - Hackachu (stage 1)
            Move(4, 'BunnyHack', power=7, accuracy=85, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='cacti'),
            # Special Defense - Hackachu (stage 1)
            Move(5, 'TokenWard', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='cacti'),
            # Special Attack - Hackachimon (stage 2)
            Move(6, 'RogueRampage', power=6, accuracy=75, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='cacti'),
            # Special Defense - Hackachimon (stage 2)
            Move(7, 'VaultStance', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='cacti'),

            # ==================== VOLTQUEEN LINE (Electricity Element) ====================
            # Physical Attack - shared across all evolutions
            Move(10, 'StingJolt', power=4, accuracy=95, move_type=MOVE_TYPE_PHYSICAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='electricity'),
            # Physical Defense - shared across all evolutions
            Move(11, 'WingParry', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='evasion_up', element='electricity'),
            # Special Attack - Voltiny (stage 0)
            Move(12, 'CableWhip', power=4, accuracy=90, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='electricity'),
            # Special Defense - Voltiny (stage 0)
            Move(13, 'FuseGuard', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='electricity'),
            # Special Attack - Voltqueen (stage 1)
            Move(14, 'ArcFlash', power=6, accuracy=85, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='electricity'),
            # Special Defense - Voltqueen (stage 1)
            Move(15, 'Ground', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='electricity'),
            # Special Attack - Voltreign (stage 2)
            Move(16, 'StormCharge', power=6, accuracy=75, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='electricity'),
            # Special Defense - Voltreign (stage 2)
            Move(17, 'SurgeAmp', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='electricity'),

            # ==================== CINDERSERP LINE (Poison Element) ====================
            # Physical Attack - shared across all evolutions
            Move(20, 'TailLance', power=6, accuracy=95, move_type=MOVE_TYPE_PHYSICAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='poison'),
            # Physical Defense - shared across all evolutions
            Move(21, 'ScaleBunker', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='poison'),
            # Special Attack - Cindersip (stage 0)
            Move(22, 'SmogSpit', power=6, accuracy=90, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='poison'),
            # Special Defense - Cindersip (stage 0)
            Move(23, 'CarbonSkin', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='poison'),
            # Special Attack - Cinderserp (stage 1)
            Move(24, 'VenomByte', power=5, accuracy=85, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='poison'),
            # Special Defense - Cinderserp (stage 1)
            Move(25, 'Quarantine', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='poison'),
            # Special Attack - CinderserpX (stage 2)
            Move(26, 'BlackoutGas', power=9, accuracy=75, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='poison'),
            # Special Defense - CinderserpX (stage 2)
            Move(27, 'ToxinShield', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='poison'),

            # ==================== GLYPHBAT LINE (Radiowaves Element) ====================
            # Physical Attack - shared across all evolutions
            Move(30, 'RazorDive', power=5, accuracy=95, move_type=MOVE_TYPE_PHYSICAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='radiowaves'),
            # Physical Defense - shared across all evolutions
            Move(31, 'CowlGuard', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='radiowaves'),
            # Special Attack - Blipbat (stage 0)
            Move(32, 'PingScreech', power=6, accuracy=90, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='radiowaves'),
            # Special Defense - Blipbat (stage 0)
            Move(33, 'PairLock', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='radiowaves'),
            # Special Attack - Glyphbat (stage 1)
            Move(34, 'BeaconBite', power=7, accuracy=85, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='radiowaves'),
            # Special Defense - Glyphbat (stage 1)
            Move(35, 'SignalDome', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='radiowaves'),
            # Special Attack - Runewing (stage 2)
            Move(36, 'RuneStorm', power=9, accuracy=75, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='radiowaves'),
            # Special Defense - Runewing (stage 2)
            Move(37, 'SilentMode', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='radiowaves'),

            # ==================== ENIGMOX LINE (Shadow/Stealth Element) ====================
            # Physical Attack - shared across all evolutions
            Move(40, 'QuickStrike', power=4, accuracy=95, move_type=MOVE_TYPE_PHYSICAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='shadow'),
            # Physical Defense - shared across all evolutions
            Move(41, 'QuickStep', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='evasion_up', element='shadow'),
            # Special Attack - Cipherkit (stage 0)
            Move(42, 'ShadowPounce', power=4, accuracy=90, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_DAMAGE, priority=0, element='shadow'),
            # Special Defense - Cipherkit (stage 0)
            Move(43, 'ShadowStep', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='sp_defense_up', element='shadow'),
            # Special Attack - Enigmox (stage 1)
            Move(44, 'VoidLash', power=4, accuracy=85, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='shadow'),
            # Special Defense - Enigmox (stage 1)
            Move(45, 'DarknessVeil', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='shadow'),
            # Special Attack - Cryptilox (stage 2)
            Move(46, 'PhantomStrike', power=5, accuracy=75, move_type=MOVE_TYPE_SPECIAL,
                 category=MOVE_CAT_HEAVY, priority=0, element='shadow'),
            # Special Defense - Cryptilox (stage 2)
            Move(47, 'VoidGuard', power=0, accuracy=100, move_type=MOVE_TYPE_STATUS,
                 category=MOVE_CAT_SUPPORT, priority=0, effect='defense_up', element='shadow'),

            # ==================== UTILITY / RECOVERY MOVES ====================
            Move(100, 'Patch', power=0, accuracy=100, move_type=MOVE_TYPE_HEAL,
                 category=MOVE_CAT_RECOVERY, priority=0, heal_percent=25),
            Move(101, 'Debug', power=0, accuracy=100, move_type=MOVE_TYPE_HEAL,
                 category=MOVE_CAT_RECOVERY, priority=0, heal_percent=50),
        ]
        
        for move in defaults:
            self.register(move)


# Global move registry instance
_move_registry = None

def get_move_registry():
    """
    Get the global move registry, initializing if needed.
    
    Returns:
        MoveRegistry: Global move registry instance.
    """
    global _move_registry
    if _move_registry is None:
        _move_registry = MoveRegistry()
        _move_registry.register_defaults()
    return _move_registry


def set_move_registry(registry):
    """
    Set the global move registry implementation.

    Pass None to reset to default lazy initialization.
    """
    global _move_registry
    if registry is not None and not isinstance(registry, MoveRegistry):
        raise TypeError("registry must be MoveRegistry or None")
    _move_registry = registry


def reset_move_registry():
    """Reset to the built-in move registry defaults."""
    set_move_registry(None)


def set_move_definitions(moves):
    """
    Replace active move definitions with a custom iterable of Move objects.
    """
    registry = MoveRegistry()
    for move in moves or ():
        if not isinstance(move, Move):
            raise TypeError("moves must contain Move instances")
        registry.register(move)
    if not registry.ids():
        raise ValueError("moves must contain at least one Move")
    set_move_registry(registry)
    return registry


def get_move(move_id):
    """
    Convenience function to get a move by ID.
    
    Args:
        move_id (int): Move identifier.
        
    Returns:
        Move or None: Move instance if found.
    """
    return get_move_registry().get(move_id)
