"""Character validation, evolution, and cleanup for the CactusCon badge battle system.

Handles validation of player character inventory, evolution mechanics, and cleanup.
"""

from cactuscon.prefs import make_key
from cactuscon.game.engine.character.base import EVOLVE_REQUIRED_LEVEL

# NVS keys for player stats (legacy keys for migration)
KEY_XP = make_key("pl", "xp")
KEY_LVL = make_key("pl", "lvl")


def validate_and_cleanup_player_characters(prefs, reset_level_on_new_char=True):
    """
    Validate player's character inventory and clean up invalid entries.
    
    This function:
    1. Removes any characters from the player's pack that are not in EVOLUTION_TREE_INDEX
    2. Removes any owned forms that are not valid
    3. If the active character is invalid or not set, assigns a random first-stage
       character (excluding hackachu line) and resets level/XP to 1/0
    
    Args:
        prefs: Preferences manager instance.
        reset_level_on_new_char: If True, resets level to 1 and XP to 0 when
                                 assigning a new random character.
    
    Returns:
        dict: {
            'cleaned': bool - True if any cleanup was performed,
            'removed_chars': list - Character IDs that were removed,
            'new_active': str or None - New active character if one was assigned,
            'level_reset': bool - True if level/XP was reset
        }
    """
    from cactuscon.game.engine.character.registry import (
        get_all_valid_character_ids,
        get_random_starter,
    )
    from cactuscon.game.engine.character.pack import (
        get_player_pack,
        get_owned_forms,
        set_owned_forms,
        PACK_KEY,
        ACTIVE_CHAR_KEY,
    )
    from cactuscon.game.engine.character.stats import (
        get_creature_stats,
        init_creature_stats,
    )
    
    valid_ids = get_all_valid_character_ids()
    result = {
        'cleaned': False,
        'removed_chars': [],
        'new_active': None,
        'level_reset': False,
    }
    
    # Load current state
    pack = get_player_pack(prefs)
    current_chars = pack.get("characters", []) or []
    active_char = pack.get("active_character", "")
    owned_forms = get_owned_forms(prefs) or []
    
    # Filter out invalid characters from pack
    valid_chars = [c for c in current_chars if c in valid_ids]
    removed_from_pack = [c for c in current_chars if c not in valid_ids]
    
    # Filter out invalid owned forms
    valid_owned = [f for f in owned_forms if f in valid_ids]
    removed_from_owned = [f for f in owned_forms if f not in valid_ids]
    
    # Track all removed characters
    all_removed = set(removed_from_pack + removed_from_owned)
    result['removed_chars'] = list(all_removed)
    
    # Check if active character is valid
    active_is_valid = active_char and active_char in valid_ids
    
    # If we removed anything, update the stored lists
    if removed_from_pack:
        from cactuscon.game.engine.character.pack import _save_csv_list
        _save_csv_list(
            prefs,
            PACK_KEY,
            valid_chars,
            context="character.evolution.validate_cleanup pack",
        )
        result['cleaned'] = True
    
    if removed_from_owned:
        set_owned_forms(prefs, valid_owned)
        result['cleaned'] = True
    
    # Handle invalid or missing active character
    if not active_is_valid:
        # Try to use first valid character from pack
        if valid_chars:
            new_active = valid_chars[0]
        else:
            # No valid characters - assign a random starter
            new_active = get_random_starter(exclude_hackachu_line=True)
            if new_active:
                # Add to pack and owned forms
                valid_chars.append(new_active)
                if new_active not in valid_owned:
                    valid_owned.append(new_active)
                
                from cactuscon.game.engine.character.pack import _save_csv_list
                _save_csv_list(
                    prefs,
                    PACK_KEY,
                    valid_chars,
                    context="character.evolution.validate_cleanup new_starter pack",
                )
                set_owned_forms(prefs, valid_owned)
        
        if new_active:
            # Set as active character
            prefs.begin(write=True, context="character.evolution.validate_cleanup set_active")
            prefs.set_string(ACTIVE_CHAR_KEY, new_active)
            prefs.end()
            
            result['new_active'] = new_active
            result['cleaned'] = True
            
            # Initialize per-creature stats for the new character if not already present
            # This ensures the new starter has level 1, 0 XP tracked per-creature
            current_stats = get_creature_stats(prefs, new_active)
            if current_stats['level'] <= 1 and current_stats['xp'] == 0:
                # Initialize at level 1
                init_creature_stats(prefs, new_active, level=1, xp=0)
            
            # Also reset legacy global keys for backwards compatibility
            if reset_level_on_new_char and new_active not in current_chars:
                prefs.begin(write=True, context="character.evolution.validate_cleanup reset_level")
                prefs.set_int32(KEY_LVL, 1)
                prefs.set_int32(KEY_XP, 0)
                prefs.end()
                result['level_reset'] = True
    
    return result


