"""Station/Gym definitions for the CactusCon badge battle system."""

from micropython import const

from cactuscon.game.engine.characters import get_character, CharacterStats

# AI Difficulty level constants
DIFFICULTY_EASY = const(0)    # 70% random, 30% smart
DIFFICULTY_MEDIUM = const(1)  # 40% random, 60% smart  
DIFFICULTY_HARD = const(2)    # 10% random, 90% smart

# Difficulty names for display
DIFFICULTY_NAMES = ('Easy', 'Medium', 'Hard')


class Station:
    """
    A battle station/gym in the CactusCon game.
    
    Stations are fixed locations with preset characters and AI difficulty.
    Players challenge stations to earn badges/rewards.
    
    Attributes:
        id (str): Unique station identifier.
        name (str): Display name.
        character_id (str): ID of the character this station uses.
        difficulty (int): AI difficulty level (DIFFICULTY_*).
        description (str): Optional description.
        rewards (dict): Optional rewards for defeating station.
    
    Example:
        gym = Station(
            'gym_ctf_1', 'CTF Challenge Gym',
            character_id='pwnyboi',
            difficulty=DIFFICULTY_HARD
        )
    """
    
    __slots__ = ('id', 'name', 'character_id', 'difficulty', 'description', 'rewards', 'extra')
    
    def __init__(self, station_id, name, character_id='hacktarmon',
                 difficulty=DIFFICULTY_MEDIUM, description=None, rewards=None, **extra):
        """
        Initialize a station.
        
        Args:
            station_id (str): Unique station identifier.
            name (str): Display name.
            character_id (str): Character ID this station battles with.
            difficulty (int): DIFFICULTY_* constant.
            description (str): Optional description text.
            rewards (dict): Optional rewards dict.
            **extra: Additional attributes.
        """
        self.id = station_id
        self.name = name
        self.character_id = character_id
        self.difficulty = difficulty
        self.description = description
        self.rewards = rewards if rewards else {}
        self.extra = extra if extra else {}
    
    def get_difficulty_name(self):
        """
        Get human-readable difficulty name.
        
        Returns:
            str: Difficulty name string.
        """
        if 0 <= self.difficulty < len(DIFFICULTY_NAMES):
            return DIFFICULTY_NAMES[self.difficulty]
        return 'Unknown'
    
    def get_character(self):
        """
        Get the Character instance for this station.
        
        Returns:
            Character or None: Character this station uses.
        """
        return get_character(self.character_id)
    
    def get_battle_stats(self):
        """
        Get battle-ready stats for this station's character.
        
        Returns:
            CharacterStats: Fresh stats for battle.
        """
        char = self.get_character()
        if char:
            return char.get_battle_stats()
        # Fallback if character not found
        return CharacterStats()
    
    def get_battle_stats_dict(self):
        """
        Get battle-ready stats as dictionary.
        
        Returns:
            dict: Stats dictionary for battle protocol.
        """
        return self.get_battle_stats().to_dict()
    
    def get_moves(self):
        """
        Get move list for this station's character.
        
        Returns:
            list: List of move IDs.
        """
        char = self.get_character()
        return char.moves if char else [0, 1, 2, 3]
    
    def to_dict(self):
        """
        Convert to dictionary format (for serialization/legacy compatibility).
        
        Returns:
            dict: Station data as dictionary.
        """
        data = {
            'id': self.id,
            'name': self.name,
            'character': self.character_id,
            'difficulty': self.difficulty,
        }
        if self.description:
            data['description'] = self.description
        if self.rewards:
            data['rewards'] = self.rewards
        if self.extra:
            data.update(self.extra)
        return data
    
    @classmethod
    def from_dict(cls, station_id, data):
        """
        Create Station from dictionary format.
        
        Args:
            station_id (str): Station identifier (may come from dict key).
            data (dict): Station data dictionary.
            
        Returns:
            Station: New Station instance.
        """
        return cls(
            station_id=station_id,
            name=data.get('name', 'Unknown Station'),
            character_id=data.get('character', 'hacktarmon'),
            difficulty=data.get('difficulty', DIFFICULTY_MEDIUM),
            description=data.get('description'),
            rewards=data.get('rewards'),
        )
    
    def __repr__(self):
        return f"Station('{self.id}', '{self.name}', char='{self.character_id}', diff={self.get_difficulty_name()})"


