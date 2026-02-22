"""Engine extension surface for swapping core game content at runtime."""

from cactuscon.game.engine.character.registry import (
    get_character_registry,
    set_character_registry,
    reset_character_registry,
    set_evolution_index,
    get_evolution_index,
)
from cactuscon.game.engine.character.care import (
    get_care_catalog,
    set_care_catalog,
)
from cactuscon.game.engine.moves import (
    get_move_registry,
    set_move_registry,
    reset_move_registry,
    set_move_definitions,
)
from cactuscon.game.engine.stations import (
    get_station_registry,
    set_station_registry,
    reset_station_registry,
    set_station_definitions,
)
from cactuscon.game.engine.achievements import (
    get_achievement_catalog,
    get_achievement_powers,
    set_achievement_catalog,
)
from cactuscon.game.engine.battle_rules import (
    create_battle_rules,
    set_battle_rules_factory,
    reset_battle_rules_factory,
)

__all__ = [
    "get_character_registry",
    "set_character_registry",
    "reset_character_registry",
    "set_evolution_index",
    "get_evolution_index",
    "get_care_catalog",
    "set_care_catalog",
    "get_move_registry",
    "set_move_registry",
    "reset_move_registry",
    "set_move_definitions",
    "get_station_registry",
    "set_station_registry",
    "reset_station_registry",
    "set_station_definitions",
    "get_achievement_catalog",
    "get_achievement_powers",
    "set_achievement_catalog",
    "create_battle_rules",
    "set_battle_rules_factory",
    "reset_battle_rules_factory",
]
