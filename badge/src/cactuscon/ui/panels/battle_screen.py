"""Battle screen panel - Active battle UI with move selection and turn-based combat."""

import lvgl as lv
import time
import gc
from micropython import const

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.ui.layout_utils import get_screen_size
from cactuscon.game.engine.moves import get_move, MOVE_CAT_SUPPORT, MOVE_CAT_RECOVERY
from cactuscon.game.engine.characters import get_character
from cactuscon.prefs import prefs
from cactuscon import config
from cactuscon.ui.sprites import evict_sprite_cache

# Battle UI states
BATTLE_UI_INIT = const(0)  # Battle starting
BATTLE_UI_SELECTING = const(1)  # Our turn - selecting move
BATTLE_UI_WAITING = const(2)  # Waiting for opponent
BATTLE_UI_RESOLVING = const(3)  # Moves being resolved
BATTLE_UI_RESULT = const(4)  # Battle ended

# Timeout for player move selection (ms)
MOVE_SELECT_TIMEOUT_MS = const(20000)  # 20 seconds
# Max time to keep "Sending move..." overlay before yielding to terminal result UI.
MOVE_SEND_SPINNER_TIMEOUT_MS = const(5000)

# Colors
COLOR_HP_FULL = lv.color_hex(0x00FF00)  # Green
COLOR_HP_MEDIUM = lv.color_hex(0xFFFF00)  # Yellow
COLOR_HP_LOW = lv.color_hex(0xFF0000)  # Red
COLOR_TIMEOUT_BAR = lv.color_hex(0x4488FF)  # Blue
COLOR_YOUR_TURN = lv.color_hex(0x00FF00)  # Green
COLOR_WAITING = lv.color_hex(0xFFAA00)  # Orange
COLOR_BG_DARK = lv.color_hex(0x1A1A2E)
COLOR_BG_PANEL = lv.color_hex(0x2A2A4A)

PLAYER_SPRITE_DIMENSION = 64

