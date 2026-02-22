"""Extensibility tests for game-engine extension points."""
import copy
import pytest

from cactuscon.game.engine.achievements import (
    get_achievement_catalog,
    get_achievement_powers,
    set_achievement_catalog,
)
from cactuscon.game.engine.battle_rules import (
    BattleRules,
    create_battle_rules,
    reset_battle_rules_factory,
    set_battle_rules_factory,
)
from cactuscon.game.engine.character.base import Character, CharacterStats
from cactuscon.game.engine.character.care import get_care_catalog, set_care_catalog
from cactuscon.game.engine.character.registry import (
    CHAR_ID_TO_CID,
    CID_TO_CHAR_ID,
    get_character,
    reset_character_registry,
    set_evolution_index,
)
from cactuscon.game.engine.stations import (
    DIFFICULTY_HARD,
    Station,
    get_station,
    get_station_character_ids,
    get_station_registry,
    reset_station_registry,
    set_station_definitions,
)

def test_character_registry_supports_runtime_override_and_reset():
    custom_index = {
        "modline": [
            Character(
                "modmon",
                "Modmon",
                cid=200,
                stats=CharacterStats(hp=90, attack=12, defense=11, speed=10),
                moves=[0, 1, 2, 3],
            ),
            Character(
                "modlord",
                "Modlord",
                cid=201,
                stats=CharacterStats(hp=120, attack=16, defense=15, speed=8),
                moves=[0, 1, 2, 3],
            ),
        ]
    }

    try:
        set_evolution_index(custom_index)
        assert get_character("modmon") is not None
        assert CHAR_ID_TO_CID["modmon"] == 200
        assert CID_TO_CHAR_ID[201] == "modlord"
    finally:
        reset_character_registry()

    assert get_character("hackachu") is not None
    assert "modmon" not in CHAR_ID_TO_CID


def test_character_registry_rejects_invalid_custom_evolution_index():
    with pytest.raises(ValueError):
        set_evolution_index({})
    with pytest.raises(ValueError):
        set_evolution_index(None)


def test_achievements_and_care_catalogs_are_replaceable_and_validated():
    original_achievements = [dict(item) for item in get_achievement_catalog()]
    original_powers = {pid: dict(effect) for pid, effect in get_achievement_powers().items()}
    original_care = copy.deepcopy(get_care_catalog())
    original_first_id = original_achievements[0]["id"] if original_achievements else None

    custom_achievements = [{"id": "mod_badge", "name": "Mod Badge", "desc": "Custom", "action": "info"}]
    custom_powers = {
        "mod_power": {
            "id": "mod_power",
            "name": "Mod Power",
            "duration_ms": 1000,
            "cooldown_ms": 5000,
            "atk_delta": 2,
        }
    }
    custom_care = {
        "activity": [{"id": "meditate", "name": "Meditate"}],
        "food": [{"id": "snack", "name": "Snack"}],
    }

    try:
        if original_first_id:
            assert get_achievement_catalog()[0]["id"] == original_first_id
        set_achievement_catalog(custom_achievements, custom_powers)
        set_care_catalog(custom_care)
        assert get_achievement_catalog()[0]["id"] == "mod_badge"
        assert "mod_power" in get_achievement_powers()
        assert get_care_catalog()["activity"][0]["id"] == "meditate"

        with pytest.raises(ValueError):
            set_achievement_catalog([{"id": "dup"}, {"id": "dup"}], None)
        with pytest.raises(TypeError):
            set_care_catalog({"activity": "bad", "food": []})
    finally:
        set_achievement_catalog(original_achievements, original_powers)
        set_care_catalog(original_care)


def test_station_registry_override_and_default_fallback_work():
    custom_station = Station(
        "mod_station",
        "Mod Arena",
        character_id="hacktarmon",
        difficulty=DIFFICULTY_HARD,
    )
    fallback_station = Station("fallback", "Fallback", character_id="hacktarmon")

    try:
        set_station_definitions([custom_station], default_station=fallback_station)
        assert get_station("mod_station").name == "Mod Arena"
        assert get_station("missing").id == "fallback"
        assert get_station_character_ids() == ["hacktarmon"]
    finally:
        reset_station_registry()

    assert get_station_registry().get("enigmox_gym") is not None


def test_station_registry_rejects_invalid_custom_station_definitions():
    with pytest.raises(TypeError):
        set_station_definitions(["not-a-station"])
    with pytest.raises(ValueError):
        set_station_definitions([])
    with pytest.raises(TypeError):
        set_station_definitions([Station("ok", "OK", character_id="hacktarmon")], default_station="bad")


def test_battle_rules_factory_and_power_normalization_are_extensible():
    class CustomBattleRules(BattleRules):
        def normalize_power_effects(self, power_effects):
            if power_effects:
                return ["forced_custom_power"]
            return []

        def apply_power_modifiers(self, stats, power_effects):
            if "forced_custom_power" in power_effects:
                stats["attack"] += 42
                return {"atk_delta": 42}
            return {"atk_delta": 0}

    try:
        set_battle_rules_factory(CustomBattleRules)
        rules = create_battle_rules()
        assert isinstance(rules, CustomBattleRules)

        normalized = rules.normalize_power_effects(["focus", b"rage", "missing", b"\xff"])
        assert normalized == ["forced_custom_power"]

        stats = {"attack": 10, "defense": 10, "speed": 10}
        mods = rules.apply_power_modifiers(stats, normalized)
        assert mods["atk_delta"] == 42
        assert stats["attack"] == 52
    finally:
        reset_battle_rules_factory()
