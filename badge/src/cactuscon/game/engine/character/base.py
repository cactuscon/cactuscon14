"""Base character classes and XP calculations for the CactusCon badge battle system."""

# Game-wide character constants (authoritative for UI)
XP_BASE_LEVEL = 120
XP_LEVEL_EXPONENT = 1.5
EVOLVE_REQUIRED_LEVEL = 5
FORM_STAGE_NAMES = ("Base", "Intermediate", "Final")


def get_xp_for_level(level):
    """XP required to advance through a given level (1-based)."""
    if level < 1:
        level = 1
    return int(XP_BASE_LEVEL * max(((level - 1) ** XP_LEVEL_EXPONENT), 1))


def get_total_xp_for_level(level):
    """Total XP required to reach the start of a given level (1-based)."""
    if level <= 1:
        return 0
    total = 0
    for lvl in range(1, level):
        total += get_xp_for_level(lvl)
    return total


class CharacterStats:
    """
    Battle stats for a character.
    
    Tracks both base stats (permanent) and current battle stats (modified in battle).
    
    Attributes:
        level (int): Creature level (1-5).
        hp (int): Current HP.
        max_hp (int): Maximum HP.
        attack (int): Physical attack power.
        defense (int): Physical defense.
        sp_attack (int): Special attack power.
        sp_defense (int): Special defense.
        speed (int): Speed (determines turn order).
        status (int): Current status flags.
        status_effects (list): Active status effect instances.
    """
    
    __slots__ = (
        'level',
        'hp', 'max_hp', 'attack', 'defense', 'sp_attack', 'sp_defense',
        'speed', 'status', 'status_effects',
        'defense_turns', 'defense_mult', 'defense_elem',
        'sp_defense_turns', 'sp_defense_mult', 'sp_defense_elem',
        'evasion', 'evasion_turns',
    )
    
    def __init__(self, level=1, hp=100, max_hp=None, attack=10, defense=10,
                 sp_attack=10, sp_defense=10, speed=10):
        """
        Initialize character stats.
        
        Args:
            level (int): Creature level (1-5).
            hp (int): Starting/current HP.
            max_hp (int): Maximum HP (defaults to hp).
            attack (int): Physical attack.
            defense (int): Physical defense.
            sp_attack (int): Special attack.
            sp_defense (int): Special defense.
            speed (int): Speed stat.
        """
        self.level = level
        self.hp = hp
        self.max_hp = max_hp if max_hp is not None else hp
        self.attack = attack
        self.defense = defense
        self.sp_attack = sp_attack
        self.sp_defense = sp_defense
        self.speed = speed
        self.status = 0
        self.status_effects = []
        self.evasion = 0
        self.evasion_turns = 0
        self.defense_turns = 0
        self.defense_mult = 1.0
        self.defense_elem = None
        self.sp_defense_turns = 0
        self.sp_defense_mult = 1.0
        self.sp_defense_elem = None
    
    def to_dict(self):
        """
        Convert to dictionary (for serialization/battle protocol).
        
        Returns:
            dict: Stats as dictionary.
        """
        return {
            'level': self.level,
            'hp': self.hp,
            'max_hp': self.max_hp,
            'attack': self.attack,
            'defense': self.defense,
            'sp_attack': self.sp_attack,
            'sp_defense': self.sp_defense,
            'speed': self.speed,
            'status': self.status,
            'status_effects': self.status_effects,
            'evasion': self.evasion,
            'evasion_turns': self.evasion_turns,
            'defense_turns': self.defense_turns,
            'defense_mult': self.defense_mult,
            'defense_elem': self.defense_elem,
            'sp_defense_turns': self.sp_defense_turns,
            'sp_defense_mult': self.sp_defense_mult,
            'sp_defense_elem': self.sp_defense_elem,
        }
    
    @classmethod
    def from_dict(cls, data):
        """
        Create CharacterStats from dictionary.
        
        Args:
            data (dict): Stats dictionary.
            
        Returns:
            CharacterStats: New instance.
        """
        stats = cls(
            hp=data.get('hp', 100),
            max_hp=data.get('max_hp', data.get('hp', 100)),
            attack=data.get('attack', 10),
            defense=data.get('defense', 10),
            sp_attack=data.get('sp_attack', 10),
            sp_defense=data.get('sp_defense', 10),
            speed=data.get('speed', 10),
        )
        stats.status = data.get('status', 0)
        stats.status_effects = data.get('status_effects', [])
        stats.evasion = data.get('evasion', 0)
        stats.evasion_turns = data.get('evasion_turns', 0)
        stats.defense_turns = data.get('defense_turns', 0)
        stats.defense_mult = data.get('defense_mult', 1.0)
        stats.defense_elem = data.get('defense_elem', None)
        stats.sp_defense_turns = data.get('sp_defense_turns', 0)
        stats.sp_defense_mult = data.get('sp_defense_mult', 1.0)
        stats.sp_defense_elem = data.get('sp_defense_elem', None)
        return stats
    
    def clone(self) -> 'CharacterStats':
        """
        Create a copy of these stats (for battle instances).
        
        Returns:
            CharacterStats: New instance with same values.
        """
        stats = CharacterStats(
            hp=self.hp,
            max_hp=self.max_hp,
            attack=self.attack,
            defense=self.defense,
            sp_attack=self.sp_attack,
            sp_defense=self.sp_defense,
            speed=self.speed,
        )
        stats.status = self.status
        stats.status_effects = list(self.status_effects)
        stats.evasion = self.evasion
        stats.evasion_turns = self.evasion_turns
        stats.defense_turns = self.defense_turns
        stats.defense_mult = self.defense_mult
        stats.defense_elem = self.defense_elem
        stats.sp_defense_turns = self.sp_defense_turns
        stats.sp_defense_mult = self.sp_defense_mult
        stats.sp_defense_elem = self.sp_defense_elem
        return stats
    
    def reset_battle_stats(self):
        """Reset HP to max and clear status effects (for new battle)."""
        self.hp = self.max_hp
        self.status = 0
        self.status_effects = []
        self.evasion = 0
        self.evasion_turns = 0
        self.defense_turns = 0
        self.defense_mult = 1.0
        self.defense_elem = None
        self.sp_defense_turns = 0
        self.sp_defense_mult = 1.0
        self.sp_defense_elem = None
    
    def is_fainted(self):
        """Check if character has fainted (HP <= 0)."""
        return self.hp <= 0
    
    def __repr__(self):
        return f"CharacterStats(hp={self.hp}/{self.max_hp}, atk={self.attack}, def={self.defense}, spd={self.speed})"


