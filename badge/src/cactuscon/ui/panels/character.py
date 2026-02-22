"""Character panel - Home screen with virtual pet view (Digimon-style)."""

import lvgl as lv
import time

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon import config
from cactuscon.game.engine.characters import (
    XP_BASE_LEVEL,
    CharacterStats,
    get_character,
    get_care_state,
    get_total_xp_for_level,
    get_xp_for_level,
    get_creature_stats,
    get_player_pack,
    EVOLVE_REQUIRED_LEVEL,
)
from cactuscon.prefs import prefs
from cactuscon.ui.sprites import LVGLImage, LVGLSpriteActor, evict_sprite_cache


class CharacterPanel(BasePanel):
    """
    Home screen - Virtual pet character view (Digimon-style).
    
    This is the default landing panel. Shows:
    - Control panel with Menu/Evo/Care/Pack buttons
    - Character sprite in center-right
    - Stats (name, level, HP, ATK, DEF) below control panel
    - XP bar at bottom 
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default state so UI can render even before prefs load
        self.character_id = getattr(config, "PLAYER_CHARACTER_ID", "deeno")
        self.character_name = "Unknown"
        self.level = 1
        self.xp_total = 0
        self.xp_into_level = 0
        self.xp_needed = XP_BASE_LEVEL
        self.base_stats = CharacterStats()
        self.sprite_path = None
        self.char_image = None  # LVGLImage
        self.char_actor = None  # LVGLSpriteActor for animation
        self.sprite_meta = None  # dict with frame_width, frame_height, frames_per_row, num_frames
        self.care_state = {}
        # Wander state
        self._wander_dir = 1
        self._wander_last_ms = 0
        self._wander_bounds = (0, 0)
        self._wander_x = 0
        self._wander_y_dir = -1
        self._wander_y_bounds = (0, 0)
        self._wander_y = 0
    
    def create_ui(self):
        """Create character panel UI with Digimon-style layout."""
        self._load_character_data()

        # Set screen background
        self.screen.set_style_bg_color(lv.color_black(), 0)
        
        # Disable scrolling on screen
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)
        

        # === CHARACTER AREA (center) ===
        self._create_character_area()

        # === CONTROL PANEL (top) ===
        self._create_control_panel()

        # === STATS AREA (below control panel) ===
        self._create_stats_area()
        
        # === XP BAR (bottom) ===
        self._create_xp_bar()
    
    def _create_control_panel(self):
        """Create control panel with Menu, Evo, Care, Pack buttons."""
        # Control panel background
        ctrl_panel = lv.obj(self.screen)
        ctrl_panel.set_size(320, 40)
        ctrl_panel.set_pos(0, 0)
        ctrl_panel.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        ctrl_panel.set_style_border_width(0, 0)
        ctrl_panel.set_style_border_color(lv.color_hex(0x333333), lv.PART.MAIN)
        ctrl_panel.set_style_border_side(lv.BORDER_SIDE.BOTTOM, 0)
        ctrl_panel.set_style_border_width(1, 0)
        ctrl_panel.set_style_pad_all(0, 0)
        ctrl_panel.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements['ctrl_panel'] = ctrl_panel
        
        # Button dimensions and spacing
        BTN_WIDTH = 70
        BTN_HEIGHT = 32
        BTN_Y = 4
        BTN_SPACING = 78  # Width + gap
        
        # Menu button (leftmost - opens main menu)
        btn_menu = self._create_ctrl_button("Menu", 5, BTN_Y, BTN_WIDTH, BTN_HEIGHT)
        btn_menu.add_event_cb(self._on_menu_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_menu'] = btn_menu
        
        # Evo button (Evolution details)
        btn_evo = self._create_ctrl_button("Evo", 5 + BTN_SPACING, BTN_Y, BTN_WIDTH, BTN_HEIGHT)
        btn_evo.add_event_cb(self._on_evo_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_evo'] = btn_evo
        
        # Care button (Feed, play, colors)
        btn_care = self._create_ctrl_button("Care", 5 + BTN_SPACING * 2, BTN_Y, BTN_WIDTH, BTN_HEIGHT)
        btn_care.add_event_cb(self._on_care_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_care'] = btn_care
        
        # Pack button (Change hacktarmon, achievements)
        btn_pack = self._create_ctrl_button("Pack", 5 + BTN_SPACING * 3, BTN_Y, BTN_WIDTH, BTN_HEIGHT)
        btn_pack.add_event_cb(self._on_pack_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_pack'] = btn_pack
    
    def _create_ctrl_button(self, text, x, y, width, height):
        """Create a styled control panel button."""
        btn = lv.button(self.screen)
        btn.set_size(width, height)
        btn.set_pos(x, y)
        btn.set_style_bg_color(lv.color_hex(0x2a2a2a), 0)
        btn.set_style_bg_color(lv.color_hex(0x3a3a3a), lv.STATE.PRESSED)
        btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn.set_style_border_width(1, 0)
        btn.set_style_radius(4, 0)
        btn.set_style_pad_all(0, 0)
        
        label = lv.label(btn)
        label.set_text(text)
        label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        label.center()
        
        return btn
    
    def _create_stats_area(self):
        """Create stats display below control panel."""
        STATS_Y = 45  # Below control panel
        
        # Evolution name (top left)
        name_label = lv.label(self.screen)
        name_label.set_text(self.character_name)
        name_label.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        name_label.set_pos(10, STATS_Y)
        self.ui_elements['name_label'] = name_label

        # Status icons (buffs) to the right of name
        act_icon = lv.label(self.screen)
        act_icon.set_text("")
        act_icon.set_style_text_color(lv.color_hex(0x33cc33), 0)
        act_icon.set_pos(120, STATS_Y)
        act_icon.add_flag(lv.obj.FLAG.HIDDEN)
        self.ui_elements["activity_icon"] = act_icon

        food_icon = lv.label(self.screen)
        food_icon.set_text("")
        food_icon.set_style_text_color(lv.color_hex(0x33aaff), 0)
        food_icon.set_pos(140, STATS_Y)
        food_icon.add_flag(lv.obj.FLAG.HIDDEN)
        self.ui_elements["food_icon"] = food_icon
        
        # Level (top right, same line as name)
        level_label = lv.label(self.screen)
        level_label.set_text(f"Lv.{self.level}")
        level_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        level_label.align(lv.ALIGN.TOP_RIGHT, -10, STATS_Y)
        self.ui_elements['level_label'] = level_label
        
        # HP (below name)
        hp_label = lv.label(self.screen)
        hp_label.set_text("HP")
        hp_label.set_style_text_color(lv.color_hex(0x888888), 0)
        hp_label.set_pos(10, STATS_Y + 20)
        
        hp_value = lv.label(self.screen)
        hp_value.set_text(str(getattr(self.base_stats, "max_hp", 0)))
        hp_value.set_style_text_color(lv.color_hex(0x00ff00), 0)
        hp_value.set_pos(35, STATS_Y + 20)
        self.ui_elements['hp_value'] = hp_value
        
        # ATK (same line, middle)
        atk_label = lv.label(self.screen)
        atk_label.set_text("ATK")
        atk_label.set_style_text_color(lv.color_hex(0x888888), 0)
        atk_label.set_pos(75, STATS_Y + 20)
        
        atk_value = lv.label(self.screen)
        atk_value.set_text(str(getattr(self.base_stats, "attack", 0)))
        atk_value.set_style_text_color(lv.color_hex(0xff6600), 0)
        atk_value.set_pos(110, STATS_Y + 20)
        self.ui_elements['atk_value'] = atk_value
        
        # DEF (same line, right)
        def_label = lv.label(self.screen)
        def_label.set_text("DEF")
        def_label.set_style_text_color(lv.color_hex(0x888888), 0)
        def_label.set_pos(145, STATS_Y + 20)
        
        def_value = lv.label(self.screen)
        def_value.set_text(str(getattr(self.base_stats, "defense", 0)))
        def_value.set_style_text_color(lv.color_hex(0x6699ff), 0)
        def_value.set_pos(180, STATS_Y + 20)
        self.ui_elements['def_value'] = def_value

        # SPEED (right-most)
        spd_label = lv.label(self.screen)
        spd_label.set_text("SPD")
        spd_label.set_style_text_color(lv.color_hex(0x888888), 0)
        spd_label.set_pos(215, STATS_Y + 20)

        spd_value = lv.label(self.screen)
        spd_value.set_text(str(getattr(self.base_stats, "speed", 0)))
        spd_value.set_style_text_color(lv.color_hex(0xffcc33), 0)
        spd_value.set_pos(250, STATS_Y + 20)
        self.ui_elements["spd_value"] = spd_value
    
    def _create_character_area(self):
        """Create character sprite display area (center-right)."""
        # Create a container that will hold the sprite.
        # The container is sized to the sprite dimensions once known.
        # IMPORTANT: Container needs opaque background for proper sprite movement
        # redrawing. Transparent containers cause trail artifacts when sprites move.
        char_area = lv.obj(self.screen)
        char_area.set_size(0, 0)  # Start with zero size; will resize when sprite loads
        char_area.align(lv.ALIGN.CENTER, 90, 10)
        # Use opaque black background to ensure proper redraw when sprite moves
        char_area.set_style_bg_color(lv.color_hex(0x000000), 0)
        char_area.set_style_bg_opa(lv.OPA.COVER, 0)
        char_area.set_style_border_width(0, 0)
        char_area.set_style_radius(0, 0)
        char_area.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements['char_area'] = char_area

        # Placeholder text (will be replaced with sprite)
        placeholder = lv.label(char_area)
        placeholder.set_text(self.character_name)
        placeholder.set_style_text_color(lv.color_hex(0x444444), 0)
        placeholder.center()
        self.ui_elements['char_placeholder'] = placeholder
    
    def _create_xp_bar(self):
        """Create XP bar at bottom of screen."""
        XP_Y = 220  # Near bottom
        
        # XP bar
        xp_bar = lv.bar(self.screen)
        xp_bar.set_size(300, 18)
        xp_bar.set_pos(10, XP_Y)
        xp_bar.set_range(0, self.xp_needed)
        xp_bar.set_value(self.xp_into_level, False)  # LVGL 9.x: bool for anim
        # Gray background for empty portion
        xp_bar.set_style_bg_color(lv.color_hex(0x333333), 0)
        # Green fill for progress
        xp_bar.set_style_bg_color(lv.color_hex(0x00ff00), lv.PART.INDICATOR)
        xp_bar.set_style_radius(3, 0)
        xp_bar.set_style_radius(3, lv.PART.INDICATOR)
        self.ui_elements['xp_bar'] = xp_bar

        # XP label overlay (centered on bar)
        xp_label = lv.label(xp_bar)
        xp_label.set_text(f"XP {self.xp_into_level}/{self.xp_needed}")
        xp_label.set_style_text_color(lv.color_hex(0xAAAAAA), 0)
        xp_label.set_style_text_font(lv.font_montserrat_14, 0)
        xp_label.center()
        self.ui_elements['xp_label'] = xp_label

    
    def on_show(self):
        """Called when character panel is displayed."""
        self.logger.info("Character panel displayed")
        try:
            self._load_character_data()
        except Exception as e:
            self.logger.error(f"Character data load failed: {e}")
        try:
            self._apply_character_data()
        except Exception as e:
            self.logger.error(f"Character data apply failed: {e}")
        # Start sprite animation if available
        if self.char_actor:
            try:
                self.char_actor.show()
            except Exception as e:
                self.logger.error(f"Sprite actor show failed: {e}")
    
    def on_hide(self):
        """Called when character panel is hidden."""
        self.logger.debug("Character panel hidden")
        if self.char_actor:
            self.char_actor.hide()

    def on_cleanup(self):
        """Cleanup sprite actor and caches on unload."""
        if self.char_actor:
            try:
                self.char_actor.destroy()
            except Exception:
                pass
            self.char_actor = None
        self.char_image = None
        self.sprite_meta = None
        self._loaded_sprite_path = None
    
    def _load_character_data(self):
        """Load character data from prefs into local attributes."""
        # Get active character from player pack
        pack = get_player_pack(prefs)
        character_id = pack.get("active_character", "")
        
        # Fallback to config if no active character
        if not character_id:
            character_id = getattr(config, "PLAYER_CHARACTER_ID", None) or ""
        
        # Get per-creature level/XP stats
        creature_stats = get_creature_stats(prefs, character_id)
        level = creature_stats['level']
        xp_total = creature_stats['xp']
        
        try:
            self.care_state = get_care_state(prefs) or {}
        except Exception as e:
            self.logger.debug(f"Care state load failed: {e}")
            self.care_state = {}

        character = get_character(character_id)
        if not character:
            self.logger.warning(f"Character '{character_id}' not found; using defaults")
            base_stats = CharacterStats()
            name = "Unknown"
            sprite_path = None
            self.sprite_meta = None
        else:
            base_stats = character.base_stats
            name = character.name
            sprite_path = getattr(character, "sprite_path", None)
            self.sprite_meta = getattr(character, "extra", {}).get("sprite_meta")

        self.character_id = character_id
        self.character_name = name
        self.level = level
        self.xp_total = xp_total
        self.xp_needed = get_xp_for_level(level)
        xp_start = get_total_xp_for_level(level)
        self.xp_into_level = max(0, xp_total - xp_start)
        self.base_stats = base_stats
        self.sprite_path = sprite_path

    def _apply_character_data(self):
        """Apply loaded character data to existing UI elements."""
        if 'name_label' in self.ui_elements:
            self.ui_elements['name_label'].set_text(self.character_name)

        if 'level_label' in self.ui_elements:
            self.ui_elements['level_label'].set_text(f"Lv.{self.level}")

        if 'hp_value' in self.ui_elements:
            self.ui_elements['hp_value'].set_text(str(getattr(self.base_stats, "max_hp", 0)))

        if 'atk_value' in self.ui_elements:
            self.ui_elements['atk_value'].set_text(str(getattr(self.base_stats, "attack", 0)))

        if 'def_value' in self.ui_elements:
            self.ui_elements['def_value'].set_text(str(getattr(self.base_stats, "defense", 0)))
        if "spd_value" in self.ui_elements:
            self.ui_elements["spd_value"].set_text(str(getattr(self.base_stats, "speed", 0)))

        # Care status icons
        activity = (self.care_state or {}).get("activity")
        food = (self.care_state or {}).get("food")
        act_icon = self.ui_elements.get("activity_icon")
        food_icon = self.ui_elements.get("food_icon")
        if act_icon:
            if activity:
                act_icon.set_text("A")
                act_icon.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                act_icon.add_flag(lv.obj.FLAG.HIDDEN)
        if food_icon:
            if food:
                food_icon.set_text("F")
                food_icon.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                food_icon.add_flag(lv.obj.FLAG.HIDDEN)

        if 'char_placeholder' in self.ui_elements:
            self.ui_elements['char_placeholder'].set_text(self.character_name)
        self._ensure_character_image()

        xp_bar = self.ui_elements.get('xp_bar')
        if xp_bar:
            xp_bar.set_range(0, self.xp_needed)
            # If at max level, show full bar
            if self.level >= EVOLVE_REQUIRED_LEVEL:
                xp_bar.set_value(self.xp_needed, False)
            else:
                xp_bar.set_value(self.xp_into_level, False)

        xp_label = self.ui_elements.get('xp_label')
        if xp_label:
            # If at max level, show "- / -" instead of actual XP
            if self.level >= EVOLVE_REQUIRED_LEVEL:
                xp_label.set_text("XP - / -")
            else:
                xp_label.set_text(f"XP {self.xp_into_level}/{self.xp_needed}")
            xp_label.center()

    def _ensure_character_image(self):
        """Load and display character image if available."""
        if not self.sprite_path or 'char_area' not in self.ui_elements:
            return

        # Check if character changed - need to reload sprite
        current_loaded_path = getattr(self, '_loaded_sprite_path', None)
        actor_in_fallback = bool(
            self.char_actor and getattr(self.char_actor, "_is_fallback", False)
        )
        if self.char_actor and current_loaded_path == self.sprite_path and not actor_in_fallback:
            return  # Already loaded same character and rendering normally
        if actor_in_fallback:
            self.logger.info(
                "Character sprite actor is in fallback mode; forcing sprite reload"
            )
        
        # Clean up old actor if character changed
        if self.char_actor:
            try:
                self.char_actor.destroy()
            except Exception:
                pass
            self.char_actor = None

        # Keep our sprite cached, evict stale others
        evict_sprite_cache(keep_paths=[self.sprite_path], max_age_ms=None, min_free_percent=20)

        # Heuristic defaults for 4-frame idle grid (64x64, 4 per row)
        sprite = None
        try:
            meta = self.sprite_meta or {}
            fw = meta.get("frame_width")
            fh = meta.get("frame_height")
            fpr = meta.get("frames_per_row", meta.get("frames_per_line", 1))
            nf = meta.get("num_frames", meta.get("frames", 1))
            sprite = LVGLImage(
                self.sprite_path,
                frame_width=fw,
                frame_height=fh,
                frames_per_row=fpr,
                num_frames=nf,
            )
        except Exception as e:
            self.logger.debug(f"Grid sprite load failed, falling back to static: {e}")
            try:
                sprite = LVGLImage(self.sprite_path)
            except Exception as e2:
                self.logger.debug(f"Static sprite load failed: {e2}")
                sprite = None

        if not sprite:
            return

        try:
            # Resize the container to match sprite dimensions
            char_area = self.ui_elements['char_area']
            container_w = sprite.frame_width + 40
            container_h = sprite.frame_height + 10
            char_area.set_size(container_w, container_h)
            start_x = max(0, (container_w - sprite.frame_width) // 2)
            # Create actor positioned within container
            actor = LVGLSpriteActor(char_area, start_x, 0)
            actor.add_action('idle', sprite)
            actor.set_action('idle')
            actor.set_frame_delay(200)
            actor.show()
            self.char_actor = actor
            self._loaded_sprite_path = self.sprite_path  # Track what we loaded
            # Wander within container bounds.
            self._wander_bounds = (0, max(0, container_w - sprite.frame_width))
            self._wander_x = start_x
            self._wander_y_bounds = (0, 0)
            self._wander_y = 0

            # Remove placeholder element entirely if it exists
            if 'char_placeholder' in self.ui_elements:
                placeholder = self.ui_elements.pop('char_placeholder')
                placeholder.delete()
        except Exception as e:
            self.logger.debug(f"Failed to attach sprite actor: {e}")

    # === Event Handlers ===
    
    def _on_menu_clicked(self, event):
        """Open the main menu."""
        self.logger.info("Opening main menu")
        if self.game_ui:
            self.game_ui.show_panel('main_menu')
    
    def _on_evo_clicked(self, event):
        """Open evolution details panel."""
        self.logger.info("Evolution button clicked")
        if self.game_ui:
            self.game_ui.show_panel('character_evo')
    
    def _on_care_clicked(self, event):
        """Open care panel (feed, play, colors)."""
        self.logger.info("Care button clicked")
        if self.game_ui:
            self.game_ui.show_panel('character_care')
    
    def _on_pack_clicked(self, event):
        """Open pack panel (change hacktarmon, achievements)."""
        self.logger.info("Pack button clicked")
        if self.game_ui:
            self.game_ui.show_panel('character_pack')

    def _set_actor_facing(self, direction):
        """Flip sprite based on movement direction (right default)."""
        if not self.char_actor or not self.char_actor.img_obj:
            return
        angle = 0
        if direction < 0:
            angle = 1800  # 180 deg in 0.1 deg units
        try:
            self.char_actor.img_obj.set_angle(angle)
        except Exception:
            # Ignore if transform not supported
            pass

    def update(self):
        """Advance sprite animation (called from GameUI loop)."""
        if self.char_actor and self.char_actor.visible:
            try:
                now = time.ticks_ms()
                # Wander horizontally
                if time.ticks_diff(now, self._wander_last_ms or 0) > 200:
                    step = 2 * self._wander_dir
                    self._wander_x += step
                    low, high = self._wander_bounds
                    if self._wander_x <= low or self._wander_x >= high:
                        self._wander_dir *= -1
                        self._wander_x = max(low, min(high, self._wander_x))
                        self._set_actor_facing(self._wander_dir)
                    # Wander vertically within bounds (no lower than baseline).
                    y_step = 1 * self._wander_y_dir
                    self._wander_y += y_step
                    low_y, high_y = self._wander_y_bounds
                    if self._wander_y <= low_y or self._wander_y >= high_y:
                        self._wander_y_dir *= -1
                        self._wander_y = max(low_y, min(high_y, self._wander_y))
                    self.char_actor.move_to(self._wander_x, self._wander_y)
                    self._wander_last_ms = now

                self.char_actor.update()
            except Exception as e:
                self.logger.debug(f"Sprite actor update failed: {e}")