def can_evolve(prefs, char_id):
    """
    Check if a creature can evolve.
    
    Requirements:
    1. Creature is at EVOLVE_REQUIRED_LEVEL or higher
    2. There is a next evolution form
    3. Player does not already own the next evolution form
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to check.
        
    Returns:
        dict: {
            'can_evolve': bool,
            'reason': str - Explanation if cannot evolve,
            'next_form': Character or None,
            'current_level': int
        }
    """
    from cactuscon.game.engine.character.registry import get_next_evolution
    from cactuscon.game.engine.character.pack import get_owned_forms
    from cactuscon.game.engine.character.stats import get_creature_stats
    
    stats = get_creature_stats(prefs, char_id)
    current_level = stats['level']
    
    # Check level requirement
    if current_level < EVOLVE_REQUIRED_LEVEL:
        return {
            'can_evolve': False,
            'reason': f'Need level {EVOLVE_REQUIRED_LEVEL} (currently {current_level})',
            'next_form': None,
            'current_level': current_level,
        }
    
    # Check if there's a next form
    next_form = get_next_evolution(char_id)
    if not next_form:
        return {
            'can_evolve': False,
            'reason': 'Already at final evolution',
            'next_form': None,
            'current_level': current_level,
        }
    
    # Check if player already owns the next form
    owned = get_owned_forms(prefs) or []
    if next_form.id in owned:
        return {
            'can_evolve': False,
            'reason': f'Already own {next_form.name}',
            'next_form': next_form,
            'current_level': current_level,
        }
    
    return {
        'can_evolve': True,
        'reason': 'Ready to evolve',
        'next_form': next_form,
        'current_level': current_level,
    }


def evolve_creature(prefs, char_id, battle_manager=None):
    """
    Evolve a creature to its next form.
    
    This will:
    1. Verify evolution is allowed
    2. Clear the current form's level/XP stats
    3. Remove current form from owned forms
    4. Add next form to owned forms and pack
    5. Initialize next form at level 1
    6. Set next form as active character
    7. Notify battle_manager of the character switch
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to evolve.
        battle_manager: Optional BattleManager instance to notify of the switch.
        
    Returns:
        dict: {
            'success': bool,
            'reason': str,
            'old_form': str - Previous form ID,
            'new_form': str or None - New form ID if successful,
            'new_stats': dict or None - New form's stats,
            'battle_mgr_updated': bool
        }
    """
    from cactuscon.game.engine.character.pack import (
        get_player_pack,
        get_owned_forms,
        set_owned_forms,
        _save_csv_list,
        PACK_KEY,
        ACTIVE_CHAR_KEY,
    )
    from cactuscon.game.engine.character.stats import (
        clear_creature_stats,
        init_creature_stats,
    )
    
    # Check if evolution is allowed
    check = can_evolve(prefs, char_id)
    if not check['can_evolve']:
        return {
            'success': False,
            'reason': check['reason'],
            'old_form': char_id,
            'new_form': None,
            'new_stats': None,
            'battle_mgr_updated': False,
        }
    
    next_form = check['next_form']
    
    # Clear old form's stats
    clear_creature_stats(prefs, char_id)
    
    # Update owned forms: remove old, add new
    owned = get_owned_forms(prefs) or []
    if char_id in owned:
        owned.remove(char_id)
    if next_form.id not in owned:
        owned.append(next_form.id)
    set_owned_forms(prefs, owned)
    
    # Update pack: remove old, add new
    pack = get_player_pack(prefs)
    chars = pack.get("characters", []) or []
    if char_id in chars:
        chars.remove(char_id)
    if next_form.id not in chars:
        chars.append(next_form.id)
    _save_csv_list(prefs, PACK_KEY, chars, context="character.evolution.evolve pack")
    
    # Initialize new form at level 1
    new_stats = init_creature_stats(prefs, next_form.id, level=1, xp=0)
    
    # Set as active character
    prefs.begin(write=True, context="character.evolution.evolve set_active")
    prefs.set_string(ACTIVE_CHAR_KEY, next_form.id)
    prefs.end()
    
    # Notify battle_manager of the character switch
    battle_mgr_updated = False
    if battle_manager is not None:
        try:
            battle_mgr_updated = battle_manager.set_active_character(next_form.id)
        except Exception:
            pass
    
    return {
        'success': True,
        'reason': f'Evolved to {next_form.name}!',
        'old_form': char_id,
        'new_form': next_form.id,
        'new_stats': new_stats,
        'battle_mgr_updated': battle_mgr_updated,
    }