class Character:
    """
    A battler/creature in the CactusCon game.
    
    Characters are the "hacktarmon" that players battle with. Each has:
    - Unique ID and display name
    - Base stats (HP, attack, defense, speed, etc.)
    - Move set (list of move IDs they can use)
    - Sprite path for display
    
    Example:
        deeno = Character(
            'deeno', 'Deeno',
            cid=0,
            stats=CharacterStats(hp=100, attack=15, defense=12, speed=14),
            moves=[0, 1, 3, 4],
            sprite_path='/assets/images/sprites/deeno.rgb565'
        )
    """
    
    __slots__ = ('id', 'name', 'cid', 'base_stats', 'moves', 'sprite_path', 'extra')
    
    def __init__(self, char_id, name, cid=None, stats=None, moves=None, sprite_path=None, **extra):
        """
        Initialize a character.
        
        Args:
            char_id (str): Unique character identifier.
            name (str): Display name.
            cid (int): Stable numeric character ID used in battle protocol.
            stats (CharacterStats): Base stats (creates default if None).
            moves (list): List of move IDs this character can use.
            sprite_path (str): Path to sprite sheet file.
            **extra: Additional attributes.
        """
        if cid is None:
            raise ValueError(f"Character '{char_id}' is missing required cid")
        self.id = char_id
        self.name = name
        self.cid = cid
        self.base_stats = stats if stats else CharacterStats()
        self.moves = moves if moves else [0, 1, 2, 3]
        self.sprite_path = sprite_path
        self.extra = extra if extra else {}
        # Keep cid mirrored in extra for legacy lookups
        self.extra.setdefault("cid", cid)
    
    def get_battle_stats(self) -> CharacterStats:
        """
        Get a fresh copy of stats for a battle.
        
        Returns:
            CharacterStats: Clone of base stats ready for battle.
        """
        stats = self.base_stats.clone()
        stats.reset_battle_stats()
        return stats
    
    def get_battle_stats_dict(self):
        """
        Get battle-ready stats as dictionary.
        
        Returns:
            dict: Stats dictionary for battle protocol.
        """
        return self.get_battle_stats().to_dict()
    
    def can_use_move(self, move_id):
        """
        Check if character knows this move.
        
        Args:
            move_id (int): Move to check.
            
        Returns:
            bool: True if character can use move.
        """
        return move_id in self.moves
    
    def to_dict(self):
        """
        Convert to dictionary format (for serialization/legacy compatibility).
        
        Returns:
            dict: Character data as dictionary.
        """
        data = {
            'id': self.id,
            'name': self.name,
            'stats': self.base_stats.to_dict(),
            'moves': self.moves,
        }
        if self.sprite_path:
            data['sprite_path'] = self.sprite_path
        if self.extra:
            data.update(self.extra)
        return data
    
    @classmethod
    def from_dict(cls, data):
        """
        Create Character from dictionary format.
        
        Args:
            data (dict): Character data dictionary.
            
        Returns:
            Character: New Character instance.
        """
        stats_data = data.get('stats', {})
        stats = CharacterStats.from_dict(stats_data)
        
        return cls(
            char_id=data.get('id', 'unknown'),
            name=data.get('name', 'Unknown'),
            cid=data.get('cid', 0),
            stats=stats,
            moves=data.get('moves', [0, 1, 2, 3]),
            sprite_path=data.get('sprite_path'),
        )
    
    def __repr__(self):
        return f"Character('{self.id}', '{self.name}', moves={self.moves})"