# ==================== Station Registry ====================

class StationRegistry:
    """
    Registry of all available stations in the game.
    
    Provides centralized access to station definitions by ID.
    Initialize with register_defaults() to load standard stations.
    
    Example:
        registry = StationRegistry()
        registry.register_defaults()
        gym = registry.get('gym_ctf_1')
    """
    
    def __init__(self):
        self._stations = {}
        self._default_station = None
    
    def register(self, station):
        """
        Register a station in the registry.
        
        Args:
            station (Station): Station instance to register.
        """
        self._stations[station.id] = station
    
    def set_default(self, station):
        """
        Set the default station (used when ID not found).
        
        Args:
            station (Station): Default station instance.
        """
        self._default_station = station
        if station.id not in self._stations:
            self.register(station)
    
    def get(self, station_id):
        """
        Get station by ID, or default if not found.
        
        Args:
            station_id (str): Station identifier.
            
        Returns:
            Station or None: Station instance.
        """
        station = self._stations.get(station_id)
        if station is None and self._default_station:
            return self._default_station
        return station
    
    def all(self):
        """
        Get all registered stations.
        
        Returns:
            list: All Station instances.
        """
        return list(self._stations.values())
    
    def ids(self):
        """
        Get all station IDs.
        
        Returns:
            list: All registered station IDs.
        """
        return list(self._stations.keys())
    
    def register_defaults(self):
        """
        Register all default game stations.
        
        Call this to populate registry with standard CactusCon stations.
        """
        defaults = [
            Station('enigmox_gym', 'Enigmox Gym', character_id='enigmox', difficulty=DIFFICULTY_EASY),
            Station('hackachu_gym', 'Hackachu Gym', character_id='hackachu', difficulty=DIFFICULTY_MEDIUM),
            Station('voltreign_gym', 'Voltreign Gym', character_id='voltreign', difficulty=DIFFICULTY_HARD),
            Station('cinderserp_gym', 'Cinderserp Gym', character_id='cinderserp', difficulty=DIFFICULTY_MEDIUM),
            Station('runewing_gym', 'Runewing Gym', character_id='runewing', difficulty=DIFFICULTY_HARD),
        ]
        
        for station in defaults:
            self.register(station)
        
        # Set default station
        default = Station('default', 'Unknown Station', character_id='hacktarmon', difficulty=DIFFICULTY_MEDIUM)
        self.set_default(default)


# Global station registry instance
_station_registry = None

def get_station_registry():
    """
    Get the global station registry, initializing if needed.
    
    Returns:
        StationRegistry: Global station registry instance.
    """
    global _station_registry
    if _station_registry is None:
        _station_registry = StationRegistry()
        _station_registry.register_defaults()
    return _station_registry


def set_station_registry(registry):
    """
    Set the global station registry implementation.

    Pass None to reset to default lazy initialization.
    """
    global _station_registry
    if registry is not None and not isinstance(registry, StationRegistry):
        raise TypeError("registry must be StationRegistry or None")
    _station_registry = registry


def reset_station_registry():
    """Reset to the built-in station registry defaults."""
    set_station_registry(None)


def set_station_definitions(stations, default_station=None):
    """
    Replace active station definitions with custom Station objects.
    """
    registry = StationRegistry()
    for station in stations or ():
        if not isinstance(station, Station):
            raise TypeError("stations must contain Station instances")
        registry.register(station)
    if default_station is not None:
        if not isinstance(default_station, Station):
            raise TypeError("default_station must be Station or None")
        registry.set_default(default_station)
    if not registry.ids():
        raise ValueError("stations must contain at least one Station")
    set_station_registry(registry)
    return registry


def get_station_character_ids(include_default=False):
    """
    Return character IDs referenced by currently active stations.
    """
    ids = []
    seen = set()
    for station in get_station_registry().all():
        if not station:
            continue
        if not include_default and getattr(station, "id", "") == "default":
            continue
        char_id = getattr(station, "character_id", None)
        if char_id and char_id not in seen:
            seen.add(char_id)
            ids.append(char_id)
    return ids


def get_station(station_id):
    """
    Convenience function to get a station by ID.
    
    Args:
        station_id (str): Station identifier.
        
    Returns:
        Station or None: Station instance if found.
    """
    return get_station_registry().get(station_id)
