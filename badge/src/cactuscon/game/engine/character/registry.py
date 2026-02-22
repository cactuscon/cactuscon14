"""Character registry and evolution tree for the CactusCon badge battle system.

Contains the EVOLUTION_TREE_INDEX with all 15 creatures across 5 evolution lines,
and the CharacterRegistry for looking up characters.
"""

from cactuscon.game.engine.character.base import Character, CharacterStats

# ==================== Evolution Tree Index ====================
# Sprite mappings:
# - hackachushiny.rgb565 → Hackachu line (Cacti element)
# - radiomon.rgb565 → Voltqueen line (Electricity element)
# - shadow.rgb565 → Cinderserp line (Poison element)
# - glitch.rgb565 → Glyphbat line (Radiowaves element)
# - zombie.rgb565 → Enigmox line (Shadow/Stealth element)

EVOLUTION_TREE_INDEX = {
    # ==================== HACKACHU LINE (Cacti Element) ====================
    'hackachu': [
        Character(
            'hacktarchu',
            'Hacktarchu',
            cid=0,
            stats=CharacterStats(hp=78, attack=12, defense=9, sp_attack=9, sp_defense=9, speed=23),
            moves=[0, 1, 2, 3],  # BrambleRush, GaiterGuard, NeedleBurst, PatchWeave
            sprite_path='/assets/images/sprites/hacktarchu.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=0,
            element='cacti',
            bio='A curious seedling cactus that sparks with digital energy. Quick on its feet but still learning to control its prickly powers.',
            strengths='High speed, good physical attack',
            weaknesses='Low HP and defense',
        ),
        Character(
            'hackachu',
            'Hackachu',
            cid=1,
            stats=CharacterStats(hp=102, attack=14, defense=10, sp_attack=10, sp_defense=10, speed=16),
            moves=[0, 1, 4, 5],  # BrambleRush, GaiterGuard, BunnyHack, TokenWard
            sprite_path='/assets/images/sprites/hackachu.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=1,
            element='cacti',
            bio='A balanced cactus hacker that has learned to weaponize its thorns. Trades speed for resilience as it matures.',
            strengths='Well-rounded stats, reliable attacks',
            weaknesses='No standout specialty',
        ),
        Character(
            'hackachimon',
            'Hackachimon',
            cid=2,
            stats=CharacterStats(hp=135, attack=18, defense=14, sp_attack=12, sp_defense=13, speed=11),
            moves=[0, 1, 6, 7],  # BrambleRush, GaiterGuard, RogueRampage, VaultStance
            sprite_path='/assets/images/sprites/hackachimon.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=2,
            element='cacti',
            bio='A fortress of thorns and code. This final form sacrifices speed for devastating power and unbreakable defenses.',
            strengths='Excellent HP and defense, powerful attacks',
            weaknesses='Very slow',
        ),
    ],

    # ==================== VOLTQUEEN LINE (Electricity Element) ====================
    'voltqueen': [
        Character(
            'voltiny',
            'Voltiny',
            cid=3,
            stats=CharacterStats(hp=62, attack=12, defense=9, sp_attack=9, sp_defense=9, speed=60),
            moves=[10, 11, 12, 13],  # StingJolt, WingParry, CableWhip, FuseGuard
            sprite_path='/assets/images/sprites/voltiny.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=0,
            element='electricity',
            bio='A tiny electric wasp buzzing with static charge. Zips around the battlefield faster than opponents can react.',
            strengths='Highest speed in early game',
            weaknesses='Fragile, low HP and defense',
        ),
        Character(
            'voltqueen',
            'Voltqueen',
            cid=4,
            stats=CharacterStats(hp=88, attack=16, defense=9, sp_attack=11, sp_defense=9, speed=48),
            moves=[10, 11, 14, 15],  # StingJolt, WingParry, ArcFlash, Ground
            sprite_path='/assets/images/sprites/voltqueen.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=1,
            element='electricity',
            bio='The hive queen commands voltage like a scepter. Her arc flash attacks can short-circuit any defense system.',
            strengths='Great speed and attack balance',
            weaknesses='Still relatively fragile',
        ),
        Character(
            'voltreign',
            'Voltreign',
            cid=5,
            stats=CharacterStats(hp=118, attack=22, defense=12, sp_attack=16, sp_defense=11, speed=16),
            moves=[10, 11, 16, 17],  # StingJolt, WingParry, StormCharge, SurgeClamp
            sprite_path='/assets/images/sprites/voltreign.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=2,
            element='electricity',
            bio='The ultimate electric monarch. Commands storms and surges with royal authority, trading agility for raw power.',
            strengths='Strong all-around stats, powerful special moves',
            weaknesses='Lost the speed advantage of earlier forms',
        ),
    ],

    # ==================== CINDERSERP LINE (Poison Element) ====================
    'cinderserp': [
        Character(
            'cinderlet',
            'Cinderlet',
            cid=6,
            stats=CharacterStats(hp=84, attack=15, defense=10, sp_attack=8, sp_defense=8, speed=19),
            moves=[20, 21, 22, 23],  # TailLance, ScaleBunker, SmogSpit, CarbonSkin
            sprite_path='/assets/images/sprites/cinderlet.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=0,
            element='poison',
            bio='A small venomous serpent wreathed in toxic fumes. Its smog attacks leave opponents coughing and confused.',
            strengths='Good attack and speed combo',
            weaknesses='Average durability',
        ),
        Character(
            'cinderserp',
            'Cinderserp',
            cid=7,
            stats=CharacterStats(hp=112, attack=18, defense=12, sp_attack=12, sp_defense=13, speed=14),
            moves=[20, 21, 24, 25],  # TailLance, ScaleBunker, VenomByte, Quarantine
            sprite_path='/assets/images/sprites/cinderserp.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=1,
            element='poison',
            bio='The red gem on its head pulses with concentrated venom. Can quarantine opponents in toxic fields.',
            strengths='Strong physical and special attacks',
            weaknesses='Slowing down as it bulks up',
        ),
        Character(
            'cindervipe',
            'Cindervipe',
            cid=8,
            stats=CharacterStats(hp=148, attack=18, defense=13, sp_attack=12, sp_defense=13, speed=10),
            moves=[20, 21, 26, 27],  # TailLance, ScaleBunker, BlackoutGas, Failsafe
            sprite_path='/assets/images/sprites/cindervipe.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=2,
            element='poison',
            bio='An apex predator of toxins. Its blackout gas can fill entire arenas, and its failsafe defenses are nearly impenetrable.',
            strengths='Highest HP and attack in its line, great defense',
            weaknesses='Extremely slow',
        ),
    ],

    # ==================== GLYPHBAT LINE (Radiowaves Element) ====================
    'glyphbat': [
        Character(
            'blipbat',
            'Blipbat',
            cid=9,
            stats=CharacterStats(hp=58, attack=15, defense=11, sp_attack=11, sp_defense=11, speed=30),
            moves=[30, 31, 32, 33],  # RazorDive, CowlGuard, PingScreech, PairLock
            sprite_path='/assets/images/sprites/blipbat.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=0,
            element='radiowaves',
            bio='A tiny bat that communicates through radio pings. The fastest creature in the early game, but extremely fragile.',
            strengths='Fastest base form, excellent initiative',
            weaknesses='Lowest HP and defense',
        ),
        Character(
            'glyphbat',
            'Glyphbat',
            cid=10,
            stats=CharacterStats(hp=76, attack=20, defense=11, sp_attack=11, sp_defense=11, speed=24),
            moves=[30, 31, 34, 35],  # RazorDive, CowlGuard, BeaconBite, KeyCocoon
            sprite_path='/assets/images/sprites/glyphbat.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=1,
            element='radiowaves',
            bio='Covered in glowing glyphs that broadcast on all frequencies. Its beacon bite can disrupt enemy communications.',
            strengths='Great speed and attack, versatile',
            weaknesses='Still fragile compared to other mid-evolutions',
        ),
        Character(
            'runewing',
            'Runewing',
            cid=11,
            stats=CharacterStats(hp=98, attack=19, defense=12, sp_attack=20, sp_defense=12, speed=20),
            moves=[30, 31, 36, 37],  # RazorDive, CowlGuard, RuneStorm, SilentMode
            sprite_path='/assets/images/sprites/runewing.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=2,
            element='radiowaves',
            bio='Ancient runes cover its massive wings, channeling radio storms. Can go completely silent to ambush foes.',
            strengths='Strong attack and solid bulk',
            weaknesses='Lost much of its speed advantage',
        ),
    ],

    # ==================== ENIGMOX LINE (Shadow/Stealth Element) ====================
    'enigmox': [
        Character(
            'cipherkit',
            'Cipherkit',
            cid=12,
            stats=CharacterStats(hp=70, attack=13, defense=10, sp_attack=8, sp_defense=8, speed=27),
            moves=[40, 41, 42, 43],  # ProwlFang, SuitSlip, ShadowPounce, Lockstep
            sprite_path='/assets/images/sprites/cipherkit.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=0,
            element='shadow',
            bio='A small shadow creature that phases between dimensions. Its suit slip ability makes it nearly impossible to hit.',
            strengths='Excellent speed, evasion-focused',
            weaknesses='Low HP and defense',
        ),
        Character(
            'enigmox',
            'Enigmox',
            cid=13,
            stats=CharacterStats(hp=92, attack=18, defense=14, sp_attack=10, sp_defense=10, speed=20),
            moves=[40, 41, 44, 45],  # ProwlFang, SuitSlip, SignalBlur, CoverTrack
            sprite_path='/assets/images/sprites/enigmox.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=1,
            element='shadow',
            bio='An enigma wrapped in shadow. Can blur signals and cover its tracks, making it the perfect infiltrator.',
            strengths='Balanced stats with evasion tricks',
            weaknesses='Jack of all trades, master of none',
        ),
        Character(
            'cryptilox',
            'Cryptilox',
            cid=14,
            stats=CharacterStats(hp=120, attack=18, defense=15, sp_attack=11, sp_defense=19, speed=16),
            moves=[40, 41, 46, 47],  # ProwlFang, SuitSlip, PhantomRun, SealProof
            sprite_path='/assets/images/sprites/cryptilox.rgb565',
            sprite_meta={
                'frames_per_row': 1,
                'num_frames': 1,
                'frame_width': 160,
                'frame_height': 160
            },
            stage=2,
            element='shadow',
            bio='The ultimate shadow operative. Its phantom run phases through any obstacle, and its seal is unbreakable.',
            strengths='Excellent attack and good bulk, strong finisher',
            weaknesses='Traded speed for power',
        ),
    ],
}


