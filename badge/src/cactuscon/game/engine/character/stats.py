"""Per-creature level and XP tracking for the CactusCon badge battle system.

Each creature form has its own level and XP. When a creature evolves,
the old form's state is cleared and the new form starts at level 1.
"""

from cactuscon.prefs import make_key
from cactuscon.game.engine.character.base import (
    XP_BASE_LEVEL,
    EVOLVE_REQUIRED_LEVEL,
    get_xp_for_level,
    get_total_xp_for_level,
)

# NVS keys for player stats (must match battle_manager.py for legacy compatibility)
KEY_XP = make_key("pl", "xp")
KEY_LVL = make_key("pl", "lvl")


def _make_creature_xp_key(char_id):
    """Generate NVS key for creature XP using centralized make_key."""
    return make_key("cx", char_id)


def _make_creature_lvl_key(char_id):
    """Generate NVS key for creature level using centralized make_key."""
    return make_key("cl", char_id)


def get_creature_stats(prefs, char_id):
    """
    Get level and XP for a specific creature.
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to look up.
        
    Returns:
        dict: {'level': int, 'xp': int, 'xp_into_level': int, 'xp_for_level': int}
    """
    from cactuscon.game.engine.character.registry import is_valid_character
    
    if not char_id or not is_valid_character(char_id):
        return {'level': 1, 'xp': 0, 'xp_into_level': 0, 'xp_for_level': XP_BASE_LEVEL}
    
    xp_key = _make_creature_xp_key(char_id)
    lvl_key = _make_creature_lvl_key(char_id)
    
    prefs.begin(context=f"character.stats.get_creature_stats:{char_id}")
    xp = max(0, prefs.get_int32(xp_key, 0))
    level = max(1, prefs.get_int32(lvl_key, 1))
    prefs.end()
    
    xp_for_level = get_xp_for_level(level)
    xp_start = get_total_xp_for_level(level)
    xp_into_level = max(0, xp - xp_start)
    
    return {
        'level': level,
        'xp': xp,
        'xp_into_level': xp_into_level,
        'xp_for_level': xp_for_level,
    }


def set_creature_stats(prefs, char_id, level=None, xp=None):
    """
    Set level and/or XP for a specific creature.
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to update.
        level: New level (or None to leave unchanged).
        xp: New XP total (or None to leave unchanged).
        
    Returns:
        dict: Updated stats.
    """
    if not char_id:
        return None
    
    xp_key = _make_creature_xp_key(char_id)
    lvl_key = _make_creature_lvl_key(char_id)
    
    prefs.begin(write=True, context=f"character.stats.set_creature_stats:{char_id}")
    if xp is not None:
        prefs.set_int32(xp_key, max(0, int(xp)))
    if level is not None:
        prefs.set_int32(lvl_key, max(1, int(level)))
    prefs.end()
    
    return get_creature_stats(prefs, char_id)


def add_creature_xp(prefs, char_id, xp_amount):
    """
    Add XP to a creature and handle level ups.
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to award XP to.
        xp_amount: Amount of XP to add.
        
    Returns:
        dict: {
            'old_level': int,
            'new_level': int,
            'old_xp': int,
            'new_xp': int,
            'leveled_up': bool,
            'levels_gained': int,
            'can_evolve': bool - True if reached EVOLVE_REQUIRED_LEVEL,
            'xp_into_level': int,
            'xp_for_level': int,
        }
    """
    if not char_id or xp_amount <= 0:
        stats = get_creature_stats(prefs, char_id)
        return {
            'old_level': stats['level'],
            'new_level': stats['level'],
            'old_xp': stats['xp'],
            'new_xp': stats['xp'],
            'leveled_up': False,
            'levels_gained': 0,
            'can_evolve': stats['level'] >= EVOLVE_REQUIRED_LEVEL,
            'xp_into_level': stats['xp_into_level'],
            'xp_for_level': stats['xp_for_level'],
        }
    
    current = get_creature_stats(prefs, char_id)
    old_level = current['level']
    old_xp = current['xp']
    
    new_xp = old_xp + xp_amount
    
    # Calculate new level from total XP
    new_level = 1
    while get_total_xp_for_level(new_level + 1) <= new_xp:
        new_level += 1
    
    # Persist
    set_creature_stats(prefs, char_id, level=new_level, xp=new_xp)
    
    # Compute per-level progress for UI/protocol reporting
    xp_for_level = get_xp_for_level(new_level)
    xp_start = get_total_xp_for_level(new_level)
    xp_into_level = max(0, new_xp - xp_start)
    
    return {
        'old_level': old_level,
        'new_level': new_level,
        'old_xp': old_xp,
        'new_xp': new_xp,
        'leveled_up': new_level > old_level,
        'levels_gained': new_level - old_level,
        'can_evolve': new_level >= EVOLVE_REQUIRED_LEVEL,
        'xp_into_level': xp_into_level,
        'xp_for_level': xp_for_level,
    }


