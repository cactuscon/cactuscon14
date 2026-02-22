"""Behavior tests for battle-manager helper logic."""

from cactuscon.game import battle_manager as battle_manager_mod
from cactuscon.game.battle_manager import BattleManager, calculate_winner_by_hp_percent
from cactuscon.game.engine.battle_rules import BattleRules


class SpyRules:
    def __init__(self):
        self.calls = {
            "normalize_care_effects": 0,
            "normalize_power_effects": 0,
            "apply_care_modifiers": 0,
            "apply_power_modifiers": 0,
        }

    def normalize_care_effects(self, _effects):
        self.calls["normalize_care_effects"] += 1
        return []

    def normalize_power_effects(self, _effects):
        self.calls["normalize_power_effects"] += 1
        return []

    def apply_care_modifiers(self, _stats, _effects):
        self.calls["apply_care_modifiers"] += 1
        return {}

    def apply_power_modifiers(self, _stats, _effects):
        self.calls["apply_power_modifiers"] += 1
        return {}


class FakeGameBT:
    def __init__(self):
        self.callbacks = {}
        self.cancel_callback = None
        self.player_data_provider = None
        self.session = None

    def on_challenge_received(self, cb):
        self.callbacks["challenge"] = cb

    def on_battle_start(self, cb):
        self.callbacks["battle_start"] = cb

    def on_result_received(self, cb):
        self.callbacks["result"] = cb

    def on_error(self, cb):
        self.callbacks["error"] = cb

    def on_turn_order(self, cb):
        self.callbacks["turn_order"] = cb

    def on_turn_resolve(self, cb):
        self.callbacks["turn_resolve"] = cb

    def on_consensus(self, cb):
        self.callbacks["consensus"] = cb

    def on_battle_ready(self, cb):
        self.callbacks["battle_ready"] = cb

    def get_opponent_care_effects(self):
        return {"activity": None, "food": None}

    def get_opponent_power_effects(self):
        return []


def test_battle_manager_prefers_explicit_rules_over_default_factory(monkeypatch):
    monkeypatch.setattr(battle_manager_mod, "_load_achievements_class", lambda: None)
    monkeypatch.setattr(
        battle_manager_mod,
        "create_battle_rules",
        lambda: (_ for _ in ()).throw(AssertionError("default factory should not run")),
    )

    game_bt = FakeGameBT()
    explicit_rules = SpyRules()
    BattleManager(game_bt=game_bt, rules=explicit_rules, player_character_id="hackachu")

    assert explicit_rules.calls["normalize_care_effects"] >= 2
    assert explicit_rules.calls["normalize_power_effects"] >= 2
    assert explicit_rules.calls["apply_care_modifiers"] >= 2
    assert explicit_rules.calls["apply_power_modifiers"] >= 2
    assert callable(game_bt.cancel_callback)
    assert callable(game_bt.player_data_provider)
    assert set(game_bt.callbacks.keys()) == {
        "challenge",
        "battle_start",
        "result",
        "error",
        "turn_order",
        "turn_resolve",
        "consensus",
        "battle_ready",
    }

def test_battle_manager_uses_default_rules_when_rules_not_provided(monkeypatch):
    monkeypatch.setattr(battle_manager_mod, "_load_achievements_class", lambda: None)
    manager = BattleManager(game_bt=FakeGameBT(), rules=None, player_character_id="hackachu")
    assert isinstance(manager.rules, BattleRules)


def test_battle_manager_process_pending_ui_flushes_queued_actions(monkeypatch):
    manager = BattleManager.__new__(BattleManager)
    shown_challenges = []
    shown_panels = []
    delivered_logs = []
    manager.logger = type("L", (), {"debug": lambda *_a, **_k: None, "info": lambda *_a, **_k: None, "warning": lambda *_a, **_k: None})()
    monkeypatch.setattr(
        BattleManager,
        "_show_challenge_dialog",
        lambda self, name, addr: shown_challenges.append((name, addr)),
    )
    monkeypatch.setattr(BattleManager, "_show_inline_battle_result", lambda self, _result: None)
    manager.pending_challenge = ("peer", b"\x01\x02")
    manager.pending_battle_result = None
    manager.result_shown = False
    manager.pending_turn_logs = ["turn one", "turn two"]
    manager.pending_panel = "battle_screen"
    manager.pending_panel_data = {"unused": True}
    panel = type("Panel", (), {"add_battle_log": lambda self, msg: delivered_logs.append(msg)})()
    manager.game_ui = type(
        "UI",
        (),
        {
            "get_current_panel": lambda self: panel,
            "show_panel": lambda self, panel_name: shown_panels.append(panel_name),
        },
    )()

    manager._process_pending_ui()

    assert shown_challenges == [("peer", b"\x01\x02")]
    assert delivered_logs == ["turn one", "turn two"]
    assert shown_panels == ["battle_screen"]
    assert manager.pending_challenge is None
    assert manager.pending_turn_logs == []
    assert manager.pending_panel is None
    assert manager.pending_panel_data is None

def test_battle_manager_result_mapping_and_hp_tiebreak_logic():
    assert calculate_winner_by_hp_percent(70, 100, 100, 200) == 1
    assert calculate_winner_by_hp_percent(50, 100, 100, 200) == 0
    assert calculate_winner_by_hp_percent(10, 100, 150, 200) == 2

    manager = BattleManager.__new__(BattleManager)
    assert manager._map_remote_winner_to_local(0) == 0
    assert manager._map_remote_winner_to_local(1) == 2
    assert manager._map_remote_winner_to_local(2) == 1
