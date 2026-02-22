"""Battle management system - protocol bridge between BT comms, game rules, and UI."""

import time
try:
    import urandom as _random_mod
except Exception:
    import random as _random_mod

from cactuscon import config
from cactuscon.utils import Logger
from cactuscon.prefs import prefs, make_key, HANDLE_KEY, LEGACY_HANDLE_KEY
from cactuscon.game.engine.battle_rules import (
    BattleRules,
    create_battle_rules,
    BattleContext,
    BATTLE_CONTINUES,
    PLAYER_WINS,
    BATTLE_DRAW,
)
from cactuscon.game.engine.characters import (
    get_character,
    CharacterStats,
    get_care_state,
    add_creature_xp,
    acquire_creature,
    get_creature_stats,
    get_current_form_index,
    get_evolution_tree,
    get_genus_for_character,
    ACTIVE_CHAR_KEY,
    EVOLVE_REQUIRED_LEVEL,
)
from cactuscon.game.engine.moves import get_move
from cactuscon.game.engine.stations import get_station_registry
from cactuscon.game.engine.consensus import (
    ConsensusTracker,
    TurnOutcome,
)
from cactuscon.game.comms import (
    AVAILABILITY_OPEN,
    AVAILABILITY_IDLE,
    GameBTComms,
    ID_TO_CHARACTER,
    SESSION_CHALLENGING,
    SESSION_CHALLENGED,
    SESSION_HANDSHAKING,
    SESSION_EXCHANGING_DATA,
    SESSION_BATTLING,
    TURN_WAITING,
    READY_GRACE_TIMEOUT_MS,
    PLAYER_DATA_IS_STATION
)

def _load_achievements_class():
    """
    Lazy-load Achievements to avoid importing the module during boot when
    battles may never be used in this session.
    """
    try:
        from cactuscon.game.engine.achievements import Achievements as _Achievements

        return _Achievements
    except Exception:
        return None

# Short NVS keys for player stats (<=15 chars)
KEY_XP = make_key("pl", "xp")
KEY_LVL = make_key("pl", "lvl")
KEY_WINS = make_key("pl", "win")
KEY_LOSSES = make_key("pl", "loss")


def calculate_winner_by_hp_percent(our_hp, our_max_hp, opponent_hp, opponent_max_hp):
    """
    Calculate battle winner based on HP percentage remaining.

    Higher HP percentage wins. This prevents gaming by having a tanky character
    with high HP - a character with 70/100 HP (70%) beats one with 100/200 HP (50%).

    Args:
        our_hp: Our current HP
        our_max_hp: Our maximum HP
        opponent_hp: Opponent's current HP
        opponent_max_hp: Opponent's maximum HP

    Returns:
        int: 0=draw, 1=we win, 2=opponent wins
    """
    # Avoid division by zero
    our_max = our_max_hp if our_max_hp > 0 else 1
    opp_max = opponent_max_hp if opponent_max_hp > 0 else 1

    our_percent = (our_hp / our_max) * 100
    opp_percent = (opponent_hp / opp_max) * 100

    # Use small epsilon for floating point comparison
    if abs(our_percent - opp_percent) < 0.01:
        return 0  # Draw
    elif our_percent > opp_percent:
        return 1  # We win
    else:
        return 2  # Opponent wins


