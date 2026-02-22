"""Player pack management for the CactusCon badge battle system.

Handles player character inventory, owned forms, and active character selection.
"""

from cactuscon.prefs import make_key
from cactuscon import config

def _switch_player_creature_cache(creature_id):
    """
    Switch player sprite cache lazily.

    Importing cactuscon.ui.sprites at module import time creates a heavy import
    chain (engine -> UI). Keep this lazy so engine modules remain lightweight.
    """
    if config.AUTO_BATTLE_MODE:
        return
    try:
        from cactuscon.ui.sprites import switch_player_creature_cache
        switch_player_creature_cache(creature_id)
    except Exception:
        # Cache updates are opportunistic; never block gameplay flow.
        pass

# NVS keys for pack data
PACK_KEY = make_key("pc", "chars")
ACTIVE_CHAR_KEY = make_key("pc", "act")
OWNED_FORMS_KEY = make_key("pf", "forms")


def _parse_csv_list(raw, limit=12):
    """Parse a comma-separated string into a unique list with optional limit."""
    if not raw:
        return []
    values = [v for v in raw.split(",") if v]
    seen = set()
    ordered = []
    for v in values:
        if v not in seen:
            ordered.append(v)
            seen.add(v)
        if len(ordered) >= limit:
            break
    return ordered


def _load_csv_list(prefs, key, fallback_key=None, context=None, default=None):
    """Load a CSV list from NVS with optional fallback key."""
    prefs.begin(context=context or f"character.pack.load_{key}")
    raw = prefs.get_string(key, "")
    if not raw and fallback_key:
        raw = prefs.get_string(fallback_key, "")
    prefs.end()
    if raw:
        return _parse_csv_list(raw)
    return list(default or [])


def _save_csv_list(prefs, key, values, fallback_key=None, context=None):
    """Save a list as CSV to NVS."""
    vals = _parse_csv_list(",".join(values))
    prefs.begin(write=True, context=context or f"character.pack.save_{key}")
    prefs.set_string(key, ",".join(vals))
    if fallback_key:
        prefs.set_string(fallback_key, ",".join(vals))
    prefs.end()
    return vals


def get_owned_forms(prefs):
    """Return list of owned form IDs (unique creature+form)."""
    forms = _load_csv_list(
        prefs, OWNED_FORMS_KEY, fallback_key=None, context="character.pack.get_owned_forms"
    )
    if not forms:
        # Seed from existing pack data (legacy)
        pack_ids = _load_csv_list(
            prefs,
            PACK_KEY,
            context="character.pack.seed_forms_from_pack",
        )
        if pack_ids:
            forms = _save_csv_list(
                prefs,
                OWNED_FORMS_KEY,
                pack_ids,
                context="character.pack.seed_forms_save",
            )
    return forms


def set_owned_forms(prefs, form_ids):
    """Persist owned forms list (unique IDs)."""
    return _save_csv_list(
        prefs,
        OWNED_FORMS_KEY,
        form_ids,
        context="character.pack.set_owned_forms",
    )


def get_player_pack(prefs, default_ids=None):
    """
    Load pack contents and active character from prefs.
    
    Returns:
        dict: {'characters': [ids], 'active_character': id}
    """
    default_ids = default_ids if default_ids is not None else []
    char_list = _load_csv_list(
        prefs,
        PACK_KEY,
        context="character.pack.get_player_pack",
        default=default_ids,
    )
    # Active character (fallback to first default if present)
    prefs.begin(context="character.pack.get_player_pack active")
    active = prefs.get_string(ACTIVE_CHAR_KEY)
    prefs.end()

    return {"characters": char_list, "active_character": active}


def set_active_character(prefs, char_id, battle_manager=None):
    """
    Persist the active character selection and notify battle_manager.
    
    This is the central function for switching creatures. It:
    1. Saves the new active character to NVS
    2. Notifies the battle_manager to update its internal state
    3. Does NOT reset per-creature stats (each creature keeps its own level/XP)
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to set as active.
        battle_manager: Optional BattleManager instance to notify of the switch.
        
    Returns:
        dict: {
            'success': bool,
            'old_active': str or None,
            'new_active': str,
            'battle_mgr_updated': bool
        }
    """
    # Get current state
    pack = get_player_pack(prefs)
    old_active = pack.get("active_character", "")
    chars = pack.get("characters", []) or []
    
    # Preserve existing pack list
    _save_csv_list(
        prefs,
        PACK_KEY,
        chars,
        context="character.pack.set_active_character pack",
    )
    
    # Set new active character
    prefs.begin(write=True, context="character.pack.set_active_character")
    prefs.set_string(ACTIVE_CHAR_KEY, char_id)
    prefs.end()
    
    # Update sprite cache for new creature's evolution tree (best effort).
    _switch_player_creature_cache(char_id)
    
    # Notify battle_manager if provided
    battle_mgr_updated = False
    if battle_manager is not None:
        try:
            battle_mgr_updated = battle_manager.set_active_character(char_id)
        except Exception:
            pass
    
    return {
        'success': True,
        'old_active': old_active,
        'new_active': char_id,
        'battle_mgr_updated': battle_mgr_updated,
    }


