"""Character definitions for the CactusCon badge battle system.

BACKWARDS COMPATIBILITY SHIM
============================
This module re-exports everything from the character/ package for backwards
compatibility. New code should import directly from the submodules:

    from cactuscon.game.engine.character.base import Character, CharacterStats
    from cactuscon.game.engine.character.registry import get_character
    from cactuscon.game.engine.character.pack import get_player_pack

The character/ package structure:
    character/base.py     - Character, CharacterStats classes, XP calculations
    character/care.py     - Care system (feeding, activities, temperament)
    character/registry.py - EVOLUTION_TREE_INDEX, CharacterRegistry
    character/pack.py     - Player pack management, owned forms
    character/stats.py    - Per-creature level/XP tracking
    character/evolution.py - Evolution mechanics and validation
"""

# Re-export everything from the character package for backwards compatibility
from cactuscon.game.engine.character import (
    # base
    XP_BASE_LEVEL,
    XP_LEVEL_EXPONENT,
    EVOLVE_REQUIRED_LEVEL,
    FORM_STAGE_NAMES,
    get_xp_for_level,
    get_total_xp_for_level,
    CharacterStats,
    Character,
    # care
    CARE_EFFECT_DURATION_MS,
    CARE_EFFECT_COOLDOWN_MS,
    CARE_TEMPER_DECAY_MS,
    CARE_TEMPERAMENT_MAX,
    CARE_ACT_ID,
    CARE_ACT_EXP,
    CARE_ACT_SET,
    CARE_ACT_CD,
    CARE_ACT_CD_SET,
    CARE_FOOD_ID,
    CARE_FOOD_EXP,
    CARE_FOOD_SET,
    CARE_FOOD_CD,
    CARE_FOOD_CD_SET,
    CARE_TEMPER_KEY,
    CARE_TEMPER_SET,
    CARE_EFFECT_CATALOG,
    get_care_catalog,
    set_care_catalog,
    tick_care_timers,
    get_care_state,
    set_care_effect,
    # registry
    EVOLUTION_TREE_INDEX,
    CHAR_ID_TO_CID,
    CID_TO_CHAR_ID,
    CharacterRegistry,
    get_character_registry,
    set_character_registry,
    reset_character_registry,
    set_evolution_index,
    get_evolution_index,
    get_character,
    get_evolution_tree,
    get_genus_for_character,
    get_next_evolution,
    get_previous_evolution,
    get_all_valid_character_ids,
    is_valid_character,
    get_starter_form_ids,
    get_random_starter,
    # pack
    PACK_KEY,
    ACTIVE_CHAR_KEY,
    OWNED_FORMS_KEY,
    get_owned_forms,
    set_owned_forms,
    get_player_pack,
    set_active_character,
    get_current_form_index,
    set_current_form_index,
    acquire_creature,
    # stats
    KEY_XP,
    KEY_LVL,
    get_creature_stats,
    set_creature_stats,
    add_creature_xp,
    clear_creature_stats,
    init_creature_stats,
    get_active_creature_stats,
    migrate_global_stats_to_creature,
    # evolution
    validate_and_cleanup_player_characters,
    can_evolve,
    evolve_creature,
)

# Also import internal helpers for any code that might depend on them
from cactuscon.game.engine.character.pack import (
    _parse_csv_list,
    _load_csv_list,
    _save_csv_list,
)
from cactuscon.game.engine.character.stats import (
    _make_creature_xp_key,
    _make_creature_lvl_key,
)


# Legacy compatibility: ensure all original exports are available
__all__ = [
    # base
    'XP_BASE_LEVEL',
    'XP_LEVEL_EXPONENT',
    'EVOLVE_REQUIRED_LEVEL',
    'FORM_STAGE_NAMES',
    'get_xp_for_level',
    'get_total_xp_for_level',
    'CharacterStats',
    'Character',
    # care
    'CARE_EFFECT_DURATION_MS',
    'CARE_EFFECT_COOLDOWN_MS',
    'CARE_TEMPER_DECAY_MS',
    'CARE_TEMPERAMENT_MAX',
    'CARE_ACT_ID',
    'CARE_ACT_EXP',
    'CARE_ACT_SET',
    'CARE_ACT_CD',
    'CARE_ACT_CD_SET',
    'CARE_FOOD_ID',
    'CARE_FOOD_EXP',
    'CARE_FOOD_SET',
    'CARE_FOOD_CD',
    'CARE_FOOD_CD_SET',
    'CARE_TEMPER_KEY',
    'CARE_TEMPER_SET',
    'CARE_EFFECT_CATALOG',
    'get_care_catalog',
    'set_care_catalog',
    'tick_care_timers',
    'get_care_state',
    'set_care_effect',
    # registry
    'EVOLUTION_TREE_INDEX',
    'CHAR_ID_TO_CID',
    'CID_TO_CHAR_ID',
    'CharacterRegistry',
    'get_character_registry',
    'set_character_registry',
    'reset_character_registry',
    'set_evolution_index',
    'get_evolution_index',
    'get_character',
    'get_evolution_tree',
    'get_genus_for_character',
    'get_next_evolution',
    'get_previous_evolution',
    'get_all_valid_character_ids',
    'is_valid_character',
    'get_starter_form_ids',
    'get_random_starter',
    # pack
    'PACK_KEY',
    'ACTIVE_CHAR_KEY',
    'OWNED_FORMS_KEY',
    'get_owned_forms',
    'set_owned_forms',
    'get_player_pack',
    'set_active_character',
    'get_current_form_index',
    'set_current_form_index',
    'acquire_creature',
    # stats
    'KEY_XP',
    'KEY_LVL',
    'get_creature_stats',
    'set_creature_stats',
    'add_creature_xp',
    'clear_creature_stats',
    'init_creature_stats',
    'get_active_creature_stats',
    'migrate_global_stats_to_creature',
    # evolution
    'validate_and_cleanup_player_characters',
    'can_evolve',
    'evolve_creature',
    # internal helpers (for legacy code)
    '_parse_csv_list',
    '_load_csv_list',
    '_save_csv_list',
    '_make_creature_xp_key',
    '_make_creature_lvl_key',
]
