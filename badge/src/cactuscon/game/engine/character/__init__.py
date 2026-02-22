"""Character package for the CactusCon badge battle system.

This package provides character classes, evolution trees, care system,
and player pack management.

Submodules:
    base: Character and CharacterStats classes, XP calculations
    care: Care system (feeding, activities, temperament)
    registry: Evolution tree index and character registry
    pack: Player pack management and owned forms
    stats: Per-creature level/XP tracking
    evolution: Evolution mechanics and validation

For backwards compatibility with code that imports from characters.py,
the main characters.py module re-exports from this package.
"""

# Re-export from base
from cactuscon.game.engine.character.base import (
    # Constants
    XP_BASE_LEVEL,
    XP_LEVEL_EXPONENT,
    EVOLVE_REQUIRED_LEVEL,
    FORM_STAGE_NAMES,
    # Functions
    get_xp_for_level,
    get_total_xp_for_level,
    # Classes
    CharacterStats,
    Character,
)

# Re-export from care
from cactuscon.game.engine.character.care import (
    # Constants
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
    # Functions
    get_care_catalog,
    set_care_catalog,
    tick_care_timers,
    get_care_state,
    set_care_effect,
)

# Re-export from registry
from cactuscon.game.engine.character.registry import (
    # Data
    EVOLUTION_TREE_INDEX,
    CHAR_ID_TO_CID,
    CID_TO_CHAR_ID,
    # Classes
    CharacterRegistry,
    # Functions
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
)

# Re-export from pack
from cactuscon.game.engine.character.pack import (
    # Constants
    PACK_KEY,
    ACTIVE_CHAR_KEY,
    OWNED_FORMS_KEY,
    # Functions
    get_owned_forms,
    set_owned_forms,
    get_player_pack,
    set_active_character,
    get_current_form_index,
    set_current_form_index,
    acquire_creature,
)

# Re-export from stats
from cactuscon.game.engine.character.stats import (
    # Constants
    KEY_XP,
    KEY_LVL,
    # Functions
    get_creature_stats,
    set_creature_stats,
    add_creature_xp,
    clear_creature_stats,
    init_creature_stats,
    get_active_creature_stats,
    migrate_global_stats_to_creature,
)

# Re-export from evolution
from cactuscon.game.engine.character.evolution import (
    validate_and_cleanup_player_characters,
    can_evolve,
    evolve_creature,
)

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
]