class BattlePanel(BasePanel):
    """
    Active battle screen with landscape layout for 320x240.

    Features:
    - Side-by-side opponent/player areas
    - Dynamic move buttons (2x2 grid)
    - Turn indicator with timeout countdown
    - HP bars with color coding
    - Battle log
    """

    def __init__(
        self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs
    ):
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)

        # Battle state
        self.ui_state = BATTLE_UI_INIT

        # Load player info from prefs/config
        self.player_name = prefs.get_string("player_name", "Player")

        # Load character info
        char_id = prefs.get_string("character", config.PLAYER_CHARACTER_ID)
        character = get_character(char_id)

        if character:
            self.player_character_name = character.name
            self.player_hp = character.base_stats.hp
            self.player_max_hp = character.base_stats.max_hp
        else:
            self.player_character_name = "Hacktarmon"
            self.player_hp = 100
            self.player_max_hp = 100

        self.opponent_name = "Opponent"
        self.opponent_hp = 100
        self.opponent_max_hp = 100
        self.opponent_character_name = "Deeno"

        # Turn state
        self.is_our_turn = False
        self.turn_start_time = 0
        self.timeout_ms = config.BATTLE_MOVE_TIMEOUT_MS
        self.move_inflight = False
        self.move_send_started_ms = None

        # Move buttons - use dict mapping instead of set_user_data (LVGL 9.x limitation)
        self.available_moves = []
        self.move_buttons = []
        self.button_to_move_id = {}  # Map button object id() to move_id

        # Battle log
        self.battle_log_messages = []
        self.max_log_messages = 4
        # Keep references to icon descriptors to avoid GC
        self._icon_sprites = {}
        self._icon_img_dsc = {}
        self._icon_img_data = {}
        self._icon_sprite_paths = {}

    def _create_combatant_areas(self, screen_w, area_h):
        """Create battle stage with cornered sprites and HP/name placements."""
        stage = lv.obj(self.screen)
        stage.set_size(screen_w, area_h)
        stage.set_pos(0, 0)
        stage.set_style_bg_color(COLOR_BG_DARK, 0)  # dark brown placeholder
        stage.set_style_border_width(0, 0)
        stage.set_style_pad_all(8, 0)
        self.ui_elements["battle_stage"] = stage

        hp_bar_len = 100
        opponent_margin_left = screen_w - PLAYER_SPRITE_DIMENSION - 20 - hp_bar_len - 8

        # Opponent info (top-left)
        opp_name = lv.label(stage)
        opp_name.set_text(self.opponent_name)
        opp_name.set_pos(opponent_margin_left, 4)
        opp_name.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        self.ui_elements["opponent_name"] = opp_name

        opp_type = lv.label(stage)
        opp_type.set_text(self.opponent_character_name)
        opp_type.set_pos(opponent_margin_left, 20)
        opp_type.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        opp_type.set_style_text_font(lv.font_montserrat_12, 0)
        self.ui_elements["opponent_type"] = opp_type


        opp_hp_bar = lv.bar(stage)
        opp_hp_bar.set_size(hp_bar_len, 10)
        opp_hp_bar.set_pos(opponent_margin_left, 40)
        opp_hp_bar.set_range(0, 100)
        opp_hp_bar.set_value(100, False)
        opp_hp_bar.set_style_bg_color(lv.color_hex(0x333333), 0)
        opp_hp_bar.set_style_bg_color(COLOR_HP_FULL, lv.PART.INDICATOR)
        opp_hp_bar.set_style_radius(2, 0)
        opp_hp_bar.set_style_radius(2, lv.PART.INDICATOR)
        self.ui_elements["opponent_hp_bar"] = opp_hp_bar

        opp_hp_text = lv.label(stage)
        opp_hp_text.set_text("100%")
        opp_hp_text.set_pos(opponent_margin_left - 32, 40)
        opp_hp_text.set_style_text_color(lv.color_hex(0xEEEEEE), 0)
        opp_hp_text.set_style_text_font(lv.font_montserrat_12, 0)
        self.ui_elements["opponent_hp_text"] = opp_hp_text

        # Opponent sprite (upper-right)
        opp_sprite = lv.obj(stage)
        opp_sprite.set_size(PLAYER_SPRITE_DIMENSION, PLAYER_SPRITE_DIMENSION)
        opp_sprite.set_style_bg_color(COLOR_BG_DARK, 0)  # Match arena background for transparency effect
        opp_sprite.set_style_radius(4, 0)
        opp_sprite.set_pos(screen_w - PLAYER_SPRITE_DIMENSION - 20, 12)
        opp_sprite.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["opponent_sprite"] = opp_sprite

        # Player sprite (lower-left)
        player_sprite = lv.obj(stage)
        player_sprite.set_size(PLAYER_SPRITE_DIMENSION, PLAYER_SPRITE_DIMENSION)
        player_sprite.set_style_bg_color(COLOR_BG_DARK, 0)  # Match arena background for transparency effect
        player_sprite.set_style_radius(4, 0)
        player_sprite.set_pos(16, area_h - PLAYER_SPRITE_DIMENSION - 20)
        player_sprite.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["player_sprite"] = player_sprite

        # Player info (bottom-right, mirrored styling)
        player_name = lv.label(stage)
        player_name.set_text("You")
        player_name.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        player_name_pos_x = 16 + PLAYER_SPRITE_DIMENSION + 8
        player_name_pos_y = area_h - 72
        player_name.set_pos(player_name_pos_x, player_name_pos_y)
        self.ui_elements["player_name"] = player_name

        player_type = lv.label(stage)
        player_type.set_text(self.player_character_name)
        player_type.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        player_type.set_style_text_font(lv.font_montserrat_12, 0)
        player_type.set_pos(player_name_pos_x, player_name_pos_y + 16)
        self.ui_elements["player_type"] = player_type

        player_hp_bar = lv.bar(stage)
        player_hp_bar.set_size(hp_bar_len, 10)
        player_hp_bar.set_range(0, 100)
        player_hp_bar.set_value(100, False)
        player_hp_bar.set_style_bg_color(lv.color_hex(0x333333), 0)
        player_hp_bar.set_style_bg_color(COLOR_HP_FULL, lv.PART.INDICATOR)
        player_hp_bar.set_style_radius(2, 0)
        player_hp_bar.set_style_radius(2, lv.PART.INDICATOR)
        player_hp_bar_x = player_name_pos_x
        player_hp_bar_y = area_h - 28
        player_hp_bar.set_pos(player_hp_bar_x, player_hp_bar_y)
        self.ui_elements["player_hp_bar"] = player_hp_bar

        player_hp_text = lv.label(stage)
        player_hp_text.set_text("100%")
        player_hp_text.set_style_text_color(lv.color_hex(0xEEEEEE), 0)
        player_hp_text.set_style_text_font(lv.font_montserrat_12, 0)
        player_hp_text.set_pos(player_hp_bar_x + hp_bar_len + 4, player_hp_bar_y)
        self.ui_elements["player_hp_text"] = player_hp_text

    def _create_battle_log(self, parent, width, height, x_pos=0, y_pos=0):
        """Create battle log area."""
        log_container = lv.obj(parent)
        log_container.set_size(width, height)
        log_container.set_pos(x_pos, y_pos)
        log_container.set_style_bg_color(lv.color_hex(0x0A0A1A), 0)
        log_container.set_style_border_width(0, 0)
        log_container.set_style_radius(2, 0)
        log_container.set_style_pad_all(4, 0)
        self.ui_elements["log_container"] = log_container

        log_label = lv.label(log_container)
        log_label.set_text("Battle start!")
        log_label.set_width(width - 8)
        log_label.set_style_text_color(lv.color_hex(0xAAAA00), 0)
        log_label.set_style_text_font(lv.font_montserrat_12, 0)
        # Wrap long text and keep left aligned so multi-line logs render cleanly
        if hasattr(lv.label, "LONG"):
            log_label.set_long_mode(lv.label.LONG.WRAP)
        else:
            log_label.set_long_mode(0)  # Fallback constant
        log_label.set_style_text_align(lv.TEXT_ALIGN.LEFT, 0)
        self.ui_elements["battle_log"] = log_label

    def _create_action_area(self, screen_w, y_start, height):
        """Create action area with turn indicator, battle log, and move buttons."""
        action_container = lv.obj(self.screen)
        action_container.set_size(screen_w, height)
        action_container.set_pos(0, y_start)
        action_container.set_style_bg_color(COLOR_BG_PANEL, 0)
        action_container.set_style_border_width(1, 0)
        action_container.set_style_border_color(lv.color_hex(0x3A3A4E), 0)
        action_container.set_style_radius(4, 0)
        action_container.set_style_pad_all(4, 0)
        self.ui_elements["action_container"] = action_container

        log_width = max(120, screen_w // 2 - 40)
        log_height = height - 8
        self._create_battle_log(action_container, log_width, log_height, 4, 4)

        # Right column for turn info and moves
        moves_container = lv.obj(action_container)
        moves_container_width = screen_w - log_width - 12
        moves_container.set_size(moves_container_width, log_height)
        moves_container.set_pos(log_width - 4, -8)
        moves_container.set_style_bg_color(lv.color_hex(0x000000), 0)
        if hasattr(lv, "OPA"):
            moves_container.set_style_bg_opa(lv.OPA.TRANSP, 0)
        moves_container.set_style_border_width(0, 0)
        moves_container.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["moves_container"] = moves_container


        # --- Move buttons container (top of moves area, 2x2 grid) ---
        # Place move buttons first (they'll be at the top)
        moves_x = 0
        moves_y = 0
        btn_w = (moves_container_width - 4) // 2
        btn_h = 30
        gap = 4

        # Button labels: Atk1, Atk2 (top row), Def1, Def2 (bottom row)
        btn_labels = ["Atk1", "Atk2", "Def1", "Def2"]

        # Create 4 placeholder buttons (will be updated with actual moves)
        for row in range(2):
            for col in range(2):
                idx = row * 2 + col
                btn = lv.button(moves_container)
                btn.set_size(btn_w, btn_h)
                btn.set_pos(
                    moves_x + col * (btn_w + gap), moves_y + row * (btn_h + gap)
                )

                is_defense = idx >= 2
                border_color = lv.color_hex(0x3388FF) if is_defense else lv.color_hex(0xFF3333)
                text_color = border_color

                # Theme colors: dark bg, red offense / blue defense accents
                btn.set_style_bg_color(lv.color_hex(0x2A2A2A), 0)
                btn.set_style_bg_color(lv.color_hex(0x3A3A3A), lv.STATE.PRESSED)
                btn.set_style_border_color(border_color, 0)
                btn.set_style_border_width(1, 0)
                btn.set_style_radius(4, 0)

                label = lv.label(btn)
                label.set_width(btn_w - 12)
                if hasattr(lv.label, "LONG"):
                    label.set_long_mode(lv.label.LONG.SCROLL_CIRCULAR)
                else:
                    label.set_long_mode(0)  # Fallback for bindings without LONG enum
                label.set_text(btn_labels[idx])
                label.center()
                label.set_style_text_color(text_color, 0)
                label.set_style_text_font(lv.font_montserrat_12, 0)

                btn.add_event_cb(self._on_move_clicked, lv.EVENT.CLICKED, None)
                self.move_buttons.append(btn)
                self.button_to_move_id[id(btn)] = idx  # Default mapping

        # --- Turn indicator row (horizontal) - now below move buttons ---
        turn_label = lv.label(moves_container)
        turn_label.set_text("YOUR TURN")
        turn_label.set_style_text_color(COLOR_YOUR_TURN, 0)
        turn_label.set_style_text_font(lv.font_montserrat_12, 0)
        turn_label.set_pos(4, 68)  # Position below move buttons (4 + 2*30 + 2*4 gap)
        self.ui_elements["turn_indicator"] = turn_label

        # Calculate x offset for timeout bar (right of turn_label)
        turn_label_w = 80  # Estimate width, adjust if needed
        timeout_bar_x = 4 + turn_label_w + 8
        timeout_bar_y = 68  # Match turn label y position
        timeout_bar = lv.bar(moves_container)
        timeout_bar.set_size(60, 8)
        timeout_bar.set_pos(timeout_bar_x, timeout_bar_y)
        timeout_bar.set_range(0, 100)
        timeout_bar.set_value(100, False)
        timeout_bar.set_style_bg_color(lv.color_hex(0x333333), 0)
        timeout_bar.set_style_bg_color(COLOR_TIMEOUT_BAR, lv.PART.INDICATOR)
        timeout_bar.set_style_radius(2, 0)
        timeout_bar.set_style_radius(2, lv.PART.INDICATOR)
        self.ui_elements["timeout_bar"] = timeout_bar

        # Timeout text to the right of timeout bar
        timeout_text_x = timeout_bar_x + 60
        timeout_text_y = 66  # Match bar baseline
        timeout_text = lv.label(moves_container)
        timeout_text.set_text("20s")
        timeout_text.set_pos(timeout_text_x, timeout_text_y)
        timeout_text.set_style_text_color(lv.color_hex(0x888888), 0)
        timeout_text.set_style_text_font(lv.font_montserrat_12, 0)
        self.ui_elements["timeout_text"] = timeout_text

        # Status message (shown when waiting) - position below turn indicator
        status_msg = lv.label(moves_container)
        status_msg.set_text("Waiting...")
        status_msg.set_pos(4, 86)  # Below turn indicator
        status_msg.set_style_text_color(COLOR_WAITING, 0)
        status_msg.set_style_text_font(lv.font_montserrat_12, 0)
        status_msg.add_flag(lv.obj.FLAG.HIDDEN)
        self.ui_elements["status_message"] = status_msg

    def _create_move_buttons(self, moves):
        """Update move buttons with actual moves."""
        # Clear mapping
        self.button_to_move_id = {}

        for i, move in enumerate(moves[:4]):  # Max 4 moves
            if i >= len(self.move_buttons):
                break

            btn = self.move_buttons[i]

            # Get move id
            if hasattr(move, "id"):
                move_id = move.id
            else:
                move_id = move.get("id", i)

            # Set button label to move name (trim to fit)
            label_text = getattr(move, "name", None) or move.get("name", "Move")
            label_text = label_text[:16]  # accommodate longer move names on wider buttons
            for child_idx in range(btn.get_child_count()):
                child = btn.get_child(child_idx)
                if hasattr(child, "set_text"):
                    child.set_text(label_text)
                    break

            # Update button color based on move category
            if hasattr(move, "category"):
                is_defense = move.category in (MOVE_CAT_SUPPORT, MOVE_CAT_RECOVERY)
            else:
                is_defense = False
            border_color = lv.color_hex(0x3388FF) if is_defense else lv.color_hex(0xFF3333)
            for child_idx in range(btn.get_child_count()):
                child = btn.get_child(child_idx)
                if hasattr(child, "set_style_text_color"):
                    child.set_style_text_color(border_color, 0)
                    break
            btn.set_style_border_color(border_color, 0)

            # Map button to move_id (using id() as key since we can't use set_user_data)
            self.button_to_move_id[id(btn)] = move_id
            btn.remove_flag(lv.obj.FLAG.HIDDEN)

        # Hide unused buttons
        for i in range(len(moves), len(self.move_buttons)):
            self.move_buttons[i].add_flag(lv.obj.FLAG.HIDDEN)

        self.available_moves = moves

    def _create_default_move_buttons(self):
        """Create default move buttons."""
        default_moves = []
        for mid in [0, 1, 2, 3]:
            move = get_move(mid)
            if move:
                default_moves.append(move)

        if default_moves:
            self._create_move_buttons(default_moves)
        else:
            self._create_move_buttons(
                [
                    {"id": 0, "name": "Tackle"},
                    {"id": 1, "name": "Byte"},
                    {"id": 2, "name": "Patch"},
                    {"id": 3, "name": "Firewall"},
                ]
            )

    def _update_hp_bar(self, bar_key, text_key, current_hp, max_hp):
        """Update HP bar with color coding."""
        if bar_key not in self.ui_elements:
            return

        hp_percent = int((current_hp / max_hp) * 100) if max_hp > 0 else 0
        hp_bar = self.ui_elements[bar_key]

        hp_bar.set_value(hp_percent, True)

        # Color based on HP
        if hp_percent > 50:
            color = COLOR_HP_FULL
        elif hp_percent > 25:
            color = COLOR_HP_MEDIUM
        else:
            color = COLOR_HP_LOW

        hp_bar.set_style_bg_color(color, lv.PART.INDICATOR)

        if text_key in self.ui_elements:
            self.ui_elements[text_key].set_text(str(hp_percent) + "%")

    def _update_turn_ui(self, is_our_turn, message=None):
        """Update UI based on turn state."""
        self.is_our_turn = is_our_turn
        can_select_move = (
            is_our_turn
            and not self.move_inflight
            and self.ui_state != BATTLE_UI_RESULT
        )

        if "turn_indicator" in self.ui_elements:
            indicator = self.ui_elements["turn_indicator"]
            if is_our_turn:
                indicator.set_text("YOUR TURN")
                indicator.set_style_text_color(COLOR_YOUR_TURN, 0)
            else:
                indicator.set_text("WAITING")
                indicator.set_style_text_color(COLOR_WAITING, 0)

        # Show/hide move buttons
        for btn in self.move_buttons:
            if can_select_move:
                btn.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                btn.add_flag(lv.obj.FLAG.HIDDEN)

        # Status message
        if "status_message" in self.ui_elements:
            status = self.ui_elements["status_message"]
            if is_our_turn and not self.move_inflight:
                status.add_flag(lv.obj.FLAG.HIDDEN)
            else:
                if message:
                    status.set_text(message)
                status.remove_flag(lv.obj.FLAG.HIDDEN)

        # Timeout bar
        if "timeout_bar" in self.ui_elements:
            if is_our_turn and not self.move_inflight:
                self.ui_elements["timeout_bar"].remove_flag(lv.obj.FLAG.HIDDEN)
                self.ui_elements["timeout_text"].remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                self.ui_elements["timeout_bar"].add_flag(lv.obj.FLAG.HIDDEN)
                self.ui_elements["timeout_text"].add_flag(lv.obj.FLAG.HIDDEN)

    def _update_timeout_bar(self):
        """Update timeout countdown."""
        if not self.is_our_turn or self.move_inflight:
            return

        elapsed = time.ticks_diff(time.ticks_ms(), self.turn_start_time)
        remaining_ms = self.timeout_ms - elapsed

        if remaining_ms <= 0:
            self._on_move_timeout()
            return

        percent = int((remaining_ms / self.timeout_ms) * 100)
        if "timeout_bar" in self.ui_elements:
            self.ui_elements["timeout_bar"].set_value(percent, False)

        remaining_sec = remaining_ms // 1000
        if "timeout_text" in self.ui_elements:
            self.ui_elements["timeout_text"].set_text(str(remaining_sec) + "s")

    def on_show(self):
        """Initialize battle state when shown."""
        self.logger.info("Battle screen shown")
        self.show_spinner("Loading battle assets...")
        self.ui_state = BATTLE_UI_INIT
        self.move_inflight = False
        self.battle_log_messages = []
        self.turn_start_time = 0
        self.ready_to_play = False
        self._clear_battle_result_ui()
        self._clear_dynamic_icons()

        # Evict cached sprites only if we're low on RAM; keep active sprites when possible.
        if gc.mem_free() < 200000:
            keep_paths = []
            if self.battle_manager and getattr(self.battle_manager, "player_character", None):
                keep_paths.append(getattr(self.battle_manager.player_character, "sprite_path", None))
            evict_sprite_cache(keep_paths=keep_paths, max_age_ms=None, min_free_percent=20)

        try:
            # Sync from battle manager
            self._sync_from_battle_manager()

            # Update HP bars
            self._update_hp_bar(
                "player_hp_bar", "player_hp_text", self.player_hp, self.player_max_hp
            )
            self._update_hp_bar(
                "opponent_hp_bar",
                "opponent_hp_text",
                self.opponent_hp,
                self.opponent_max_hp,
            )

            # Wait for readiness handshake before enabling turn UI
            self._update_turn_ui(is_our_turn=False, message="Syncing battle...")
        finally:
            if self.battle_manager:
                self.battle_manager.mark_ui_ready()
            self.hide_spinner()

    def _sync_from_battle_manager(self):
        """Sync state from BattleManager."""
        if not self.battle_manager:
            self._create_default_move_buttons()
            return

        battle_info = self.battle_manager.get_battle_info()
        if battle_info:
            self.opponent_name = battle_info.get("opponent_name", "Opponent")
            self.player_name = battle_info.get("player_name", "Player")
            self.player_hp = battle_info.get("player_hp", 100)
            self.player_max_hp = battle_info.get("player_max_hp", 100)
            self.opponent_hp = battle_info.get("opponent_hp", 100)
            self.opponent_max_hp = battle_info.get("opponent_max_hp", 100)
            self.player_character_name = battle_info.get(
                "player_character_name", self.player_character_name
            )
            self.opponent_character_name = battle_info.get(
                "opponent_character_name", self.opponent_character_name
            )

            # Update labels
            if "opponent_name" in self.ui_elements:
                self.ui_elements["opponent_name"].set_text(self.opponent_name[:10])
            if "player_name" in self.ui_elements:
                self.ui_elements["player_name"].set_text(self.player_name[:10])
            if "opponent_type" in self.ui_elements:
                self.ui_elements["opponent_type"].set_text(
                    self.opponent_character_name
                )
            if "player_type" in self.ui_elements:
                self.ui_elements["player_type"].set_text(
                    self.player_character_name
                )

            # Get moves
            move_ids = battle_info.get("player_moves", [0, 1, 2, 3])
            moves = []
            for mid in move_ids:
                move = get_move(mid)
                if move:
                    moves.append(move)
            if moves:
                self._create_move_buttons(moves)
            else:
                self._create_default_move_buttons()
            # Load scaled icons for player/opponent
            self._set_icon_from_sprite(
                "player_sprite",
                battle_info.get("player_sprite_path"),
                battle_info.get("player_sprite_meta", {}),
            )
            self._set_icon_from_sprite(
                "opponent_sprite",
                battle_info.get("opponent_sprite_path"),
                battle_info.get("opponent_sprite_meta", {}),
            )
        else:
            self.logger.warning("No battle info - using defaults")
            self._create_default_move_buttons()
            self._load_default_icons()

    def _on_move_clicked(self, event):
        """Handle move button click."""
        if self.ui_state == BATTLE_UI_RESULT:
            return
        if self.battle_manager and (
            self.battle_manager.last_battle_result or self.battle_manager.pending_battle_result
        ):
            return
        if not self.is_our_turn or self.move_inflight:
            return

        btn = event.get_target_obj()

        # Get move_id from our mapping (LVGL 9.x can't use set_user_data with int)
        move_id = self.button_to_move_id.get(id(btn), 0)

        self.logger.info("Player selected move " + str(move_id))
        self.move_inflight = True

        self._update_turn_ui(is_our_turn=False, message="Move selected!")
        self.ui_state = BATTLE_UI_WAITING
        self.show_spinner("Sending move...")
        self.move_send_started_ms = time.ticks_ms()

        move = get_move(move_id)
        if move:
            pass

        if self.battle_manager:
            success = self.battle_manager.use_move(move_id)
            if not success:
                self.logger.error("Failed to use move")
                self.add_battle_log("Error sending move!")
                self.move_inflight = False
                self.move_send_started_ms = None
                self._update_turn_ui(is_our_turn=True)

    def _on_move_timeout(self):
        """Handle move selection timeout."""
        self.logger.warning("Move selection timed out!")
        self.add_battle_log("Time's up! Auto-select.")

        if self.available_moves:
            if hasattr(self.available_moves[0], "id"):
                default_move = self.available_moves[0].id
            else:
                default_move = self.available_moves[0].get("id", 0)
        else:
            default_move = 0

        self.move_inflight = True
        self._update_turn_ui(is_our_turn=False, message="Timeout!")
        self.show_spinner("Sending move...")
        self.move_send_started_ms = time.ticks_ms()

        if self.battle_manager:
            self.battle_manager.use_move(default_move)

    def _create_exit_button(self):
        """Create exit button in action area for post-battle."""
        if "exit_btn" in self.ui_elements:
            return  # Already exists

        action_container = self.ui_elements.get("action_container")
        if not action_container:
            return

        # Position exit button where move buttons were (right side)
        exit_btn = lv.button(action_container)
        exit_btn.set_size(60, 30)
        exit_btn.set_pos(228, 12)  # Right side of action area

        # Style: green border on dark background
        exit_btn.set_style_bg_color(lv.color_hex(0x2A4A2A), 0)
        exit_btn.set_style_bg_color(lv.color_hex(0x3A5A3A), lv.STATE.PRESSED)
        exit_btn.set_style_border_color(lv.color_hex(0x00FF00), 0)
        exit_btn.set_style_border_width(2, 0)
        exit_btn.set_style_radius(6, 0)

        label = lv.label(exit_btn)
        label.set_text("EXIT")
        label.center()
        label.set_style_text_color(lv.color_hex(0x00FF00), 0)
        label.set_style_text_font(lv.font_montserrat_14, 0)

        exit_btn.add_event_cb(self._on_exit_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements["exit_btn"] = exit_btn

    def _on_exit_clicked(self, event):
        """Handle exit button click after battle."""
        self.logger.info("Exit button clicked")
        self.show_spinner("Leaving battle...")

        if not self.game_ui:
            return

        # Show detailed battle result screen (uses battle_manager.last_battle_result)
        self.game_ui.show_panel("battle_result")

    def create_ui(self):
        """Create landscape battle UI for 320x240."""
        self.logger.debug("BattlePanel.create_ui() starting...")
        screen_w, screen_h = get_screen_size(self.screen)
        self.logger.debug(f"  Screen size: {screen_w}x{screen_h}")

        # Screen background
        self.screen.set_style_bg_color(COLOR_BG_DARK, 0)

        # Layout constants for 320x240
        ACTION_AREA_H = 100  # Turn indicator + move buttons + log
        STAGE_AREA_H = screen_h - ACTION_AREA_H  # Battle stage height

        # === BATTLE STAGE ===
        self._create_combatant_areas(screen_w, STAGE_AREA_H)

        # === BOTTOM: Log + Action Area ===
        self._create_action_area(screen_w, STAGE_AREA_H, ACTION_AREA_H)

        # Initial state
        self._update_turn_ui(is_our_turn=False, message="Battle starting...")

        self.logger.debug("BattlePanel.create_ui() complete")

    def add_battle_log(self, message):
        """Add message to battle log."""
        self.battle_log_messages.append(message)
        if len(self.battle_log_messages) > self.max_log_messages:
            self.battle_log_messages.pop(0)

        if "battle_log" in self.ui_elements:
            log_text = "\r\n".join(self.battle_log_messages)
            self.ui_elements["battle_log"].set_text(log_text)

    def update(self):
        """Update battle screen (called each frame)."""
        if not self.battle_manager:
            return

        # Check if battle ended
        if self.battle_manager.last_battle_result:
            # Terminal result exists: always clear any transient "sending/waiting" spinner state.
            self.move_inflight = False
            self.move_send_started_ms = None
            self.hide_spinner()
            return

        # Sync HP
        battle_info = self.battle_manager.get_battle_info()
        if battle_info:
            new_player_hp = battle_info.get("player_hp", self.player_hp)
            new_opponent_hp = battle_info.get("opponent_hp", self.opponent_hp)

            if new_player_hp != self.player_hp or new_opponent_hp != self.opponent_hp:
                self.player_hp = new_player_hp
                self.opponent_hp = new_opponent_hp
                self._update_hp_bar(
                    "player_hp_bar",
                    "player_hp_text",
                    self.player_hp,
                    self.player_max_hp,
                )
                self._update_hp_bar(
                    "opponent_hp_bar",
                    "opponent_hp_text",
                    self.opponent_hp,
                    self.opponent_max_hp,
                )

        # Check waiting state
        if self.battle_manager.waiting_for_opponent:
            if self.ui_state != BATTLE_UI_WAITING:
                self.ui_state = BATTLE_UI_WAITING
                self._update_turn_ui(
                    is_our_turn=False, message="Waiting for opponent..."
                )
        elif self.move_inflight:
            # Move was selected, opponent responded - back to selecting
            self.move_inflight = False
            self.move_send_started_ms = None
            self.ui_state = BATTLE_UI_SELECTING
            self.turn_start_time = time.ticks_ms()
            self._update_turn_ui(is_our_turn=True, message="YOUR TURN")

        # Guard the race where a terminal result arrives while send spinner is up.
        # If that spinner has overstayed and result data is present, drop the overlay
        # so the received result can surface immediately.
        if self.move_inflight and self.move_send_started_ms is not None:
            elapsed = time.ticks_diff(time.ticks_ms(), self.move_send_started_ms)
            if elapsed >= MOVE_SEND_SPINNER_TIMEOUT_MS:
                if self.battle_manager.last_battle_result or self.battle_manager.pending_battle_result:
                    self.logger.warning(
                        "Move-send spinner timeout with terminal result present; clearing wait overlay"
                    )
                    self.move_inflight = False
                    self.move_send_started_ms = None
                    self.hide_spinner()

        # Check if handshake is complete but turn hasn't started yet
        # This handles the race condition where start_turn() was called before
        # this panel was set as current_panel_obj in graphics.py
        handshake_complete = getattr(self.battle_manager, "ready_handshake_complete", False)
        if (handshake_complete and
            not self.battle_manager.waiting_for_opponent and
            not self.move_inflight and
            self.ui_state != BATTLE_UI_SELECTING and
            not self.is_our_turn):
            # Handshake completed but we never got start_turn() - trigger it now
            self.logger.info("Handshake complete, starting turn from update()")
            self.start_turn(self.battle_manager._compute_effective_turn_timeout_ms())

        waiting_for_response = (
            self.battle_manager.waiting_for_opponent or self.move_inflight
        )
        if not getattr(self.battle_manager, "ready_handshake_complete", True):
            self.show_spinner("Syncing battle...")
        elif waiting_for_response:
            self.show_spinner("Waiting for opponent...")
        else:
            self.hide_spinner()

        # Update timeout
        if self.ui_state == BATTLE_UI_SELECTING:
            self._update_timeout_bar()

    def on_hide(self):
        """Cleanup when leaving."""
        self.logger.info("Battle screen hidden")
        self._clear_battle_result_ui()
        self.button_to_move_id = {}
        self._clear_dynamic_icons()
        self.hide_spinner()
        self.ready_to_play = False

    def _clear_battle_result_ui(self):
        """Reset any battle-end UI state so it doesn't persist into the next battle."""
        if "exit_btn" in self.ui_elements:
            try:
                self.ui_elements["exit_btn"].delete()
            except Exception:
                pass
            self.ui_elements.pop("exit_btn", None)

        if "result_status" in self.ui_elements:
            try:
                self.ui_elements["result_status"].delete()
            except Exception:
                pass
            self.ui_elements.pop("result_status", None)

        if "status_message" in self.ui_elements:
            status = self.ui_elements["status_message"]
            status.set_text("Waiting...")
            status.set_style_text_color(COLOR_WAITING, 0)
            status.add_flag(lv.obj.FLAG.HIDDEN)

    def start_turn(self, timeout_ms=None):
        """Start a new turn."""
        self.is_our_turn = True
        self.move_inflight = False
        self.move_send_started_ms = None
        self.timeout_ms = timeout_ms or config.BATTLE_MOVE_TIMEOUT_MS
        self.turn_start_time = time.ticks_ms()
        self.ui_state = BATTLE_UI_SELECTING
        self.ready_to_play = True
        self._update_turn_ui(is_our_turn=True)
        self.add_battle_log("Choose your move!")
        self.hide_spinner()

    def on_back_pressed(self):
        """Back button - forfeit battle."""
        self.logger.info("Back pressed during battle")

        if self.battle_manager:
            self.battle_manager.forfeit_battle()

        super().on_back_pressed()

        return True

    def on_battle_end(self, winner, result_data=None):
        """
        Called when battle ends - shows results inline on battle screen.

        Args:
            winner: 0=draw, 1=player won, 2=opponent won
            result_data: Optional dict with 'exp_gained', 'voided', 'error'
        """
        self.ui_state = BATTLE_UI_RESULT
        result_data = result_data or {}
        self.is_our_turn = False
        self.move_inflight = False
        self.move_send_started_ms = None
        self.hide_spinner()

        # Refresh final HP snapshot (prefer values passed in result_data)
        if "player_hp_end" in result_data or "opponent_hp_end" in result_data:
            self.player_hp = result_data.get("player_hp_end", self.player_hp)
            self.opponent_hp = result_data.get("opponent_hp_end", self.opponent_hp)
            self.player_max_hp = result_data.get("player_max_hp", self.player_max_hp)
            self.opponent_max_hp = result_data.get("opponent_max_hp", self.opponent_max_hp)
        elif self.battle_manager:
            info = self.battle_manager.get_battle_info()
            if info:
                self.player_hp = info.get("player_hp", self.player_hp)
                self.opponent_hp = info.get("opponent_hp", self.opponent_hp)
                self.player_max_hp = info.get("player_max_hp", self.player_max_hp)
                self.opponent_max_hp = info.get("opponent_max_hp", self.opponent_max_hp)

        # Apply HP bars/text
        self._update_hp_bar(
            "player_hp_bar",
            "player_hp_text",
            self.player_hp,
            self.player_max_hp,
        )
        self._update_hp_bar(
            "opponent_hp_bar",
            "opponent_hp_text",
            self.opponent_hp,
            self.opponent_max_hp,
        )

        # Determine result text
        if result_data.get("voided"):
            result_text = "BATTLE VOID"
            result_color = lv.color_hex(0xFF6666)  # Light red
            log_msg = f"Battle voided: {result_data.get('error', 'Unknown error')}"
        elif winner == 1:
            result_text = "VICTORY!"
            result_color = lv.color_hex(0x00FF00)  # Green
            log_msg = f"You win! +{result_data.get('exp_gained', 0)} XP"
        elif winner == 2:
            result_text = "DEFEAT"
            result_color = lv.color_hex(0xFF4444)  # Red
            log_msg = f"You lost! +{result_data.get('exp_gained', 0)} XP"
        else:
            result_text = "DRAW"
            result_color = lv.color_hex(0xFFAA00)  # Orange
            log_msg = "Battle ended in a draw!"

        # Add result to battle log so player sees final state
        self.add_battle_log(log_msg)

        # Hide all move buttons
        for btn in self.move_buttons:
            btn.add_flag(lv.obj.FLAG.HIDDEN)

        # Hide timeout elements
        if "timeout_bar" in self.ui_elements:
            self.ui_elements["timeout_bar"].add_flag(lv.obj.FLAG.HIDDEN)
        if "timeout_text" in self.ui_elements:
            self.ui_elements["timeout_text"].add_flag(lv.obj.FLAG.HIDDEN)

        # Create separate result status text (victory/defeat) at top of action area
        moves_container = self.ui_elements.get("moves_container")
        if moves_container:
            result_status = lv.label(moves_container)
            result_status.set_text(result_text)
            result_status.set_style_text_color(result_color, 0)
            result_status.set_style_text_font(lv.font_montserrat_14, 0)
            result_status.set_pos(4, 12)  # Top left, same line as exit button
            self.ui_elements["result_status"] = result_status

        # Show status message with final HP
        if "status_message" in self.ui_elements:
            status = self.ui_elements["status_message"]
            final_hp_text = f"HP: You {self.player_hp} / Opp {self.opponent_hp}"
            status.set_text(final_hp_text)
            status.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
            status.remove_flag(lv.obj.FLAG.HIDDEN)

        # Create Exit button in the action area (where move buttons were)
        self._create_exit_button()

        self.logger.info(f"Battle ended: winner={winner}, result={result_text}")

    def _load_default_icons(self):
        """Show icons when no live battle data is available."""
        try:
            player_char = get_character(config.PLAYER_CHARACTER_ID)
        except Exception as e:
            self.logger.debug(f"Default icon load failed: {e}")
            player_char = None
        if player_char:
            self._set_icon_from_sprite(
                "player_sprite",
                player_char.sprite_path,
                player_char.extra.get("sprite_meta", {}),
            )

    def _set_icon_from_sprite(self, container_key, sprite_path, sprite_meta):
        """Render a scaled sprite frame into the small icon container or show a placeholder."""
        container = self.ui_elements.get(container_key)
        if not container:
            return

        if not sprite_path:
            self._set_placeholder_icon(container)
            return
        if self._icon_sprite_paths.get(container_key) == sprite_path and self._icon_images.get(container_key):
            return

        img = self._set_icon_on_container(
            container,
            sprite_path,
            sprite_meta=sprite_meta,
            cache_key=container_key,
            img_store=self._icon_images,
            dsc_store=self._icon_img_dsc,
            data_store=self._icon_img_data,
        )
        if not img:
            self.logger.debug(f"Icon load failed ({sprite_path})")
            self._set_placeholder_icon(container)
        else:
            self._icon_sprite_paths[container_key] = sprite_path

    def _set_placeholder_icon(self, container):
        """Show a simple placeholder when no sprite is available."""
        try:
            if hasattr(container, "clean"):
                container.clean()
        except Exception:
            pass
        placeholder = lv.label(container)
        placeholder.set_text("?")
        placeholder.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        placeholder.center()

    def _clear_dynamic_icons(self):
        """Delete dynamic icon images to avoid stacking and free memory."""
        for img in list(self._icon_images.values()):
            try:
                img.delete()
            except Exception:
                pass
        self._icon_sprites = {}
        self._icon_images = {}
        self._icon_img_dsc = {}
        self._icon_img_data = {}
        self._icon_sprite_paths = {}

        for key in ("player_sprite", "opponent_sprite"):
            container = self.ui_elements.get(key)
            if not container:
                continue
            try:
                if hasattr(container, "clean"):
                    container.clean()
            except Exception:
                pass