def _build_character_cids(evolution_index=None):
    """Build mapping between character IDs and numeric CIDs."""
    evolution_index = evolution_index if evolution_index is not None else EVOLUTION_TREE_INDEX
    cid_map = {}
    reverse_map = {}
    for _, line in evolution_index.items():
        for character in line:
            cid = getattr(character, "cid", None)
            if cid is None:
                raise ValueError(f"Character '{character.id}' missing cid")
            if cid in reverse_map:
                raise ValueError(f"Duplicate cid {cid} for character '{character.id}'")
            cid_map[character.id] = cid
            reverse_map[cid] = character.id
            # Mirror into extra for legacy callers
            character.extra["cid"] = cid
    return cid_map, reverse_map


CHAR_ID_TO_CID = {}
CID_TO_CHAR_ID = {}


def _sync_character_cids(evolution_index=None):
    """
    Rebuild character CID maps in-place.

    In-place mutation preserves compatibility for modules that imported
    CHAR_ID_TO_CID/CID_TO_CHAR_ID objects at import time.
    """
    cid_map, reverse_map = _build_character_cids(evolution_index=evolution_index)
    CHAR_ID_TO_CID.clear()
    CHAR_ID_TO_CID.update(cid_map)
    CID_TO_CHAR_ID.clear()
    CID_TO_CHAR_ID.update(reverse_map)