class BattleManager:
    """
    High-level battle manager for badge-to-badge battles.

    Coordinates between the Bluetooth protocol layer and the UI layer,
    managing battle state, player stats, and game logic.

    ARCHITECTURE:
    - BattleManager OWNS battle-related UI transitions
    - GameUI reference is set via set_game_ui() after both are initialized
    - UI transitions are DEFERRED via pending_panel to avoid recursion in BLE callbacks
    - The main loop calls update() which processes pending UI changes

    Usage:
        # Create battle manager
        battle_mgr = BattleManager(game_bt_comms, screen, logger_level=20)

        # Wire up UI after GameUI is created
        battle_mgr.set_game_ui(game_ui)

        # In main loop
        battle_mgr.update()  # Processes pending UI transitions

        # Start battle from UI
        battle_mgr.start_opponent_scan()
        opponents = battle_mgr.get_opponents()
        battle_mgr.challenge_opponent(opponents[0])
    """

    __slots__ = (
        "logger",
        "game_bt",
        "screen",
        "headless",
        "game_ui",
        "battle_timeout_ms",
        "battle_start_time",
        "pending_panel",
        "pending_panel_data",
        "pending_challenge",
        "rules",
        "player_character_id",
        "player_character",
        "opponent_character",
        "is_station_battle",
        "station_ui_shim",
        "achievements",
        "in_battle",
        "current_session",
        "battle_context",
        "consensus_tracker",
        "scanning",
        "last_scan_results",
        "player_stats",
        "player_hp",
        "player_max_hp",
        "player_status",
        "player_moves",
        "opponent_stats",
        "opponent_hp",
        "opponent_max_hp",
        "opponent_status",
        "player_care_effects",
        "player_power_effects",
        "opponent_care_effects",
        "opponent_power_effects",
        "player_care_mods",
        "player_power_mods",
        "opponent_care_mods",
        "opponent_power_mods",
        "opponent_moves",
        "is_challenger",
        "attacker_stats",
        "defender_stats",
        "attacker_moves",
        "defender_moves",
        "last_battle_result",
        "pending_battle_result",
        "pending_remote_result",
        "last_error",
        "waiting_for_opponent",
        "_waiting_since_ms",
        "_waiting_turn_number",
        "matchmaking_enabled",
        "pending_turn_logs",
        "result_shown",
        "local_ready",
        "remote_ready",
        "ready_handshake_complete",
        "ready_sent_ts",
        "last_ready_resend_ts",
    )

    def __init__(
        self,
        game_bt,
        screen=None,
        rules=None,
        player_character_id=None,
        battle_timeout_ms=None,
        logger_level=20,
    ):
        """
        Initialize battle manager.

        Args:
            game_bt: GameBTComms instance for Bluetooth protocol
            screen: Screen instance for UI updates (optional)
            rules: BattleRules instance for game mechanics (optional)
            player_character_id: Player's character ID (MUST be set, no fallback)
            battle_timeout_ms: Optional battle timeout in ms (None=no timeout, for stations use 10000-30000)
            logger_level: Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR)
        """
        self.logger = Logger(logger_level)
        self.game_bt: GameBTComms = game_bt
        self.screen = screen
        self.headless = getattr(config, "AUTO_BATTLE_MODE", False)

        # UI reference - set via set_game_ui() after initialization
        self.game_ui = None

        # Battle timeout (for station mode - auto-ends battle after duration)
        self.battle_timeout_ms = battle_timeout_ms
        self.battle_start_time = 0

        # Pending UI state - processed in update() to avoid recursion in BLE callbacks
        self.pending_panel = None
        self.pending_panel_data = None
        self.pending_challenge = None  # (opponent_name, opponent_addr) tuple

        # Battle rules engine
        self.rules = rules if rules else create_battle_rules()

        # Player character (must be set, never fallback to hacktarmon)
        if not player_character_id:
            self.logger.error(
                "No player_character_id provided to BattleManager! This is a fatal error."
            )
            raise ValueError("player_character_id must be set and non-empty!")
        self.player_character_id = player_character_id
        self.player_character = get_character(self.player_character_id)
        self.opponent_character = None
        self.is_station_battle = False  # True if opponent is a station, triggers creature rewards
        # Local-only station display/reward shim (non-consensus):
        # - Changes what the player sees in battle UI
        # - Changes which creature gets awarded after a station win
        # - Does NOT alter any protocol/consensus inputs
        self.station_ui_shim = None
        if not self.player_character:
            self.logger.error(
                f"Character '{self.player_character_id}' not found! This is a fatal error."
            )
            raise ValueError(f"Character '{self.player_character_id}' not found!")

        # Achievements handler (global prefs by default); disable in headless/station mode or when module unavailable
        achievements_cls = _load_achievements_class() if not self.headless else None
        self.achievements = achievements_cls() if achievements_cls else None

        # Battle state
        self.in_battle = False
        self.current_session = None
        self.battle_context = None  # BattleContext for current battle
        self.consensus_tracker = None  # ConsensusTracker for networked battles
        self.scanning = False
        self.last_scan_results = []

        # Player battle stats (initialized from character on battle start)
        if self.player_character:
            self.player_stats = self.player_character.get_battle_stats()
        else:
            self.player_stats = CharacterStats()
        self.player_hp = self.player_stats.hp
        self.player_max_hp = self.player_stats.max_hp
        self.player_status = 0  # Status effect bitmask
        self.player_moves = (
            self.player_character.moves if self.player_character else [0, 1, 2, 3]
        )

        # Opponent battle stats (set when battle starts)
        self.opponent_stats = CharacterStats()
        self.opponent_hp = self.opponent_stats.hp
        self.opponent_max_hp = self.opponent_stats.max_hp
        self.opponent_status = 0

        # Apply care modifiers (activity/food) to battle stats before consensus setup
        self.player_care_effects = self.rules.normalize_care_effects(
            self._load_local_care_effects()
        )
        self.player_power_effects = self.rules.normalize_power_effects(
            self._load_local_power_effects()
        )
        self.opponent_care_effects = self.rules.normalize_care_effects(
            self._load_opponent_care_effects()
        )
        self.opponent_power_effects = self.rules.normalize_power_effects(
            self._load_opponent_power_effects()
        )
        self.player_care_mods = self.rules.apply_care_modifiers(
            self.player_stats, self.player_care_effects
        )
        self.player_power_mods = self.rules.apply_power_modifiers(
            self.player_stats, self.player_power_effects
        )
        self.opponent_care_mods = self.rules.apply_care_modifiers(
            self.opponent_stats, self.opponent_care_effects
        )
        self.opponent_power_mods = self.rules.apply_power_modifiers(
            self.opponent_stats, self.opponent_power_effects
        )
        self.opponent_moves = [0, 1, 2, 3]

        # Canonical stats for consensus (set in _on_battle_start)
        self.is_challenger = True
        self.attacker_stats = None
        self.defender_stats = None
        self.attacker_moves = []
        self.defender_moves = []
        self.player_care_effects = None
        self.opponent_care_effects = None
        self.player_power_effects = None
        self.opponent_power_effects = None
        self.player_care_mods = None
        self.opponent_care_mods = None
        self.player_power_mods = None
        self.opponent_power_mods = None

        # Battle result data (set before showing result panel)
        self.last_battle_result = None  # {'winner': int, 'exp_gained': int, ...}
        self.pending_battle_result = (
            None  # Set to trigger inline result display on battle screen
        )
        self.pending_remote_result = (
            None  # Remote result received before local completion
        )
        self.last_error = None  # Last error message
        self.waiting_for_opponent = (
            False  # True after we select move, waiting for opponent
        )
        # Wall-clock watchdog for "waiting for opponent" state (turn progress).
        self._waiting_since_ms = None
        self._waiting_turn_number = None
        # Track desired matchmaking state so we can re-enter after scans
        self.matchmaking_enabled = False
        self.pending_turn_logs = []  # Turn summary messages to show on UI
        self.result_shown = False  # Prevent duplicate result display
        self.local_ready = False  # UI/assets loaded locally
        self.remote_ready = False  # Peer has signaled ready
        self.ready_handshake_complete = False
        self.ready_sent_ts = None  # ticks_ms when we sent READY
        self.last_ready_resend_ts = None
        # Wall-clock watchdog for "waiting for opponent" state. This is separate from
        # protocol inactivity timeouts so we can still recover if keepalives continue
        # but the peer is no longer progressing the battle.
        self._waiting_since_ms = None

        # Register callbacks with GameBTComms
        self.game_bt.on_challenge_received(self._on_challenge_received)
        self.game_bt.on_battle_start(self._on_battle_start)
        # NOTE: Do NOT register on_move_received - it's legacy and conflicts with consensus!
        # The turn-based protocol (on_turn_resolve) handles all move execution with proper RNG.
        self.game_bt.on_result_received(self._on_result_received)
        self.game_bt.on_error(self._on_error)
        self.game_bt.cancel_callback = self._on_bt_cancel

        # Register turn-based callbacks (these are the primary flow now)
        self.game_bt.on_turn_order(self._determine_turn_order)
        self.game_bt.on_turn_resolve(self._on_turn_resolve)

        # Register consensus callback
        self.game_bt.on_consensus(self._on_consensus_result)

        # Register player data provider - comms will call this to get current player data
        self.game_bt.player_data_provider = self._get_player_data
        # Register ready callback to gate timers until both UIs are ready
        self.game_bt.on_battle_ready(self._on_peer_ready)

        self.logger.info("BattleManager initialized")

    # =========================================================================
    # Dependency Injection
    # =========================================================================

    def set_game_ui(self, game_ui):
        """
        Set the GameUI reference for UI transitions.

        Call this after GameUI is created to enable panel switching.

        Args:
            game_ui: GameUI instance
        """
        self.game_ui = game_ui
        self.logger.info("GameUI reference set")

    # =========================================================================
    # Callback Handlers (registered with GameBTComms)
    # =========================================================================

    def _on_bt_cancel(self, reason=""):
        """
        BLE/comms signaled a cancel (decline/timeout/error) - reset UI spinners.
        """
        if self.game_ui:
            panel = self.game_ui.get_current_panel()
            if panel and hasattr(panel, "cancel_pending_action"):
                try:
                    panel.cancel_pending_action()
                except Exception as e:
                    self.logger.debug(f"cancel_pending_action failed: {e}")

    def set_active_character(self, char_id):
        """
        Update the active character for battles.

        Call this when the player switches creatures in their pack.
        Cannot be called during an active battle.

        Args:
            char_id: Character ID to switch to.

        Returns:
            bool: True if switch succeeded, False otherwise.
        """
        if self.in_battle:
            self.logger.warning("Cannot switch character during battle!")
            return False

        if not char_id:
            self.logger.error("Cannot set empty character_id!")
            return False

        new_character = get_character(char_id)
        if not new_character:
            self.logger.error(f"Character '{char_id}' not found!")
            return False

        old_id = self.player_character_id
        self.player_character_id = char_id
        self.player_character = new_character

        # Update player stats from new character
        self.player_stats = self.player_character.get_battle_stats()
        self.player_hp = self.player_stats.hp
        self.player_max_hp = self.player_stats.max_hp
        self.player_moves = list(self.player_character.moves)

        # Reload care effects for the new character
        self.player_care_effects = self.rules.normalize_care_effects(
            self._load_local_care_effects()
        )
        self.player_care_mods = self.rules.apply_care_modifiers(
            self.player_stats, self.player_care_effects
        )

        self.logger.info(f"Switched character: {old_id} -> {char_id}")
        return True

    def _process_pending_ui(self):
        """
        Process any pending UI transitions.

        This is called from update() to handle panel switches that were
        requested from BLE callbacks. By deferring to the main loop, we
        avoid deep recursion that exceeds MicroPython's stack limits.
        """
        if self.pending_challenge or self.pending_battle_result or self.pending_panel:
            self.logger.debug(
                f"[BM] _process_pending_ui() called. pending_panel={self.pending_panel}, pending_battle_result={self.pending_battle_result}, pending_challenge={self.pending_challenge}"
            )

        # Handle pending challenge dialog
        if self.pending_challenge:
            name, addr = self.pending_challenge
            self.pending_challenge = None
            self._show_challenge_dialog(name, addr)

        # Deliver pending turn logs to current panel (battle screen)
        if self.pending_turn_logs and self.game_ui:
            current_panel = self.game_ui.get_current_panel()
            if current_panel and hasattr(current_panel, "add_battle_log"):
                while self.pending_turn_logs:
                    try:
                        msg = self.pending_turn_logs.pop(0)
                        current_panel.add_battle_log(msg)
                    except Exception as e:
                        self.logger.debug(f"Failed to deliver turn log: {e}")
                        break

        # Handle pending battle result (show inline on battle screen)
        if self.pending_battle_result and not self.result_shown:
            result = self.pending_battle_result
            self.pending_battle_result = None
            self._show_inline_battle_result(result)
            self.result_shown = True

        # Handle pending panel switch
        if self.pending_panel:
            panel_name = self.pending_panel
            panel_data = self.pending_panel_data
            self.pending_panel = None
            self.pending_panel_data = None

            if self.game_ui:
                self.logger.info(f"Showing panel: {panel_name}")
                self.game_ui.show_panel(panel_name)
            else:
                self.logger.warning(f"Cannot show panel {panel_name} - no game_ui")

    def _show_inline_battle_result(self, result):
        """
        Show battle result inline on the battle screen.

        Args:
            result: Dict with 'winner', 'exp_gained', 'voided', 'error', etc.
        """
        if not self.game_ui:
            self.logger.warning("Cannot show battle result - no game_ui")
            return

        # Get current panel - should be battle_screen
        current_panel = self.game_ui.get_current_panel()
        if current_panel and hasattr(current_panel, "on_battle_end"):
            winner = result.get("winner", 0)
            current_panel.on_battle_end(winner, result)
            self.logger.info(f"Showed inline battle result: winner={winner}")
        else:
            # Fallback: switch to battle_result panel
            self.logger.warning(
                "Current panel doesn't support inline results - using battle_result panel"
            )
            self.pending_panel = "battle_result"

    def _check_battle_timeout(self):
        """
        Check if battle has exceeded timeout duration and end it if so.

        Only applies if battle_timeout_ms is set (for station mode).
        Determines winner by HP percentage when timeout occurs.
        """
        # Skip if no timeout configured or not in battle
        if not self.battle_timeout_ms or not self.in_battle:
            return

        # Check elapsed time
        elapsed = time.ticks_diff(time.ticks_ms(), self.battle_start_time)
        if elapsed < self.battle_timeout_ms:
            return

        # Timeout - determine winner by HP percentage
        winner = calculate_winner_by_hp_percent(
            self.player_hp, self.player_max_hp, self.opponent_hp, self.opponent_max_hp
        )

        player_pct = (self.player_hp / max(self.player_max_hp, 1)) * 100
        opp_pct = (self.opponent_hp / max(self.opponent_max_hp, 1)) * 100
        self.logger.info(
            f"Battle timeout ({elapsed}ms) - winner={winner} "
            f"(us:{player_pct:.1f}% vs opp:{opp_pct:.1f}%)"
        )

        # Send result and end battle
        if self.game_bt:
            self.game_bt.send_battle_result(winner=winner)

        # Update stats
        self._update_player_stats(winner)
        # Add timeout flag
        if self.last_battle_result is not None:
            self.last_battle_result["timeout"] = True

        # Show result inline on battle screen
        self.pending_battle_result = self.last_battle_result
        self.in_battle = False
        self.in_battle = False

    def _compute_effective_turn_timeout_ms(self):
        """
        Clamp turn timer to remaining inactivity window (40s watchdog).
        """
        from cactuscon import config as cfg

        default_turn = getattr(cfg, "BATTLE_MOVE_TIMEOUT_MS", 30000)
        inactivity_window = getattr(cfg, "BATTLE_INACTIVITY_TIMEOUT_MS", 40000)

        if not self.ready_sent_ts:
            return default_turn

        elapsed = time.ticks_diff(time.ticks_ms(), self.ready_sent_ts)
        remaining = max(0, inactivity_window - elapsed)

        return min(default_turn, remaining)

    def mark_ui_ready(self):
        """
        Signal that our UI/assets are ready; sends READY packet and gates timers until peer also ready.
        """
        if self.local_ready:
            return
        self.local_ready = True
        now = time.ticks_ms()
        self.ready_sent_ts = now
        self.last_ready_resend_ts = now
        if self.game_bt:
            sent = self.game_bt.send_battle_ready()
            if not sent:
                self.logger.debug("mark_ui_ready: send_battle_ready returned False")
        self._maybe_begin_battle_turns()

    def _on_peer_ready(self):
        """Handle peer READY packet."""
        self.remote_ready = True
        self.logger.info("Peer marked ready")
        # Stop grace disconnect once both sides are ready
        if self.game_bt and self.game_bt.session:
            self.game_bt.session.disconnect_grace_until = 0
        self._maybe_begin_battle_turns()

    def _maybe_begin_battle_turns(self):
        """
        Start turn timers/UI once both sides reported ready.
        Keeps inactivity watchdog (40s) but delays 30s turn timers until ready.
        """
        if not self.in_battle:
            self.logger.debug("ready_handshake: not in battle")
            return
        if self.last_battle_result or self.pending_battle_result:
            self.logger.debug("ready_handshake: result already present, skipping start")
            return
        if self.ready_handshake_complete:
            return
        if not (self.local_ready and self.remote_ready):
            self.logger.debug(
                f"ready_handshake: waiting local_ready={self.local_ready} remote_ready={self.remote_ready}"
            )
            return
        self.ready_handshake_complete = True
        # Stop ready resends once handshake is done
        self.ready_sent_ts = None
        self.last_ready_resend_ts = None

        # If panel is active, start player turn UI
        if self.game_ui:
            panel = self.game_ui.get_current_panel()
            if panel and hasattr(panel, "start_turn"):
                try:
                    panel.start_turn(self._compute_effective_turn_timeout_ms())
                except Exception as e:
                    self.logger.error(f"Failed to start turn UI: {e}")

        # Reset wait flags for first turn
        self.waiting_for_opponent = False

    def _handle_error(self, message, code=0):
        """
        Handle protocol/battle errors gracefully (especially in headless mode).

        Args:
            message: Error description.
            code: Optional error code from protocol layer.
        """
        self.logger.error(f"[BM] Error: {message} (code={code})")
        self.last_error = message
        self.waiting_for_opponent = False

        # Void active battle so we can recover cleanly; otherwise just reset state.
        if self.in_battle:
            self._void_battle(message)
        else:
            self.end_battle()

    def _ensure_ready_progress(self):
        """
        Prevent deadlock if peer ready is lost; start after short grace period.
        """
        if not self.in_battle:
            return
        if self.ready_handshake_complete:
            return
        if not self.ready_sent_ts:
            return
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.ready_sent_ts)

        # If peer never sent READY within grace, abort cleanly
        if elapsed > READY_GRACE_TIMEOUT_MS:
            self.logger.warning("Ready handshake timeout - aborting battle start")
            self._handle_error("Ready handshake timeout")
            return

        # Retry READY every 3s while waiting
        if self.game_bt:
            if (self.last_ready_resend_ts is None) or (
                time.ticks_diff(now, self.last_ready_resend_ts) >= 3000
            ):
                self.game_bt.send_battle_ready(force=True)
                self.last_ready_resend_ts = now

        # If peer hasn't responded within 10s, treat as draw/void to avoid a stuck UI
        if elapsed >= 18000:
            self.logger.error(
                "Ready handshake timed out after 10s - voiding battle as draw"
            )
            self._void_battle("Ready handshake timeout")

    def _show_challenge_dialog(self, opponent_name, opponent_addr):
        """
        Show challenge accept/decline dialog on matchmaking panel.

        Args:
            opponent_name: Attacker's display name
            opponent_addr: Attacker's BLE address
        """
        if not self.game_ui:
            # No UI - auto-accept
            self.logger.info(f"Auto-accepting challenge from {opponent_name} (no UI)")
            self.accept_challenge(opponent_addr)
            return

        # Check if matchmaking panel is visible
        if "battle_matchmaking" in self.game_ui.panel_instances:
            panel = self.game_ui.panel_instances["battle_matchmaking"]
            if panel.visible and hasattr(panel, "show_challenge_dialog"):
                panel.show_challenge_dialog(opponent_name, opponent_addr)
                return

        # Not on matchmaking screen - auto-accept
        self.logger.info(
            f"Auto-accepting challenge from {opponent_name} (not on matchmaking)"
        )
        self.accept_challenge(opponent_addr)

    # Internal callback handlers (called by GameBTComms)
    # These set pending state - actual UI transitions happen in update()

    def _on_challenge_received(self, opponent_addr, opponent_name):
        """
        Handle incoming challenge from another badge.

        DEFERS UI to update() to avoid recursion in BLE callback stack.

        Args:
            opponent_addr: Attacker's BLE address
            opponent_name: Attacker's display name
        """
        self.logger.info(f"Challenge received from {opponent_name}")
        # Defer to main loop - will be processed in update() -> _process_pending_ui()
        self.pending_challenge = (opponent_name, opponent_addr)

    def _on_battle_start(self, session):
        """
        Handle battle session start.

        Initializes battle state including ConsensusTracker for
        networked battle verification.

        Args:
            session: BattleSession object
        """
        self.logger.info(f"Battle started with {session.opponent_name}!")

        # Reset all battle state before starting a new battle
        self._reset_battle_stats()
        self.in_battle = True
        self.pending_turn_logs = []
        self.result_shown = False
        self.current_session = session
        self.battle_start_time = time.ticks_ms()  # For timeout tracking
        self.opponent_character = None
        self.station_ui_shim = None
        self.local_ready = False
        self.remote_ready = False
        self.ready_handshake_complete = False

        # Initialize consensus tracker with session token
        if session.session_token:
            self.consensus_tracker = ConsensusTracker(session.session_token)
            self.logger.info("Consensus tracker initialized")
        else:
            self.consensus_tracker = None
            self.logger.warning("No session token - consensus disabled")

        # Initialize player stats from character
        if self.player_character:
            self.player_stats = self.player_character.get_battle_stats()
            self.player_moves = list(self.player_character.moves)
            # Get player's level from stored creature stats
            player_creature_stats = get_creature_stats(prefs, self.player_character_id)
            self.player_stats.level = player_creature_stats.get('level', 1)
        else:
            self.player_stats = CharacterStats()
            self.player_stats.level = 1
            self.player_moves = [0, 1, 2, 3]

        self.player_hp = self.player_stats.hp
        self.player_max_hp = self.player_stats.max_hp
        self.player_status = 0

        # Initialize opponent stats from exchanged player data
        opponent_char_id = self.game_bt.get_opponent_character_id()
        opponent_char_str = ID_TO_CHARACTER.get(opponent_char_id)
        if not opponent_char_str:
            raise ValueError(f"Unknown opponent character ID: {opponent_char_id}")
        opponent_char = get_character(opponent_char_str)
        if not opponent_char:
            raise ValueError(
                f"Opponent character lookup failed for id={opponent_char_id} ({opponent_char_str})"
            )

        self.opponent_character = opponent_char
        self.opponent_stats = opponent_char.get_battle_stats()
        # Set opponent's level from exchanged player data
        opponent_level = self.game_bt.get_opponent_level()
        self.opponent_stats.level = opponent_level
        self.opponent_moves = list(opponent_char.moves)
        
        opponent_player_data = self.current_session.opponent_player_data if self.current_session else {}
        is_station_flag = opponent_player_data.get(PLAYER_DATA_IS_STATION, 0)
        self.is_station_battle = is_station_flag == 1
        self.logger.info(f"[STATION-CHECK] opponent_player_data keys={list(opponent_player_data.keys())}, IS_STATION flag={is_station_flag}, is_station_battle={self.is_station_battle}")
        if self.is_station_battle:
            # Pick a per-battle local shim identity for station visuals/reward.
            # Underlying opponent_character/stats remain unchanged for consensus.
            self.station_ui_shim = self._select_station_ui_shim()
            if self.station_ui_shim:
                self.logger.info(
                    f"[STATION-SHIM] station='{self.station_ui_shim.get('station_name')}', "
                    f"creature='{self.station_ui_shim.get('character_id')}'"
                )

        self.logger.info(
            f"Opponent character: {opponent_char.name} (id={opponent_char_id}) Lv.{opponent_level}{'[STATION]' if self.is_station_battle else ''}"
        )

        self.opponent_hp = self.opponent_stats.hp
        self.opponent_max_hp = self.opponent_stats.max_hp
        self.opponent_status = 0

        # Apply care and achievement power modifiers now that stats are loaded
        self.player_care_effects = self.rules.normalize_care_effects(
            self._load_local_care_effects()
        )
        self.player_power_effects = self.rules.normalize_power_effects(
            self._load_local_power_effects()
        )
        self.player_care_mods = self.rules.apply_care_modifiers(
            self.player_stats, self.player_care_effects
        )
        self.player_power_mods = self.rules.apply_power_modifiers(
            self.player_stats, self.player_power_effects
        )

        self.opponent_care_effects = self.rules.normalize_care_effects(
            self._load_opponent_care_effects()
        )
        self.opponent_power_effects = self.rules.normalize_power_effects(
            self._load_opponent_power_effects()
        )
        self.opponent_care_mods = self.rules.apply_care_modifiers(
            self.opponent_stats, self.opponent_care_effects
        )
        self.opponent_power_mods = self.rules.apply_power_modifiers(
            self.opponent_stats, self.opponent_power_effects
        )

        # CANONICAL STATS for consensus: Both devices must compute from same perspective
        # Attacker = the one who sent the challenge (is_challenger=True on that device)
        # We determine which role we have from session.is_challenger
        self.is_challenger = session.is_challenger if session else True

        if self.is_challenger:
            # We are attacker: our stats = attacker stats
            self.attacker_stats = self.player_stats
            self.defender_stats = self.opponent_stats
            self.attacker_moves = self.player_moves
            self.defender_moves = self.opponent_moves
        else:
            # We are defender: our stats = defender stats
            self.attacker_stats = self.opponent_stats
            self.defender_stats = self.player_stats
            self.attacker_moves = self.opponent_moves
            self.defender_moves = self.player_moves

        # === BATTLE START DEBUG INFO ===
        # Print comprehensive info to trace character/consensus issues
        self.logger.info(f"[BATTLE] ========== BATTLE START ==========")
        self.logger.info(
            f"[BATTLE] Our role: {'ATTACKER (initiated)' if self.is_challenger else 'DEFENDER (received)'}"
        )
        self.logger.info(
            f"[BATTLE] Our character: {self.player_character.name if self.player_character else 'UNKNOWN'} (id={self.player_character_id})"
        )
        self.logger.info(
            f"[BATTLE]   HP={self.player_stats.hp}, ATK={self.player_stats.attack}, DEF={self.player_stats.defense}, SPD={self.player_stats.speed}"
        )
        self.logger.info(
            f"[BATTLE] Opponent character: {opponent_char.name if opponent_char else 'UNKNOWN'} (id={opponent_char_id})"
        )
        self.logger.info(
            f"[BATTLE]   HP={self.opponent_stats.hp}, ATK={self.opponent_stats.attack}, DEF={self.opponent_stats.defense}, SPD={self.opponent_stats.speed}"
        )
        self.logger.info(
            f"[BATTLE] Canonical: attacker_hp={self.attacker_stats.hp}, defender_hp={self.defender_stats.hp}"
        )
        self.logger.info(
            f"[BATTLE] Canonical speeds: attacker_spd={self.attacker_stats.speed}, defender_spd={self.defender_stats.speed}"
        )
        self.logger.info(f"[BATTLE] ======================================")

        self.logger.debug(f"Canonical setup: is_challenger={self.is_challenger}")
        self.logger.debug(
            f"  Attacker HP: {self.attacker_stats.hp}, Defender HP: {self.defender_stats.hp}"
        )

        # Create battle context
        self.battle_context = BattleContext(self.player_character, opponent_char)

        # Notify rules of battle start
        self.rules.on_battle_start(
            self.player_stats.to_dict(), self.opponent_stats.to_dict()
        )

        # DEFER battle screen switch to main loop (avoids recursion in BLE stack)
        self.pending_panel = "battle_screen"
        self.logger.info("Battle start - pending panel switch to battle_screen")

        # Send initial status to opponent
        if self.game_bt:
            self.game_bt.send_status(self.player_hp, self.player_status)

        # Headless/auto modes still need to signal readiness
        if not self.game_ui or config.AUTO_BATTLE_MODE:
            self.mark_ui_ready()

    def _on_result_received(self, winner, result_data):
        """
        Handle battle result.

        Stores result and defers panel switch to main loop.

        CRITICAL: Enforces consensus by verifying against local result.

        Args:
            winner: 0=draw, 1=player, 2=opponent
            result_data: Additional result data
        """
        self.logger.info(f"Battle result received: winner={winner}")
        # Winner in packet is from sender's perspective; translate to our perspective
        local_winner_from_remote = self._map_remote_winner_to_local(winner)

        # If consensus tracker still has an uncommitted outcome, defer handling.
        if (
            self.consensus_tracker
            and self.consensus_tracker.pending_outcome is not None
        ):
            self.logger.warning(
                "Received battle result before consensus commit; deferring until consensus completes."
            )
            self.pending_remote_result = (local_winner_from_remote, result_data)
            return

        # Check if we have a local result to compare against
        if self.last_battle_result:
            local_winner = self.last_battle_result.get("winner")
            if local_winner != local_winner_from_remote:
                self.logger.error(
                    f"CONSENSUS FAILURE: Local winner={local_winner} != Remote (translated) winner={local_winner_from_remote} (raw={winner})"
                )
                self._void_battle("Result consensus mismatch")
                return
            else:
                self.logger.info("Result consensus verified")
        else:
            # We haven't finished the battle locally yet. Cache and verify later.
            self.logger.warning(
                "Received result before local completion - caching for later verification."
            )
            self.pending_remote_result = (local_winner_from_remote, result_data)
            return

        if local_winner_from_remote == 0:
            result_msg = "DRAW"
        elif local_winner_from_remote == 1:
            result_msg = "WE WON!"
        elif local_winner_from_remote == 2:
            result_msg = "WE LOST"
        else:
            result_msg = f"Unknown result ({local_winner_from_remote})"

        self.logger.info(f"   Result: {result_msg}")

        # Use our LOCAL result data (trusted), ignore remote result_data
        # self.last_battle_result is already set by _on_turn_resolve

        # Show result inline on battle screen (deferred to main loop)
        if not self.result_shown:
            self.pending_battle_result = self.last_battle_result
        # We're done waiting for opponent/state updates
        self.waiting_for_opponent = False
        self.in_battle = False
        self.ready_handshake_complete = False

    def _process_pending_remote_result(self):
        """
        Verify any remote result that arrived before local completion.

        Called after we finish local resolution to avoid voiding battles
        when the opponent sends the result slightly earlier.
        """
        if not self.pending_remote_result or not self.last_battle_result:
            return

        winner, result_data = self.pending_remote_result
        self.pending_remote_result = None

        local_winner = self.last_battle_result.get("winner")
        if local_winner != winner:
            self.logger.error(
                f"CONSENSUS FAILURE: Cached remote winner={winner} != Local winner={local_winner}"
            )
            self._void_battle("Result consensus mismatch (delayed)")
            return

        self.logger.info("Cached remote result matches local outcome")

    def _map_remote_winner_to_local(self, remote_winner):
        """
        Convert opponent-perspective winner code to our local perspective.

        Args:
            remote_winner: Winner value from MSG_BATTLE_RESULT (0=draw, 1=sender wins, 2=sender loses)

        Returns:
            int: Winner from our perspective (0=draw, 1=we win, 2=opponent wins)
        """
        if remote_winner == 0:
            return 0
        elif remote_winner == 1:
            # Sender says they won -> we lost
            return 2
        elif remote_winner == 2:
            # Sender says we won
            return 1
        return remote_winner

    def _update_player_stats(self, winner):
        """
        Update player stats (XP, wins/losses) based on battle result.

        Uses per-creature XP tracking - XP is awarded to the active creature,
        not globally to the player.

        Args:
            winner: 0=draw, 1=we win, 2=opponent wins
        """
        # Calculate XP via battle rules (single source of truth)
        turn_count = None
        if self.current_session:
            turn_count = self.current_session.turn_number
        # End-of-battle HP snapshots to feed XP formula
        player_end_hp = max(0, self.player_hp)
        opponent_end_hp = max(0, self.opponent_hp)
        result = self.rules.on_battle_end(
            winner,
            self.player_stats.to_dict(),
            self.opponent_stats.to_dict(),
            turn_count=turn_count,
            battle_log=(
                self.battle_context.battle_log if self.battle_context else None
            ),
            player_care_effects=self.player_care_effects,
            player_power_effects=self.player_power_effects,
        )
        xp_gained = result.get("xp_gained", 0)
        xp_base = result.get("xp_gained_base", xp_gained)
        xp_boost_pct = result.get("xp_boost_pct", 0)

        # Get creature ID for per-creature tracking
        creature_id = self.player_character_id

        # Check current level - cannot gain XP at level 5 (max level)
        current_stats = get_creature_stats(prefs, creature_id)
        current_level = current_stats.get('level', 1)
        
        # If already at max level, don't award XP
        if current_level >= EVOLVE_REQUIRED_LEVEL:
            xp_gained = 0
            self.logger.info(f"{creature_id} is at max level ({current_level}) - no XP awarded")

        # Add XP to the specific creature (per-creature tracking)
        xp_result = add_creature_xp(prefs, creature_id, xp_gained)
        current_level = xp_result["old_level"]
        new_level = xp_result["new_level"]
        new_xp = xp_result["new_xp"]
        leveled_up = xp_result["leveled_up"]
        can_evolve = xp_result["can_evolve"]

        # Log detailed XP computation for diagnostics
        self.logger.info(
            f"XP calc: base={xp_base}, boost_pct={xp_boost_pct}, gained={xp_gained}, "
            f"old_xp={xp_result.get('old_xp')}, new_xp={new_xp}"
        )

        # Refresh cached stats for UI to reflect updated XP/level
        try:
            refreshed = get_creature_stats(prefs, creature_id)
            self.player_stats = self.player_character.get_battle_stats()
            self.player_max_hp = self.player_stats.max_hp
        except Exception as e:
            self.logger.debug(f"Failed to refresh creature stats after XP update: {e}")

        # Update win/loss counters (these remain global per-player)
        prefs.begin(write=True, context="battle_manager.update_player_stats")
        wins = prefs.get_int32(KEY_WINS, 0)
        losses = prefs.get_int32(KEY_LOSSES, 0)

        if winner == 1:
            wins += 1
        elif winner == 2:
            losses += 1

        prefs.set_int32(KEY_WINS, wins)
        prefs.set_int32(KEY_LOSSES, losses)
        # Write legacy keys for any callers still reading old locations
        prefs.set_int32("wins", wins)
        prefs.set_int32("losses", losses)
        prefs.set_int32("level", new_level)
        prefs.end()

        self.logger.info(
            f"Stats updated for {creature_id}: +{xp_gained} XP, "
            f"Level {current_level}->{new_level}, Wins: {wins}, Losses: {losses}"
        )
        if leveled_up:
            self.logger.info(f"LEVEL UP! {creature_id} is now level {new_level}")
        if can_evolve:
            self.logger.info(f"{creature_id} is ready to evolve!")

        # Determine current evolution stage to gate evolution prompts (stage 0/1 only)
        try:
            current_stage = get_current_form_index(prefs, creature_id)
        except Exception:
            current_stage = 0
        can_evolve_now = bool(can_evolve and current_stage < 2)
        creature_name = getattr(self.player_character, "name", creature_id)

        # Award creature if player defeated a station
        station_reward_result = None
        self.logger.info(f"[STATION-REWARD] Checking: winner={winner}, is_station_battle={self.is_station_battle}")
        if winner == 1 and self.is_station_battle:
            # Player won against a station - award the stage 0 creature for the opponent
            try:
                # Shim-first reward source:
                # - enables varied station rewards on badge OTA
                # - fallback keeps behavior safe if shim data is missing
                reward_char_id = None
                if self.station_ui_shim:
                    reward_char_id = self.station_ui_shim.get("character_id")
                if not reward_char_id and self.opponent_character:
                    reward_char_id = self.opponent_character.id
                if not reward_char_id:
                    raise ValueError("No station reward character available")
                self.logger.info(f"[STATION-REWARD] Opponent character id: {reward_char_id}")
                # Get the base form (stage 0) from the evolution tree
                genus = get_genus_for_character(reward_char_id)
                self.logger.info(f"[STATION-REWARD] Genus for {reward_char_id}: {genus}")
                if genus:
                    tree = get_evolution_tree(reward_char_id)
                    self.logger.info(
                        f"[STATION-REWARD] Evolution tree: {[f.get('id') for f in tree] if tree else 'empty'}"
                    )
                    if tree:
                        base_form_id = tree[0].get("id")  # First element is stage 0
                        self.logger.info(f"[STATION-REWARD] Base form to award: {base_form_id}")
                        
                        # Acquire the creature
                        station_reward_result = acquire_creature(prefs, base_form_id, level=1)
                        if isinstance(station_reward_result, dict):
                            station_reward_result["source_character_id"] = reward_char_id
                            station_reward_result["shimmed"] = bool(self.station_ui_shim)
                            if self.station_ui_shim:
                                station_reward_result["shim_station_name"] = self.station_ui_shim.get("station_name")
                        self.logger.info(f"Station reward: {station_reward_result}")
                else:
                    self.logger.warning(f"[STATION-REWARD] No genus found for {reward_char_id}")
            except Exception as e:
                self.logger.warning(f"Failed to award station creature reward: {e}")
                import sys
                sys.print_exception(e)

        # Store in last_battle_result for UI
        self.last_battle_result = {
            "winner": winner,
            "exp_gained": xp_gained,
            "xp_gained_base": result.get("xp_gained_base", xp_gained),
            "xp_boost_pct": result.get("xp_boost_pct", 0),
            "wins": wins,
            "losses": losses,
            "level": new_level,
            "old_level": current_level,
            "leveled_up": leveled_up,
            "can_evolve": can_evolve,
            "creature_id": creature_id,
            "total_xp": new_xp,
            "xp_into_level": xp_result.get("xp_into_level", 0),
            "xp_for_level": xp_result.get("xp_for_level", 0),
            "creature_name": creature_name,
            "current_stage": current_stage,
            "can_evolve_now": can_evolve_now,
            # Snapshot final HP for UI display
            "player_hp_end": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "opponent_hp_end": self.opponent_hp,
            "opponent_max_hp": self.opponent_max_hp,
            # Station reward info (if applicable)
            "station_reward": station_reward_result,
        }
        # If a remote result arrived early, verify it now that we have local data
        self._process_pending_remote_result()

    def _on_error(self, error_code, message):
        """
        Handle battle error (including disconnects/timeouts).

        When a battle ends unexpectedly, determine winner by HP percentage.
        This prevents gaming by timing out or disconnecting.

        Args:
            error_code: Error code
            message: Error message
        """
        self.logger.error(f"Battle error: {message} (code={error_code})")

        # Store error for UI to display if needed
        self.last_error = message

        # If we were in a battle, determine winner by HP percentage
        if self.in_battle:
            winner = calculate_winner_by_hp_percent(
                self.player_hp,
                self.player_max_hp,
                self.opponent_hp,
                self.opponent_max_hp,
            )

            player_pct = (self.player_hp / max(self.player_max_hp, 1)) * 100
            opp_pct = (self.opponent_hp / max(self.opponent_max_hp, 1)) * 100
            self.logger.info(
                f"Battle ended by error - winner={winner} "
                f"(player:{player_pct:.1f}% vs opp:{opp_pct:.1f}%)"
            )

            # Update stats
            self._update_player_stats(winner)
            # Add error info
            if self.last_battle_result is not None:
                self.last_battle_result["error"] = message

            # Show result inline on battle screen
            self.pending_battle_result = self.last_battle_result

        self.in_battle = False
        # Only call end_session if there's actually a session to end
        # This prevents recursion when disconnect triggers error which triggers end_session
        if self.game_bt and self.game_bt.session:
            self.game_bt.end_session()

    def _determine_turn_order(self, our_move, opponent_move):
        """
        Determine turn order based on BattleRules.

        Callback for GameBTComms turn protocol. Uses speed-based turn order
        from Pokemon-style rules, with attacker-wins tiebreaker.

        Args:
            our_move: tuple (move_id, move_data)
            opponent_move: tuple (move_id, move_data)

        Returns:
            bool: True if we go first, False if opponent goes first.
        """
        # Determine if we are the attacker (for speed tie tiebreaker)
        is_challenger = True
        if self.game_bt and self.game_bt.session:
            is_challenger = self.game_bt.session.is_challenger
        self.logger.debug(
            f"[TURN] Determining turn order: our_move={our_move}, opponent_move={opponent_move}, is_challenger={is_challenger}"
        )
        # Use BattleRules to determine turn order
        result = self.rules.calculate_turn_order(
            our_move,
            self.player_stats,
            opponent_move,
            self.opponent_stats,
            is_challenger=is_challenger,
        )
        self.logger.debug(f"[TURN] Turn order result: we_go_first={result}")
        return result

    def _on_turn_resolve(self, turn_number, our_move, opponent_move, we_go_first):
        """
        Handle turn resolution - apply both moves in speed order with consensus.

        CRITICAL FOR CONSENSUS:
        Both devices must compute IDENTICAL results. To achieve this, we use
        CANONICAL execution order based on attacker/defender roles, not
        local player/opponent perspective.

        CANONICAL FLOW:
        1. Map moves to attacker_move and defender_move
        2. Determine execution order (attacker first or defender first) - same on both
        3. Execute using canonical stats (attacker_stats, defender_stats)
        4. Record results in canonical form
        5. Map back to local player/opponent for display

        Args:
            turn_number: Current turn number
            our_move: tuple (move_id, move_data)
            opponent_move: tuple (move_id, move_data)
            we_go_first: True if we move first
        """
        self.logger.info(f"Turn {turn_number}: we_go_first={we_go_first}")
        self.logger.debug(
            f"[TURN] _on_turn_resolve: turn_number={turn_number}, our_move={our_move}, opponent_move={opponent_move}, we_go_first={we_go_first}"
        )

        # Map moves to canonical order: attacker_move, defender_move
        if self.is_challenger:
            attacker_move = our_move
            defender_move = opponent_move
        else:
            attacker_move = opponent_move
            defender_move = our_move

        def _is_defense_move(move_tuple):
            try:
                m = get_move(move_tuple[0])
                return bool(m and m.effect and "defense" in m.effect.lower())
            except Exception:
                return False

        attacker_defending = _is_defense_move(attacker_move)
        defender_defending = _is_defense_move(defender_move)

        # CANONICAL turn order: use canonical stats so both devices agree
        # Rule: defense moves resolve before speed; otherwise higher speed, attacker wins ties
        attacker_speed = self.attacker_stats.speed
        defender_speed = self.defender_stats.speed
        if attacker_defending != defender_defending:
            attacker_goes_first = attacker_defending  # defender move wins if set on that side
        else:
            if attacker_speed != defender_speed:
                attacker_goes_first = attacker_speed > defender_speed
            else:
                attacker_goes_first = True  # Attacker wins speed ties

        # Debug: show move mapping and turn order
        self.logger.info(f"[TURN] is_challenger={self.is_challenger}")
        self.logger.info(
            f"[TURN] our_move={our_move[0]}, opponent_move={opponent_move[0]}"
        )
        self.logger.debug(
            f"[TURN] speeds: attacker={attacker_speed}, defender={defender_speed}, "
            f"attacker_def={attacker_defending}, defender_def={defender_defending} -> attacker_goes_first={attacker_goes_first}"
        )
        self.logger.debug(
            f"[TURN] Canonical mapping: attacker_move={attacker_move}, defender_move={defender_move}, attacker_speed={attacker_speed}, defender_speed={defender_speed}, attacker_goes_first={attacker_goes_first}"
        )
        self.logger.debug(
            f"Canonical moves: attacker={attacker_move[0]}, defender={defender_move[0]}"
        )

        # Queue turn summary for UI log (local perspective)
        our_move_obj = get_move(our_move[0])
        opp_move_obj = get_move(opponent_move[0])
        our_move_name = our_move_obj.name if our_move_obj else str(our_move[0])
        opp_move_name = opp_move_obj.name if opp_move_obj else str(opponent_move[0])
        self.pending_turn_logs.append(
            f"You used {our_move_name} | Opponent used {opp_move_name}"
        )

        # Initialize deterministic RNG for consensus
        # MUST use canonical move order (attacker, defender) for consistent seeding
        rng = None
        if self.consensus_tracker:
            try:
                token_hex = (
                    self.consensus_tracker.session_token[:8].hex()
                    if self.consensus_tracker.session_token
                    else "None"
                )
                self.logger.info(
                    f"[CONSENSUS] begin_turn: token={token_hex}..., turn={turn_number}, attacker={attacker_move[0]}, defender={defender_move[0]}"
                )

                # Use canonical move order for RNG seed
                rng = self.consensus_tracker.begin_turn(
                    turn_number, attacker_move[0], defender_move[0]
                )
                self.rules.set_rng(rng)
                self.logger.debug("Consensus RNG initialized for turn")
            except ValueError as e:
                self.logger.error(f"Consensus turn error: {e}")
                self._void_battle("Turn number mismatch")
                return

        # Create outcome record in CANONICAL form
        outcome = TurnOutcome()
        outcome.turn_number = turn_number
        # Store in canonical order (attacker, defender)
        outcome.player_move_id = attacker_move[0]
        outcome.opponent_move_id = defender_move[0]
        outcome.player_went_first = attacker_goes_first

        # Build canonical execution order
        if attacker_goes_first:
            first = ("attacker", attacker_move)
            second = ("defender", defender_move)
        else:
            first = ("defender", defender_move)
            second = ("attacker", attacker_move)
        self.logger.debug(f"[TURN] Execution order: first={first}, second={second}")

        # Track canonical results
        attacker_damage = 0
        attacker_healed = 0
        attacker_crit = False
        defender_damage = 0
        defender_healed = 0
        defender_crit = False

        victory = BATTLE_CONTINUES

        # Execute moves in CANONICAL order using CANONICAL stats
        for actor, (move_id, move_data) in [first, second]:
            self.logger.debug(
                f"[TURN] Executing {actor}: move_id={move_id}, move_data={move_data}"
            )
            move = get_move(move_id)
            if not move:
                self.logger.warning(f"Unknown move {move_id}")
                continue

            if actor == "attacker":
                # Attacker attacks Defender
                value, result = self.rules.execute_action(
                    move, self.attacker_stats, self.defender_stats
                )
                attacker_damage = result.get("damage", 0)
                attacker_healed = result.get("healed", 0)
                attacker_crit = result.get("critical", False)
                self.logger.info(
                    f"Attacker used {move.name}: {result.get('messages', [])}"
                )
            else:
                # Defender attacks Attacker
                value, result = self.rules.execute_action(
                    move, self.defender_stats, self.attacker_stats
                )
                defender_damage = result.get("damage", 0)
                defender_healed = result.get("healed", 0)
                defender_crit = result.get("critical", False)
                self.logger.info(
                    f"Defender used {move.name}: {result.get('messages', [])}"
                )

            # Check for victory using canonical stats
            victory = self.rules.check_victory_condition(
                self.attacker_stats, self.defender_stats
            )
            self.logger.debug(
                f"[TURN] Post-move: actor={actor}, victory={victory}, attacker_hp={self.attacker_stats.hp}, defender_hp={self.defender_stats.hp}"
            )
            if victory != BATTLE_CONTINUES:
                self.logger.info(f"Victory condition met: {victory}")
                break

        # Record canonical results in outcome
        outcome.player_damage_dealt = (
            attacker_damage  # "player" = attacker in canonical
        )
        outcome.opponent_damage_dealt = (
            defender_damage  # "opponent" = defender in canonical
        )
        outcome.player_healed = attacker_healed
        outcome.opponent_healed = defender_healed
        outcome.player_crit = attacker_crit
        outcome.opponent_crit = defender_crit

        # Update local HP tracking from canonical stats
        # Map canonical back to local perspective, clamp to 0 minimum
        if self.is_challenger:
            self.player_hp = max(0, self.attacker_stats.hp)
            self.opponent_hp = max(0, self.defender_stats.hp)
        else:
            self.player_hp = max(0, self.defender_stats.hp)
            self.opponent_hp = max(0, self.attacker_stats.hp)

        # Process end-of-turn effects (status damage, etc.) if battle continues
        if victory == BATTLE_CONTINUES:
            messages = self.rules.on_turn_end(
                (
                    self.attacker_stats.to_dict()
                    if hasattr(self.attacker_stats, "to_dict")
                    else self.attacker_stats
                ),
                (
                    self.defender_stats.to_dict()
                    if hasattr(self.defender_stats, "to_dict")
                    else self.defender_stats
                ),
            )
            for msg in messages:
                self.logger.info(f"End of turn: {msg}")

            # Update HP after status effects, clamp to 0 minimum
            if self.is_challenger:
                self.player_hp = max(0, self.attacker_stats.hp)
                self.opponent_hp = max(0, self.defender_stats.hp)
            else:
                self.player_hp = max(0, self.defender_stats.hp)
                self.opponent_hp = max(0, self.attacker_stats.hp)

        # Record final HP in CANONICAL form, clamped to 0 minimum
        outcome.player_hp_after = max(0, self.attacker_stats.hp)
        outcome.opponent_hp_after = max(0, self.defender_stats.hp)

        # Capture RNG state for consensus verification
        if rng:
            outcome.rng_state = rng.get_state()

        # Clear RNG from rules
        self.rules.clear_rng()

        # Send consensus hash with explicit turn number
        # (session.turn_number is already incremented by _resolve_turn)
        if self.consensus_tracker:
            self.consensus_tracker.record_outcome(outcome)
            our_hash = self.consensus_tracker.get_our_hash()
            if our_hash and self.game_bt:
                self.game_bt.send_consensus_hash(our_hash, turn_number)
                self.logger.debug(
                    f"Sent consensus hash for turn {turn_number}: {our_hash.hex()[:16]}..."
                )

        # State is already updated - BattlePanel reads from BattleManager directly
        # via get_battle_info() during its update loop

        # NOTE: We do NOT end the battle here. We wait for consensus confirmation.
        # If victory condition is met, it will be handled in _on_consensus_result
        # after we verify the opponent agrees with the outcome.
        if victory != BATTLE_CONTINUES:
            self.logger.info(
                f"Turn {turn_number} resulted in victory condition: {victory}. Waiting for consensus..."
            )

    def _on_consensus_result(self, turn_number, agreed, their_hash):
        """
        Handle consensus verification result.

        Called by GameBTComms after receiving opponent's outcome hash.
        Syncs the ConsensusTracker with the protocol layer result.

        Args:
            turn_number: Turn number being verified
            agreed: True if hashes matched (determined by comms layer)
            their_hash: Opponent's 16-byte hash
        """
        if agreed:
            self.logger.info(f"Consensus achieved for turn {turn_number}")
            if self.consensus_tracker:
                try:
                    # Sync tracker with protocol layer - store opponent's hash
                    self.consensus_tracker.receive_opponent_hash(their_hash)
                    self.consensus_tracker.commit_turn()
                except RuntimeError as e:
                    self.logger.error(f"Failed to commit turn: {e}")

            # Turn complete - check if battle ended
            victory = self.rules.check_victory_condition(
                self.attacker_stats, self.defender_stats
            )

            if victory != BATTLE_CONTINUES:
                # Battle ended! Process result based on consensus state
                if victory == BATTLE_DRAW:
                    local_winner = 0
                elif self.is_challenger:
                    # We are attacker: attacker wins (1) → we win (1), defender wins (2) → opponent wins (2)
                    local_winner = victory
                else:
                    # We are defender: attacker wins (1) → opponent wins (2), defender wins (2) → we win (1)
                    local_winner = 2 if victory == PLAYER_WINS else 1

                # Log our perspective on the result
                if local_winner == 0:
                    result_msg = "DRAW"
                elif local_winner == 1:
                    result_msg = "VICTORY!"
                else:
                    result_msg = "DEFEAT"
                self.logger.info(
                    f"Battle ended (Consensus Verified): winner={local_winner}, result={result_msg}"
                )

                # Update player stats locally
                self._update_player_stats(local_winner)
                # Persist final HP snapshot for UI (local perspective)
                if self.last_battle_result is not None:
                    self.last_battle_result["player_hp_end"] = self.player_hp
                    self.last_battle_result["player_max_hp"] = self.player_max_hp
                    self.last_battle_result["opponent_hp_end"] = self.opponent_hp
                    self.last_battle_result["opponent_max_hp"] = self.opponent_max_hp

                # Achievements: first battle (non-draw)
                try:
                    if self.achievements:
                        self.achievements.first_battle(local_winner)
                        if local_winner == 1:
                            self.achievements.win_streak()
                        elif local_winner == 2:
                            self.achievements.loss_streak()
                        else:
                            self.achievements.reset_streaks()
                except Exception as e:
                    self.logger.warning(f"Achievement check failed: {e}")

                # Send result packet as confirmation (optional but good for protocol completeness)
                if self.game_bt:
                    self.game_bt.send_battle_result(winner=local_winner)

                # Store result and show inline
                self.pending_battle_result = self.last_battle_result
                self.waiting_for_opponent = False
                self.in_battle = False
            else:
                # Battle continues - allow UI to accept next move selection
                self.waiting_for_opponent = False
                self.logger.debug(
                    f"[BM] _on_consensus_result: waiting_for_opponent set to False for turn {turn_number}"
                )
                self.logger.debug(f"Turn {turn_number} complete, ready for next move")
        else:
            self.logger.error(f"CONSENSUS FAILED for turn {turn_number}!")
            self._void_battle("Outcome hash mismatch")

    def _void_battle(self, reason):
        """
        Void the battle due to consensus failure or error.

        Args:
            reason: Reason for voiding
        """
        self.logger.error(f"BATTLE VOIDED: {reason}")

        if self.consensus_tracker:
            void_info = self.consensus_tracker.void_battle(reason)
            self.logger.debug(f"Void info: {void_info}")

        # Store error for UI to display
        self.last_error = f"Battle void: {reason}"

        # Store result for battle_result panel
        self.last_battle_result = {
            "winner": 0,  # Draw/void
            "exp_gained": 0,
            "wins": 0,
            "losses": 0,
            "voided": True,
            "error": reason,
        }

        # Show result inline on battle screen
        self.pending_battle_result = self.last_battle_result
        self.waiting_for_opponent = False

        # End the battle session
        self.end_battle()

    # Internal helper methods

    def _reset_battle_stats(self):
        """Reset all battle state for new battle or after battle ends."""
        initial_stats = self.rules.get_initial_stats()
        self.player_hp = initial_stats["hp"]
        self.player_max_hp = initial_stats["max_hp"]
        self.player_status = 0
        self.opponent_hp = initial_stats["hp"]
        self.opponent_max_hp = initial_stats["max_hp"]
        self.opponent_status = 0
        self.waiting_for_opponent = False
        self._waiting_since_ms = None
        self._waiting_turn_number = None
        self.is_challenger = True
        self.attacker_stats = None
        self.defender_stats = None
        self.attacker_moves = []
        self.defender_moves = []
        self.last_battle_result = None
        self.pending_battle_result = None
        self.pending_remote_result = None
        self.last_error = None
        self.consensus_tracker = None
        self.current_session = None
        self.battle_context = None
        self.station_ui_shim = None
        self.local_ready = False
        self.remote_ready = False
        self.ready_handshake_complete = False
        self.ready_sent_ts = None
        self.player_care_effects = None
        self.opponent_care_effects = None
        self.player_power_effects = None
        self.opponent_power_effects = None
        self.last_ready_resend_ts = None
        self.player_care_mods = None
        self.opponent_care_mods = None
        self.player_power_mods = None
        self.opponent_power_mods = None

    def _select_station_ui_shim(self):
        """
        Pick a random station creature for local UI/reward shimming.

        This never alters battle protocol/consensus state; it only affects
        local display data and badge-side station reward selection.

        Rationale: stations may share a fixed character_id in deployed firmware.
        Badge-side shim lets OTA-updated badges diversify station presentation
        and rewards without requiring station reflashes.
        """
        try:
            registry = get_station_registry()
            stations = [
                s for s in registry.all() if s and getattr(s, "id", "") != "default"
            ]
            candidates = []
            for station in stations:
                char = get_character(station.character_id)
                if not char:
                    continue
                candidates.append(
                    {
                        "station_id": station.id,
                        "station_name": station.name,
                        "character_id": station.character_id,
                        "character_name": char.name,
                        "sprite_path": getattr(char, "sprite_path", None),
                        "sprite_meta": (getattr(char, "extra", {}) or {}).get(
                            "sprite_meta", {}
                        ),
                    }
                )
            if not candidates:
                return None
            count = len(candidates)
            idx = None
            try:
                if hasattr(_random_mod, "randrange"):
                    idx = _random_mod.randrange(count)
                elif hasattr(_random_mod, "getrandbits"):
                    # Rejection sampling keeps distribution unbiased.
                    bits = (count - 1).bit_length()
                    while True:
                        pick = _random_mod.getrandbits(bits)
                        if pick < count:
                            idx = pick
                            break
                elif hasattr(_random_mod, "randint"):
                    idx = _random_mod.randint(0, count - 1)
            except Exception:
                idx = None
            if idx is None:
                idx = time.ticks_ms() % count
            return candidates[idx]
        except Exception as e:
            self.logger.warning(f"Station shim selection failed: {e}")
            return None

    def _load_local_care_effects(self):
        """Load local care effect IDs for activity/food."""
        # During a live session, use the exact negotiated/transmitted set so
        # local stat application matches what we sent over player-data TLV.
        if self.game_bt:
            try:
                if self.game_bt.session and self.game_bt.session.our_player_data is not None:
                    return self.game_bt.get_our_care_effects()
            except Exception:
                pass
        try:
            state = get_care_state(prefs) or {}
        except Exception as e:
            self.logger.debug(f"Care state load failed: {e}")
            state = {}
        activity_id = (state.get("activity") or {}).get("id")
        food_id = (state.get("food") or {}).get("id")
        return {"activity": activity_id or None, "food": food_id or None}

    def _load_local_power_effects(self):
        """Load active achievement power IDs."""
        # During a live session, use the exact negotiated/transmitted set so
        # local stat application matches what we sent over player-data TLV.
        if self.game_bt:
            try:
                if self.game_bt.session and self.game_bt.session.our_player_data is not None:
                    return self.game_bt.get_our_power_effects()
            except Exception:
                pass
        try:
            achievements_cls = _load_achievements_class()
            if not achievements_cls:
                return []
            return achievements_cls().get_active_powers()
        except Exception as e:
            self.logger.debug(f"Power state load failed: {e}")
            return []

    def _load_opponent_care_effects(self):
        """Load opponent care effect IDs from exchanged player data."""
        if not self.game_bt:
            return {"activity": None, "food": None}
        return self.game_bt.get_opponent_care_effects()

    def _load_opponent_power_effects(self):
        """Load opponent achievement power IDs from exchanged player data."""
        if not self.game_bt:
            return []
        return self.game_bt.get_opponent_power_effects()

    def _get_player_data(self):
        """
        Get current player data from authoritative state (prefs/config/station).
        Always returns the correct character_id, never a fallback default.
        """
        # If prefs have a different active character (e.g., changed via UI), sync it.
        # Skip this for headless/station mode so station-assigned characters aren't overwritten.
        if not self.headless:
            try:
                stored_active = prefs.get_string(ACTIVE_CHAR_KEY, "")
                if stored_active and stored_active != self.player_character_id:
                    self.logger.info(
                        f"Active character changed in prefs: {self.player_character_id} -> {stored_active} (syncing)"
                    )
                    self.set_active_character(stored_active)
            except Exception as e:
                self.logger.debug(f"Active character sync skipped: {e}")

        if not self.player_character_id:
            self.logger.error(
                "_get_player_data: player_character_id is not set! This should never happen."
            )
            raise ValueError("player_character_id must be set!")
        try:
            handle = prefs.get_string(
                HANDLE_KEY,
                prefs.get_string(LEGACY_HANDLE_KEY, ""),
            )
            creature_stats = get_creature_stats(prefs, self.player_character_id)
            # Wins/losses are stored under the compact keys managed here
            wins = prefs.get_int32(KEY_WINS, 0)
            losses = prefs.get_int32(KEY_LOSSES, 0)
        except Exception:
            handle = ""
            creature_stats = {"level": 1}
            wins = 0
            losses = 0
        care_activity = None
        care_food = None
        try:
            care_state = get_care_state(prefs) or {}
            care_activity = (care_state.get("activity") or {}).get("id")
            care_food = (care_state.get("food") or {}).get("id")
        except Exception as e:
            self.logger.debug(f"Care state read failed: {e}")
        power_ids = []
        try:
            achievements_cls = _load_achievements_class()
            power_ids = achievements_cls().get_active_powers() if achievements_cls else []
        except Exception as e:
            self.logger.debug(f"Power state read failed: {e}")

        player_data = {
            "character_id": self.player_character_id,
            # Send the authoritative per-creature level (per-inventory tracking)
            "level": max(1, creature_stats.get("level", 1)),
            "name": handle or getattr(self, "device_name", None),
            "wins": wins,
            "losses": losses,
            "care_activity": care_activity or None,
            "care_food": care_food or None,
            "powers": power_ids or [],
        }
        
        # Stations always set is_station flag so opponents know they're fighting a gym
        # headless mode = AUTO_BATTLE_MODE = station/gym mode
        if self.headless:
            player_data["is_station"] = 1
        
        return player_data

    def is_in_battle(self):
        """
        Check if currently in an active battle.

        Returns:
            bool: True if in battle, False otherwise.
        """
        return self.in_battle

    def is_scanning(self):
        """
        Check if currently scanning for opponents.

        Returns:
            bool: True if scanning, False otherwise.
        """
        # Check the underlying Bluetooth layer for actual scan state
        # This is more reliable than our own flag which can get out of sync
        if self.game_bt and hasattr(self.game_bt, "bt"):
            return self.game_bt.bt.is_scanning()
        return self.scanning

    # =========================================================================
    # Main Update Loop
    # =========================================================================

    def update(self):
        """
        Update battle manager state.

        Call this regularly (e.g., in main loop) to:
            - Process pending UI panel transitions (DEFERRED to avoid recursion)
            - Update GameBTComms protocol state
            - Check battle timeout (for station mode)
            - Process battle logic

        Recommended: Call every 50-100ms.
        """
        # No debug log here; log only on state transitions or key events
        # Process pending UI transitions FIRST (deferred from BLE callbacks)
        self._process_pending_ui()
        self._ensure_ready_progress()
        # Check battle timeout (for station mode)
        self._check_battle_timeout()
        # Update underlying protocol
        if self.game_bt:
            self.game_bt.update()
        # If we're stuck waiting on a peer (e.g., reboot/crash), fail the battle
        # deterministically instead of spinning forever.
        self._check_waiting_for_opponent_timeout()

    def _check_waiting_for_opponent_timeout(self):
        """
        End the battle if we have been waiting too long for the peer to progress.

        This is intentionally independent of comms keepalives so we can recover
        even if keepalives are flowing but turn progress is stalled.
        """
        session = self.game_bt.session if self.game_bt else None
        if not self.in_battle or not session or session.state != SESSION_BATTLING:
            self.waiting_for_opponent = False
            self._waiting_since_ms = None
            self._waiting_turn_number = None
            return
        if self.last_battle_result or self.pending_battle_result:
            self.waiting_for_opponent = False
            self._waiting_since_ms = None
            self._waiting_turn_number = None
            return
        # Don't enforce during UI-ready handshake in full UI mode.
        # Headless stations can progress immediately, so allow watchdog there.
        if not self.ready_handshake_complete and not self.headless:
            self.waiting_for_opponent = False
            self._waiting_since_ms = None
            self._waiting_turn_number = None
            return

        waiting = session.turn_state == TURN_WAITING
        if not waiting:
            self.waiting_for_opponent = False
            self._waiting_since_ms = None
            self._waiting_turn_number = None
            return

        now = time.ticks_ms()
        # Reset timeout on new turn progress.
        if self._waiting_turn_number != session.turn_number:
            self._waiting_turn_number = session.turn_number
            self._waiting_since_ms = now
        elif self._waiting_since_ms is None:
            self._waiting_since_ms = now

        self.waiting_for_opponent = True

        base_timeout = getattr(config, "BATTLE_MOVE_TIMEOUT_MS", 30000)
        # Small grace to reduce edge races (both sides may hit their local timeout simultaneously).
        grace_ms = getattr(config, "BATTLE_OPPONENT_WAIT_GRACE_MS", 5000)
        timeout_ms = base_timeout + grace_ms

        if time.ticks_diff(now, self._waiting_since_ms) > timeout_ms:
            self.logger.warning(
                f"Opponent wait timeout ({timeout_ms}ms) - aborting battle"
            )
            self._handle_error("Opponent timed out")

    # Public API for UI/main loop
    def cleanup_stale_session(self, reason=""):
        """
        Clear pre-battle protocol sessions that can block new matchmaking actions.

        A session stuck in CHALLENGING/CHALLENGED/HANDSHAKING/EXCHANGING_DATA
        should not survive user navigation back to matchmaking.
        """
        if not self.game_bt:
            return False
        session = self.game_bt.session
        if not session:
            return False

        stale_states = (
            SESSION_CHALLENGING,
            SESSION_CHALLENGED,
            SESSION_HANDSHAKING,
            SESSION_EXCHANGING_DATA,
        )
        if session.state in stale_states:
            self.logger.warning(
                f"Cleaning stale pre-battle session state={session.state}"
                + (f" ({reason})" if reason else "")
            )
            self.game_bt.end_session()
            return True
        return False

    def enter_matchmaking(self):
        """
        Enter matchmaking mode - badge is now OPEN to battle challenges.

        Call this when user wants to find battles. Badge will:
            - Start GATT server to receive incoming challenges
            - Advertise as AVAILABILITY_OPEN
            - Accept incoming challenges automatically
            - Be visible to other badges scanning for opponents

        Returns:
            bool: True if matchmaking mode activated.
        """
        if not self.game_bt:
            self.logger.warning("GameBTComms not initialized")
            return False

        if self.in_battle:
            self.logger.warning("Cannot enter matchmaking during battle")
            return False

        # Defensive cleanup so stale pre-battle sessions don't block reopening matchmaking.
        self.cleanup_stale_session("enter_matchmaking")

        self.logger.info("Entering matchmaking mode")
        self.matchmaking_enabled = True

        # Start GATT server to receive incoming connections and challenges
        # This must happen BEFORE advertising as OPEN
        if not self.game_bt.start_server_mode():
            self.logger.error("Failed to start server mode")
            return False

        self.game_bt.set_availability(AVAILABILITY_OPEN)
        return True

    def exit_matchmaking(self):
        """
        Exit matchmaking mode - badge returns to IDLE (not looking for battles).

        Call this when user closes battle UI or wants to stop receiving challenges.
        Badge will still be discoverable but won't appear in opponent lists.

        Stops GATT server and sets availability to IDLE.

        Returns:
            bool: True if matchmaking mode exited.
        """
        if not self.game_bt:
            return False

        self.logger.info("Exiting matchmaking mode")
        self.matchmaking_enabled = False

        # Stop server mode (no longer accepting challenges)
        self.game_bt.stop_server_mode()

        self.game_bt.set_availability(AVAILABILITY_IDLE)
        return True

    def start_opponent_scan(self, duration_ms=5000):
        """
        Start scanning for nearby opponents.

        Note: Only returns badges that are in AVAILABILITY_OPEN state (actively
        looking for battles). To see all badges, use get_opponents with only_available=False.

        Args:
            duration_ms (int): Scan duration in milliseconds (0 = continuous).

        Returns:
            bool: True if scan started successfully.
        """
        if not self.game_bt:
            self.logger.warning("GameBTComms not initialized")
            return False

        if self.in_battle:
            self.logger.warning("Cannot scan during battle")
            return False

        # Defensive cleanup before scanning/challenging workflow.
        self.cleanup_stale_session("start_scan")

        self.logger.info("Scanning for opponents...")
        self.scanning = True
        self.last_scan_results = []

        return self.game_bt.start_opponent_scan(duration_ms)

    def stop_opponent_scan(self):
        """
        Stop scanning for opponents.

        Returns:
            bool: True if scan stopped successfully.
        """
        if not self.game_bt:
            return False

        self.scanning = False
        return self.game_bt.stop_opponent_scan()

    def get_opponents(self, min_rssi=-70, limit=10, only_available=True):
        """
        Get list of nearby opponents from last scan.

        Args:
            min_rssi (int): Minimum signal strength (default: -70 dBm for stable connection).
            limit (int): Maximum number to return.
            only_available (bool): Only return badges in AVAILABILITY_OPEN state (default: True).

        Returns:
            list: List of BluetoothDevice objects sorted by signal strength.

        Notes:
            Automatically filters to only CactusCon badges (by UUID pattern).
            By default, only returns badges actively looking for battles (AVAILABILITY_OPEN).
            Set only_available=False to see all badges including IDLE ones (for debugging).
        """
        if not self.game_bt:
            return []

        opponents = self.game_bt.get_nearby_opponents(
            min_rssi=min_rssi, limit=limit, only_available=only_available
        )

        self.last_scan_results = opponents
        return opponents

    def challenge_opponent(self, opponent_device):
        """
        Challenge a specific opponent to battle.

        Args:
            opponent_device (BluetoothDevice): Device to challenge.

        Returns:
            bool: True if challenge sent successfully.
        """
        if not self.game_bt:
            self.logger.warning("GameBTComms not initialized")
            return False

        if self.in_battle:
            self.logger.warning("Already in battle")
            return False

        # If user came back from a stale pre-battle flow, reset before issuing new challenge.
        self.cleanup_stale_session("challenge_opponent")

        # NOTE: player_data_provider callback handles player data
        # when _send_player_data() is called after session is established

        self.logger.info(f"Challenging {opponent_device.name}...")
        return self.game_bt.challenge_opponent(opponent_device.addr)

    def accept_challenge(self, opponent_addr):
        """
        Accept an incoming challenge.

        Args:
            opponent_addr (bytes or str): Opponent's BLE address.

        Returns:
            bool: True if accepted successfully.
        """
        if not self.game_bt:
            return False

        # NOTE: player_data_provider callback handles player data
        # when _send_player_data() is called after session is established

        self.logger.info("Accepting challenge...")
        return self.game_bt.accept_challenge(opponent_addr)

    def decline_challenge(self, opponent_addr):
        """
        Decline an incoming challenge.

        Args:
            opponent_addr (bytes or str): Opponent's BLE address.

        Returns:
            bool: True if declined successfully.
        """
        if not self.game_bt:
            return False

        self.logger.info("Declining challenge...")
        return self.game_bt.decline_challenge(opponent_addr)

    def use_move(self, move_id, move_data=None):
        """
        Use a battle move against opponent.

        Sends a TURN_READY message with the selected move. Once both players
        have selected their moves, the turn resolves based on speed priority.

        Args:
            move_id (int): Move identifier.
            move_data (optional): Additional move data.

        Returns:
            bool: True if move sent successfully.
        """
        if not self.in_battle or not self.game_bt:
            self.logger.warning("Not in battle")
            return False
        self.logger.info(f"Using move {move_id}")
        self.logger.debug(
            f"[TURN] Player selected move_id={move_id}, move_data={move_data}"
        )

        # Temperament-based disobedience chance (clients only)
        disobey = False
        if not self.headless:
            try:
                from cactuscon.game.engine.characters import (
                    get_care_state,
                )

                care_state = get_care_state(prefs)
                temperament = care_state.get("temperament", 0)
                if temperament >= 5:
                    # Temperament scale 0-10; disobedience starts at 5.
                    # Chance (%) = 2 * temperament (so 10% at 5, 20% at 10).
                    chance = min(100, temperament * 2)
                    roll = time.ticks_ms() % 100
                    if roll < chance:
                        disobey = True
            except Exception as e:
                self.logger.debug(f"Disobedience check failed: {e}")

        if disobey:
            msg = "Your creature ignored the command!"
            self.pending_turn_logs.append(msg)
            self.logger.info(msg)

        # Send turn ready with our move selection (turn-based protocol)
        success = self.game_bt.send_turn_ready(move_id, move_data)
        # State tracking - BattlePanel reads this to know we're waiting
        if success:
            self.waiting_for_opponent = True
            self.logger.debug(
                f"[BM] use_move: waiting_for_opponent set to True after move {move_id}"
            )
        return success

    def forfeit_battle(self):
        """
        Forfeit current battle.

        Returns:
            bool: True if forfeit sent successfully.
        """
        if not self.game_bt:
            return False

        self.logger.info("Forfeiting battle...")
        success = self.game_bt.forfeit_battle()

        if success:
            self.in_battle = False
            self._reset_battle_stats()

        return success

    def end_battle(self):
        """
        End current battle session and cleanup.

        Call this after battle completes to release resources.
        """
        if self.game_bt:
            self.game_bt.end_session()

        self.in_battle = False
        self.current_session = None
        self.opponent_character = None
        self._reset_battle_stats()

        self.logger.info("Battle ended")

    def get_battle_info(self):
        """
        Get current battle information for UI initialization.

        Returns:
            dict or None: Battle state info, or None if not in battle.
            Keys:
                - in_battle: True if battle is active
                - player_name: Our character name
                - player_hp: Current player HP
                - player_max_hp: Max player HP
                - player_moves: List of available move IDs
                - player_status: Current status effects (bitmask)
                - opponent_name: Opponent's name
                - opponent_hp: Current opponent HP
                - opponent_max_hp: Max opponent HP
                - opponent_status: Opponent status effects (bitmask)
                - turn_number: Current turn number
                - session_duration_ms: Time since battle started
        """
        if not self.in_battle or not self.current_session:
            return None

        player_name = "Player"
        if self.player_character:
            player_name = self.player_character.name
        player_sprite_path = (
            self.player_character.sprite_path if self.player_character else None
        )
        player_sprite_meta = (
            self.player_character.extra.get("sprite_meta", {})
            if self.player_character
            else {}
        )

        opponent_sprite_path = (
            self.opponent_character.sprite_path if self.opponent_character else None
        )
        opponent_sprite_meta = (
            self.opponent_character.extra.get("sprite_meta", {})
            if self.opponent_character
            else {}
        )
        opponent_name = self.current_session.opponent_name or "Opponent"
        opponent_character_name = (
            getattr(self.opponent_character, "name", None)
            or self.current_session.opponent_name
            or "Opponent"
        )
        if self.is_station_battle and self.station_ui_shim:
            # UI-only override for station battles.
            # Do not mutate opponent_character/stats used by battle logic.
            opponent_name = self.station_ui_shim.get("station_name") or opponent_name
            opponent_character_name = (
                self.station_ui_shim.get("character_name") or opponent_character_name
            )
            opponent_sprite_path = (
                self.station_ui_shim.get("sprite_path") or opponent_sprite_path
            )
            opponent_sprite_meta = (
                self.station_ui_shim.get("sprite_meta") or opponent_sprite_meta
            )

        return {
            "in_battle": self.in_battle,
            "player_name": player_name,
            "player_hp": self.player_hp,
            "player_max_hp": self.player_max_hp,
            "player_moves": list(self.player_moves),
            "player_status": self.player_status,
            "player_character_name": player_name,
            "opponent_name": opponent_name,
            "opponent_hp": self.opponent_hp,
            "opponent_max_hp": self.opponent_max_hp,
            "opponent_status": self.opponent_status,
            "opponent_character_name": opponent_character_name,
            "turn_number": self.current_session.turn_number,
            "session_duration_ms": self.current_session.duration_ms(),
            "player_sprite_path": player_sprite_path,
            "player_sprite_meta": player_sprite_meta,
            "opponent_sprite_path": opponent_sprite_path,
            "opponent_sprite_meta": opponent_sprite_meta,
        }