def get_current_form_index(prefs, char_id):
    """Load current evolution stage index (0-2) based on owned forms."""
    from cactuscon.game.engine.character.registry import get_evolution_tree
    forms = get_evolution_tree(char_id)
    owned_forms = set(get_owned_forms(prefs) or [])
    highest_stage = 0
    for form in forms:
        if form.get("id") in owned_forms:
            highest_stage = max(highest_stage, form.get("stage", 0))
    if highest_stage < 0:
        highest_stage = 0
    if highest_stage > 2:
        highest_stage = 2
    return highest_stage


def set_current_form_index(prefs, char_id, idx):
    """Persist evolution stage index (0-2) for a character."""
    from cactuscon.game.engine.character.registry import get_evolution_tree
    idx = max(0, min(2, int(idx)))
    forms = get_evolution_tree(char_id)
    if not forms:
        return idx
    if idx >= len(forms):
        idx = len(forms) - 1
    target_form = forms[idx]
    target_id = target_form.get("id")

    # Add target form to owned list
    owned = get_owned_forms(prefs) or []
    if target_id not in owned:
        owned.append(target_id)
    set_owned_forms(prefs, owned)

    # Add to pack and set active to this form
    pack = get_player_pack(prefs, default_ids=[char_id]) or {}
    chars = pack.get("characters", []) or []
    if target_id not in chars:
        chars.append(target_id)
    _save_csv_list(
        prefs,
        PACK_KEY,
        chars,
        context="character.pack.set_current_form_index pack",
    )
    # Update active character to evolved form
    prefs.begin(write=True, context="character.pack.set_current_form_index active")
    prefs.set_string(ACTIVE_CHAR_KEY, target_id)
    prefs.end()
    return idx


def acquire_creature(prefs, char_id, level=1):
    """
    Acquire a new creature (add to pack and initialize stats).
    
    Only adds the creature if the player doesn't already own it.
    Initializes the creature with level 1 and 0 XP.
    
    Args:
        prefs: Preferences manager instance.
        char_id: Character ID to acquire.
        level: Starting level (default 1, typically should stay at 1).
        
    Returns:
        dict: {
            'success': bool,
            'reason': str,
            'acquired': bool - True if newly acquired, False if already owned,
            'char_id': str,
        }
    """
    from cactuscon.game.engine.character.registry import is_valid_character, get_character
    from cactuscon.game.engine.character.stats import init_creature_stats
    
    if not char_id or not is_valid_character(char_id):
        return {
            'success': False,
            'reason': f"Invalid character: {char_id}",
            'acquired': False,
            'char_id': char_id,
        }
    
    # Check if player already owns this creature
    pack = get_player_pack(prefs)
    owned_chars = pack.get("characters", []) or []
    
    if char_id in owned_chars:
        # Already owned
        return {
            'success': True,
            'reason': f"Already own {char_id}",
            'acquired': False,
            'char_id': char_id,
        }
    
    # Add to pack
    if char_id not in owned_chars:
        owned_chars.append(char_id)
    
    # Save updated pack
    prefs.begin(write=True, context="character.pack.acquire pack")
    prefs.set_string(PACK_KEY, ",".join(owned_chars))
    prefs.end()
    
    # Initialize creature stats
    init_creature_stats(prefs, char_id, level=level, xp=0)
    
    # Update owned forms
    owned_forms = get_owned_forms(prefs) or []
    if char_id not in owned_forms:
        owned_forms.append(char_id)
    set_owned_forms(prefs, owned_forms)
    
    character = get_character(char_id)
    char_name = character.name if character else char_id
    
    return {
        'success': True,
        'reason': f"Acquired {char_name}!",
        'acquired': True,
        'char_id': char_id,
    }