_sync_character_cids()


# ==================== Character Registry ====================

class CharacterRegistry:
    """
    Registry of all available characters in the game.
    
    Provides centralized access to character definitions by ID or name.
    Initialize with register_evolution_index() to load character definitions.
    
    Example:
        registry = CharacterRegistry()
        registry.register_evolution_index(EVOLUTION_TREE_INDEX)
        deeno = registry.get('deeno')
    """
    
    def __init__(self):
        self._chars_by_id = {}
        self._chars_by_name = {}
        self._evolution_index = {}
    
    def register(self, character):
        """
        Register a character in the registry.
        
        Args:
            character (Character): Character instance to register.
        """
        self._chars_by_id[character.id] = character
        self._chars_by_name[character.name.lower()] = character
    
    def get(self, char_id):
        """
        Get character by ID.
        
        Args:
            char_id (str): Character identifier.
            
        Returns:
            Character or None: Character instance if found.
        """
        return self._chars_by_id.get(char_id)
    
    def get_by_name(self, name):
        """
        Get character by name (case-insensitive).
        
        Args:
            name (str): Character name.
            
        Returns:
            Character or None: Character instance if found.
        """
        return self._chars_by_name.get(name.lower())
    
    def all(self):
        """
        Get all registered characters.
        
        Returns:
            list: All Character instances.
        """
        return list(self._chars_by_id.values())
    
    def ids(self):
        """
        Get all character IDs.
        
        Returns:
            list: All registered character IDs.
        """
        return list(self._chars_by_id.keys())
    
    def register_defaults(self):
        """
        Register all characters from the evolution tree index.
        """
        self.register_evolution_index(EVOLUTION_TREE_INDEX)

    def register_evolution_index(self, evolution_index, replace=True):
        """
        Register all characters from the evolution index.
        """
        if replace:
            self._chars_by_id = {}
            self._chars_by_name = {}
        self._evolution_index = evolution_index if evolution_index else {}
        for _, line in evolution_index.items():
            for character in line:
                self.register(character)

    def get_evolution_index(self):
        """Return the evolution index loaded into this registry."""
        return self._evolution_index