def clear_creature_stats(prefs, char_id):
    """
    Clear/reset stats for a specific creature (used when evolving away from a form).
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to clear.
    """
    if not char_id:
        return
    
    xp_key = _make_creature_xp_key(char_id)
    lvl_key = _make_creature_lvl_key(char_id)
    
    prefs.begin(write=True, context=f"character.stats.clear_creature_stats:{char_id}")
    prefs.set_int32(xp_key, 0)
    prefs.set_int32(lvl_key, 0)  # 0 indicates no data/not owned
    prefs.end()


def init_creature_stats(prefs, char_id, level=1, xp=0):
    """
    Initialize stats for a newly acquired creature.
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to initialize.
        level: Starting level (default 1).
        xp: Starting XP (default 0, or calculated from level).
        
    Returns:
        dict: Initialized stats.
    """
    if not char_id:
        return None
    
    # If XP not specified, calculate from level
    if xp == 0 and level > 1:
        xp = get_total_xp_for_level(level)
    
    return set_creature_stats(prefs, char_id, level=level, xp=xp)


def get_active_creature_stats(prefs):
    """
    Get level/XP stats for the currently active creature.
    
    Convenience function that combines get_player_pack and get_creature_stats.
    
    Args:
        prefs: Preferences manager instance.
        
    Returns:
        dict: {
            'char_id': str,
            'level': int,
            'xp': int,
            'xp_into_level': int,
            'xp_for_level': int
        }
    """
    from cactuscon.game.engine.character.pack import get_player_pack
    
    pack = get_player_pack(prefs)
    char_id = pack.get("active_character", "")
    
    if not char_id:
        return {
            'char_id': None,
            'level': 1,
            'xp': 0,
            'xp_into_level': 0,
            'xp_for_level': XP_BASE_LEVEL,
        }
    
    stats = get_creature_stats(prefs, char_id)
    stats['char_id'] = char_id
    return stats


def migrate_global_stats_to_creature(prefs):
    """
    Migrate old global XP/level to the active creature's per-creature stats.
    
    Call this once during upgrade to move from player-global stats to
    per-creature stats. Only migrates if the active creature has no stats.
    
    Args:
        prefs: Preferences manager instance.
        
    Returns:
        dict or None: Migration result or None if no migration needed.
    """
    from cactuscon.game.engine.character.pack import get_player_pack
    
    pack = get_player_pack(prefs)
    char_id = pack.get("active_character", "")
    
    if not char_id:
        return None
    
    # Check if creature already has stats
    current = get_creature_stats(prefs, char_id)
    if current['level'] > 1 or current['xp'] > 0:
        # Already has per-creature stats, no migration needed
        return None
    
    # Load old global stats
    prefs.begin(context="character.stats.migrate_stats read_global")
    old_xp = prefs.get_int32(KEY_XP, 0)
    old_level = prefs.get_int32(KEY_LVL, 1)
    prefs.end()
    
    if old_xp == 0 and old_level <= 1:
        # No global stats to migrate
        return None
    
    # Migrate to creature
    set_creature_stats(prefs, char_id, level=old_level, xp=old_xp)
    
    # Clear global stats (optional - keep for backwards compat or clear)
    # prefs.begin(write=True, context="character.stats.migrate_stats clear_global")
    # prefs.set_int32(KEY_XP, 0)
    # prefs.set_int32(KEY_LVL, 1)
    # prefs.end()
    
    return {
        'char_id': char_id,
        'migrated_level': old_level,
        'migrated_xp': old_xp,
    }