# Global character registry instance
_character_registry = None


def get_character_registry():
    """
    Get the global character registry, initializing if needed.
    
    Returns:
        CharacterRegistry: Global character registry instance.
    """
    global _character_registry
    if _character_registry is None:
        _character_registry = CharacterRegistry()
        _character_registry.register_evolution_index(EVOLUTION_TREE_INDEX)
        _sync_character_cids(EVOLUTION_TREE_INDEX)
    return _character_registry


def set_character_registry(registry):
    """
    Set the global character registry implementation.

    Pass None to reset to default lazy initialization.
    """
    global _character_registry
    if registry is not None and not isinstance(registry, CharacterRegistry):
        raise TypeError("registry must be CharacterRegistry or None")
    _character_registry = registry
    if registry is None:
        _sync_character_cids(EVOLUTION_TREE_INDEX)
    else:
        evolution_index = registry.get_evolution_index()
        if not evolution_index:
            raise ValueError(
                "custom CharacterRegistry must be loaded with an evolution index"
            )
        _sync_character_cids(evolution_index)


def reset_character_registry():
    """Reset to default built-in character registry/data."""
    set_character_registry(None)


def set_evolution_index(evolution_index):
    """
    Replace active character/evolution data with a custom evolution index.
    """
    if not isinstance(evolution_index, dict) or not evolution_index:
        raise ValueError("evolution_index must be a non-empty dict")
    registry = CharacterRegistry()
    registry.register_evolution_index(evolution_index)
    set_character_registry(registry)
    return registry


def get_evolution_index():
    """
    Get active evolution index (custom override or built-in defaults).
    """
    registry = get_character_registry()
    return registry.get_evolution_index() or EVOLUTION_TREE_INDEX


def get_character(char_id):
    """
    Convenience function to get a character by ID.
    
    Args:
        char_id (str): Character identifier.
        
    Returns:
        Character or None: Character instance if found.
    """
    return get_character_registry().get(char_id)


def get_evolution_tree(char_id):
    """
    Get three-stage evolution data for a character.
    
    Returns:
        list[dict]: Forms with id, name, stage, bio, strengths, weaknesses, moves, sprite_path.
    """
    evolution_index = get_evolution_index()
    tree = evolution_index.get(char_id, [])
    if not tree:
        # Try to find a line that contains the character id
        for line in evolution_index.values():
            for character in line:
                if character.id == char_id:
                    tree = line
                    break
            if tree:
                break
    if not tree:
        return []

    forms = []
    for character in tree:
        extra = getattr(character, "extra", {}) or {}
        forms.append({
            'id': character.id,
            'name': character.name,
            'stage': extra.get('stage', 0),
            'bio': extra.get('bio', ''),
            'strengths': extra.get('strengths', ''),
            'weaknesses': extra.get('weaknesses', ''),
            'moves': list(getattr(character, 'moves', [])),
            'sprite_path': getattr(character, 'sprite_path', None),
            'sprite_meta': extra.get('sprite_meta'),
        })
    return forms[:3]


def get_genus_for_character(char_id):
    """
    Get the genus (evolution line key) for a character ID.
    
    Args:
        char_id: Character ID to look up.
        
    Returns:
        str or None: Genus key (e.g., 'hackachu', 'voltqueen') or None if not found.
    """
    for genus, line in get_evolution_index().items():
        for character in line:
            if character.id == char_id:
                return genus
    return None


def get_next_evolution(char_id):
    """
    Get the next evolution form for a character.
    
    Args:
        char_id: Current character ID.
        
    Returns:
        Character or None: Next evolution stage, or None if at final form or not found.
    """
    genus = get_genus_for_character(char_id)
    if not genus:
        return None
    
    line = get_evolution_index().get(genus, [])
    for i, char in enumerate(line):
        if char.id == char_id and i + 1 < len(line):
            return line[i + 1]
    return None


def get_previous_evolution(char_id):
    """
    Get the previous evolution form for a character.
    
    Args:
        char_id: Current character ID.
        
    Returns:
        Character or None: Previous evolution stage, or None if at base form or not found.
    """
    genus = get_genus_for_character(char_id)
    if not genus:
        return None
    
    line = get_evolution_index().get(genus, [])
    for i, char in enumerate(line):
        if char.id == char_id and i > 0:
            return line[i - 1]
    return None


def get_all_valid_character_ids():
    """
    Get all valid character IDs from the evolution tree.
    
    Returns:
        set: All valid character IDs across all evolution lines.
    """
    valid_ids = set()
    for line in get_evolution_index().values():
        for character in line:
            valid_ids.add(character.id)
    return valid_ids


def is_valid_character(char_id):
    """
    Check if a character ID is valid (exists in evolution tree).
    
    Args:
        char_id: Character ID to validate.
        
    Returns:
        bool: True if character exists in EVOLUTION_TREE_INDEX.
    """
    if not char_id:
        return False
    return char_id in get_all_valid_character_ids()


def get_starter_form_ids(exclude_hackachu_line=True):
    """
    Get all first-stage (stage 0) character IDs.
    
    Args:
        exclude_hackachu_line: If True, excludes the hackachu evolution line.
        
    Returns:
        list: First-stage character IDs available for random selection.
    """
    starters = []
    for genus, line in get_evolution_index().items():
        if exclude_hackachu_line and genus == 'hackachu':
            continue
        if line:
            # First character in line is stage 0
            starters.append(line[0].id)
    return starters


def get_random_starter(exclude_hackachu_line=True):
    """
    Get a random first-stage character ID.
    
    Args:
        exclude_hackachu_line: If True, excludes hackachu line from selection.
        
    Returns:
        str: Random starter character ID, or None if no valid starters.
    """
    import random
    starters = get_starter_form_ids(exclude_hackachu_line=exclude_hackachu_line)
    if not starters:
        # Fallback: include hackachu line if no others available
        starters = get_starter_form_ids(exclude_hackachu_line=False)
    if not starters:
        return None
    return random.choice(starters)
