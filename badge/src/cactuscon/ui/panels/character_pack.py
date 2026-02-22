"""Pack panel - manage owned characters and achievements."""

import gc
import lvgl as lv

from cactuscon import config
from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.ui.sprites import evict_sprite_cache
from cactuscon.game.engine.characters import (
    get_player_pack,
    set_active_character,
    get_character,
    get_care_state,
)
from cactuscon.prefs import prefs
from cactuscon.game.engine.achievements import (
    Achievements,
    get_achievement_catalog,
    get_achievement_powers,
    get_achievement_icon_path,
)
from cactuscon.application import np as npc  # Use global NeoPixelController instance

class CharacterPackPanel(BasePanel):
    """Standalone pack panel listing characters and achievements."""

    # Item types for modal behavior
    ITEM_TYPE_CREATURE = "creature"
    ITEM_TYPE_ACHIEVEMENT = "achievement"
    ITEM_TYPE_SPECIAL_ITEM = "special_item"

    # Leather color scheme
    COLOR_LEATHER_LIGHT = 0xC4A77D      # Light tan leather (backdrop)
    COLOR_LEATHER_MEDIUM = 0x8B6914    # Medium brown leather (item bg)
    COLOR_LEATHER_DARK = 0x5C4033       # Dark brown leather (borders)
    COLOR_LEATHER_HIGHLIGHT = 0xD4AF37  # Gold accent for active item
    COLOR_TEXT_DARK = 0x2D1F14          # Dark brown text
    COLOR_TEXT_LIGHT = 0xF5DEB3         # Wheat/cream text

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.npc = npc
        self.char_buttons = []
        self.ach_buttons = []
        self.achievements = Achievements()
        self._current_modal_item = None  # Track what's shown in modal
        self._power_status = {"active": {}, "cooldowns": {}}

    def create_ui(self):
        # Light leather background for the whole screen
        self.screen.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_DARK), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        header = lv.label(self.screen)
        header.set_text("Pack")
        header.set_style_text_color(lv.color_hex(self.COLOR_TEXT_LIGHT), 0)
        header.align(lv.ALIGN.TOP_LEFT, 10, 8)
        self.ui_elements["header"] = header

        back_btn = self.create_button(self.screen, "Back", width=60, height=26)
        back_btn.align(lv.ALIGN.TOP_RIGHT, -10, 6)
        back_btn.add_event_cb(self.on_back_pressed, lv.EVENT.CLICKED, None)
        # Style back button for leather theme
        back_btn.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_LIGHT), 0)
        back_btn.set_style_border_color(lv.color_hex(self.COLOR_TEXT_LIGHT), 0)
        back_btn.set_style_text_color(lv.color_hex(self.COLOR_TEXT_DARK), 0)
        self.ui_elements["back_btn"] = back_btn

        grid = lv.obj(self.screen)
        grid.set_size(300, 200)
        grid.set_pos(10, 36)
        if hasattr(lv.FLEX_FLOW, "ROW_WRAP"):
            grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
        else:
            grid.set_flex_flow(lv.FLEX_FLOW.ROW)
        grid.set_style_pad_column(6, 0)
        grid.set_style_pad_row(6, 0)
        grid.set_scroll_dir(lv.DIR.VER)
        grid.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)
        # Leather styling for the grid/pack container
        grid.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_LIGHT), 0)
        grid.set_style_border_color(lv.color_hex(self.COLOR_LEATHER_DARK), 0)
        grid.set_style_border_width(3, 0)
        grid.set_style_radius(8, 0)
        grid.set_style_pad_all(8, 0)
        self.ui_elements["grid"] = grid

        self._needs_refresh = True

    def on_show(self):
        super().on_show()
        if getattr(self, "_needs_refresh", True):
            self._refresh_lists()
            self._needs_refresh = False

    def on_hide(self):
        super().on_hide()
        self._clear_buttons(self.char_buttons)
        self._clear_buttons(self.ach_buttons)
        self.char_buttons = []
        self.ach_buttons = []
        # Ensure refresh on next show (buttons were cleared, need to rebuild)
        self._needs_refresh = True

    # --- helpers ---

    def _clear_buttons(self, buttons):
        for btn in buttons:
            try:
                btn.delete()
            except Exception:
                pass
        self._icon_images = {}
        self._icon_img_dsc = {}
        self._icon_img_data = {}

    def _refresh_lists(self):
        pack = get_player_pack(prefs, default_ids=[getattr(config, "PLAYER_CHARACTER_ID", "")])
        owned_ach = self.achievements.list_owned()
        try:
            self._power_status = self.achievements.get_power_status()
        except Exception:
            self._power_status = {"active": {}, "cooldowns": {}}
        grid = self.ui_elements.get("grid")
        if not grid:
            return

        self._clear_buttons(self.char_buttons)
        self._clear_buttons(self.ach_buttons)
        self.char_buttons = []
        self.ach_buttons = []

        active_char = pack.get("active_character")
        characters = pack.get("characters", [])
        # Evaluate collector achievement whenever pack is refreshed
        self.achievements.collector(pack.get("characters", []))

        achievement_catalog = get_achievement_catalog()
        achievements = [ach for ach in achievement_catalog if ach.get("id") in (owned_ach or [])]

        for cid in characters:
            char = get_character(cid)
            item = self._create_inventory_item(
                grid,
                sprite_path=getattr(char, "sprite_path", None) if char else None,
                sprite_meta=getattr(char, "extra", {}).get("sprite_meta") if char else None,
                highlight=(cid == active_char),
            )

            def _cb(evt, selected_char=char, char_id=cid, is_active=(cid == active_char)):
                # Get bio from extra if available
                char_bio = ""
                if selected_char:
                    extra = getattr(selected_char, "extra", {}) or {}
                    char_bio = extra.get("bio", "A creature in your pack.")
                self._show_item_modal(
                    item_type=self.ITEM_TYPE_CREATURE,
                    item_id=char_id,
                    title=selected_char.name if selected_char else char_id,
                    description=char_bio,
                    can_use=not is_active,
                    use_label="Use" if not is_active else None,
                )

            item.add_event_cb(_cb, lv.EVENT.CLICKED, None)
            self.char_buttons.append(item)

        for ach in achievements:
            ach_id = ach.get("id")
            action = ach.get("action")
            can_use = action and action != "info"
            active_ms = (self._power_status.get("active") or {}).get(ach_id)
            cooldown_ms = (self._power_status.get("cooldowns") or {}).get(ach_id)
            use_label = "Use"
            if ach_id == "work_play":
                # Always allow toggling rainbow LEDs; no cooldown/active lockout
                use_label = "Use"
                can_use = True
            else:
                if active_ms and active_ms > 0:
                    use_label = "Active"
                    can_use = False
                elif cooldown_ms and cooldown_ms > 0:
                    use_label = "Cooling"
                    can_use = False

            item = self._create_inventory_item(
                grid,
                sprite_path=get_achievement_icon_path(ach_id),
                highlight=False,
            )

            def _ach_cb(evt, achievement=ach, _can_use=can_use, _use_label=use_label):
                desc = self._format_achievement_description(achievement)
                self._show_item_modal(
                    item_type=self.ITEM_TYPE_ACHIEVEMENT,
                    item_id=achievement.get("id"),
                    title=achievement.get("name", "Achievement"),
                    description=desc,
                    can_use=_can_use,
                    use_label=_use_label,
                )

            item.add_event_cb(_ach_cb, lv.EVENT.CLICKED, None)
            self.ach_buttons.append(item)

    def _create_inventory_item(self, parent, sprite_path=None, sprite_meta=None, highlight=False):
        """Create a clickable inventory item (icon only, no label)."""
        self.logger.debug(f"Pack item: sprite={sprite_path} meta={sprite_meta} highlight={highlight}")
        
        # Make entire button clickable - larger touch target
        item = lv.button(parent)
        item.set_size(56, 56)
        item.set_style_radius(6, 0)
        # Leather styling for items
        item.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_MEDIUM), 0)
        item.set_style_border_color(lv.color_hex(self.COLOR_LEATHER_DARK), 0)
        item.set_style_border_width(2, 0)
        item.set_style_pad_all(4, 0)
        if highlight:
            # Gold border and slightly lighter bg for active creature
            item.set_style_bg_color(lv.color_hex(0xA67C00), 0)  # Darker gold
            item.set_style_border_color(lv.color_hex(self.COLOR_LEATHER_HIGHLIGHT), 0)
            item.set_style_border_width(3, 0)

        # Icon container - NOT clickable (clicks pass through to button)
        if sprite_path is not None:
            icon = lv.obj(item)
            icon.set_size(44, 44)
            icon.align(lv.ALIGN.CENTER, 0, 0)
            icon.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_MEDIUM), 0)
            icon.set_style_border_width(0, 0)
            icon.set_style_radius(4, 0)
            # Make icon non-clickable so taps pass to parent button
            # Use multiple flags for robust click-through behavior
            icon.remove_flag(lv.obj.FLAG.CLICKABLE)
            icon.remove_flag(lv.obj.FLAG.SCROLLABLE)
            # EVENT_BUBBLE ensures any events bubble up to parent
            if hasattr(lv.obj.FLAG, "EVENT_BUBBLE"):
                icon.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            # GESTURE_BUBBLE for touch gestures
            if hasattr(lv.obj.FLAG, "GESTURE_BUBBLE"):
                icon.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            try:
                if hasattr(lv, "STYLE_OVERFLOW"):
                    icon.set_style_overflow(lv.STYLE_OVERFLOW.HIDDEN, 0)
            except Exception:
                pass

            img = self._set_icon_on_container(
                icon,
                sprite_path,
                sprite_meta=sprite_meta or {},
                target_size=44,
                cache_key=id(icon),
                img_store=self._icon_images,
                dsc_store=self._icon_img_dsc,
                data_store=self._icon_img_data,
                clip_overflow=True,
            )
            if img:
                # Make the image itself non-clickable with event bubbling
                img.remove_flag(lv.obj.FLAG.CLICKABLE)
                if hasattr(lv.obj.FLAG, "EVENT_BUBBLE"):
                    img.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
                if hasattr(lv.obj.FLAG, "GESTURE_BUBBLE"):
                    img.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)
            else:
                fallback = lv.label(icon)
                fallback.set_text("?")
                fallback.set_style_text_color(lv.color_hex(self.COLOR_TEXT_LIGHT), 0)
                fallback.align(lv.ALIGN.CENTER, 0, 0)
        else:
            # Placeholder for items without sprites (achievements, etc.)
            placeholder = lv.label(item)
            placeholder.set_text("?")
            placeholder.set_style_text_color(lv.color_hex(self.COLOR_TEXT_LIGHT), 0)
            placeholder.align(lv.ALIGN.CENTER, 0, 0)
            # Make placeholder non-clickable with event bubbling
            placeholder.remove_flag(lv.obj.FLAG.CLICKABLE)
            if hasattr(lv.obj.FLAG, "EVENT_BUBBLE"):
                placeholder.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
            if hasattr(lv.obj.FLAG, "GESTURE_BUBBLE"):
                placeholder.add_flag(lv.obj.FLAG.GESTURE_BUBBLE)

        return item

    def _show_item_modal(self, item_type, item_id, title, description, can_use=False, use_label=None):
        """Show info modal for an item with optional Use button."""
        if use_label is None:
            use_label = "Use"
        
        self._current_modal_item = {
            "type": item_type,
            "id": item_id,
            "title": title,
            "can_use": can_use,
        }
        
        overlay = self.ui_elements.get("modal")
        if not overlay:
            # Create modal overlay
            overlay = lv.obj(self.screen)
            overlay.set_size(lv.pct(100), lv.pct(100))
            overlay.set_style_bg_color(lv.color_hex(0x000000), 0)
            overlay.set_style_bg_opa(lv.OPA._60, 0)
            overlay.remove_flag(lv.obj.FLAG.SCROLLABLE)
            overlay.add_flag(lv.obj.FLAG.HIDDEN)
            self.ui_elements["modal"] = overlay

            # Modal box - leather themed
            box = lv.obj(overlay)
            box.set_size(280, 200)
            box.align(lv.ALIGN.CENTER, 0, 0)
            box.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_LIGHT), 0)
            box.set_style_border_color(lv.color_hex(self.COLOR_LEATHER_DARK), 0)
            box.set_style_border_width(3, 0)
            box.set_style_radius(8, 0)
            box.set_style_pad_all(10, 0)
            if hasattr(lv.obj, "set_flex_flow"):
                box.set_flex_flow(lv.FLEX_FLOW.COLUMN)
                box.set_style_pad_row(6, 0)
            box.remove_flag(lv.obj.FLAG.SCROLLABLE)
            self.ui_elements["modal_box"] = box

            # Header row with title and close X
            header = lv.obj(box)
            header.set_size(lv.pct(100), 28)
            if hasattr(lv.obj, "set_flex_flow"):
                header.set_flex_flow(lv.FLEX_FLOW.ROW)
                header.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
            header.set_style_bg_opa(lv.OPA.TRANSP, 0)
            header.set_style_border_width(0, 0)

            modal_title = lv.label(header)
            modal_title.set_style_text_color(lv.color_hex(self.COLOR_TEXT_DARK), 0)
            modal_title.set_width(lv.pct(80))
            modal_title.set_long_mode(lv.label.LONG.SCROLL if hasattr(lv.label, "LONG") else 0)
            self.ui_elements["modal_title"] = modal_title

            close_btn = self.create_button(header, "X", width=28, height=28)
            close_btn.set_style_radius(14, 0)
            close_btn.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_DARK), 0)
            close_btn.set_style_border_width(0, 0)
            close_btn.set_style_text_color(lv.color_hex(self.COLOR_TEXT_LIGHT), 0)
            close_btn.set_style_text_font(lv.font_montserrat_16, 0)
            close_btn.set_pos(20, -20)  # Nudge into top-right corner
            try:
                lbl = close_btn.get_child(0)
                if lbl:
                    lbl.set_style_text_font(lv.font_montserrat_16, 0)
            except Exception:
                pass
            close_btn.add_event_cb(self._close_modal, lv.EVENT.CLICKED, None)
            self.ui_elements["modal_close"] = close_btn

            # Action row (Use button)
            action_row = lv.obj(box)
            action_row.set_size(lv.pct(100), 34)
            if hasattr(lv.obj, "set_flex_flow"):
                action_row.set_flex_flow(lv.FLEX_FLOW.ROW)
                action_row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
            action_row.set_style_bg_opa(lv.OPA.TRANSP, 0)
            action_row.set_style_border_width(0, 0)

            # Use button (conditionally shown) - leather styled
            use_btn = self.create_button(action_row, "Use", width=80, height=28)
            use_btn.add_event_cb(self._on_use_pressed, lv.EVENT.CLICKED, None)
            use_btn.set_style_bg_color(lv.color_hex(self.COLOR_LEATHER_DARK), 0)
            use_btn.set_style_border_color(lv.color_hex(self.COLOR_TEXT_DARK), 0)
            use_btn.set_style_text_color(lv.color_hex(self.COLOR_TEXT_LIGHT), 0)
            self.ui_elements["modal_use_btn"] = use_btn

            # Description scroll area
            desc_container = lv.obj(box)
            desc_container.set_size(lv.pct(100), 120)
            desc_container.set_scroll_dir(lv.DIR.VER)
            desc_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)
            desc_container.set_style_bg_opa(lv.OPA.TRANSP, 0)
            desc_container.set_style_pad_all(0, 0)
            desc_container.set_style_border_width(0, 0)
            desc_container.set_style_pad_row(0, 0)
            desc_container.set_style_pad_column(0, 0)
            # keep scrollable so content can scroll

            body = lv.label(desc_container)
            body.set_width(lv.pct(100))
            if hasattr(lv.label, "LONG"):
                body.set_long_mode(lv.label.LONG.WRAP)
            body.set_style_text_color(lv.color_hex(self.COLOR_TEXT_DARK), 0)
            body.align(lv.ALIGN.TOP_LEFT, 0, 0)
            self.ui_elements["modal_body"] = body

        # Update modal content
        self.ui_elements["modal_title"].set_text(title)
        self.ui_elements["modal_body"].set_text(description)
        
        # Show/hide Use button based on item type and state
        use_btn = self.ui_elements.get("modal_use_btn")
        if use_btn:
            if can_use and use_label:
                # Update button label
                try:
                    btn_label = use_btn.get_child(0)
                    if btn_label:
                        btn_label.set_text(use_label)
                except Exception:
                    pass
                use_btn.remove_flag(lv.obj.FLAG.HIDDEN)
            else:
                use_btn.add_flag(lv.obj.FLAG.HIDDEN)

        overlay.remove_flag(lv.obj.FLAG.HIDDEN)

    def _close_modal(self, event=None):
        overlay = self.ui_elements.get("modal")
        if overlay:
            overlay.add_flag(lv.obj.FLAG.HIDDEN)
        self._current_modal_item = None

    def _on_use_pressed(self, event=None):
        """Handle Use button press based on current modal item type."""
        if not self._current_modal_item:
            return
        
        item_type = self._current_modal_item.get("type")
        item_id = self._current_modal_item.get("id")
        
        if item_type == self.ITEM_TYPE_CREATURE:
            # Switch to this creature
            self._on_character_selected(item_id)
            self._close_modal()
        elif item_type == self.ITEM_TYPE_SPECIAL_ITEM:
            # Future: Handle special items like care effects
            self._use_special_item(item_id)
            self._close_modal()
        elif item_type == self.ITEM_TYPE_ACHIEVEMENT:
            self._use_achievement(item_id)
            self._close_modal()
        
        # Refresh the list to update highlights
        self._refresh_lists()

    def _on_character_selected(self, char_id):
        """Switch active character."""
        # Free sprite memory aggressively before loading the new active creature tree.
        # This helps avoid fragmentation/pressure when switching from Pack -> Character.
        try:
            evict_sprite_cache(
                keep_paths=[],
                max_age_ms=0,
                min_free_percent=101,
                preserve_preloaded=True,
            )
        except Exception as e:
            self.logger.debug(f"Pre-switch sprite eviction failed: {e}")
        gc.collect()

        # Pass battle_manager so it gets notified of the switch
        result = set_active_character(prefs, char_id, battle_manager=self.battle_manager)
        if result.get('success'):
            self.logger.info(
                f"Switched character: {result.get('old_active')} -> {result.get('new_active')}, "
                f"battle_mgr_updated={result.get('battle_mgr_updated')}"
            )

    def _use_special_item(self, item_id):
        """
        Use a special item (future feature for items that act like care effects).
        
        Special items can provide buffs similar to care actions. Before showing
        the Use button, check if the effect is already active using get_care_state().
        """
        # Placeholder for future special item system
        # This would integrate with care effects or a separate item effect system
        self.logger.info(f"Special item used: {item_id}")
        # TODO: Implement special item application
        pass

    def _use_achievement(self, achievement_id):
        """Trigger achievement power activation."""
        try:
            result = self.achievements.use_power(achievement_id)
        except Exception as e:
            self.logger.warning(f"Use achievement failed: {e}")
            return
        msg = result.get("msg", "")
        if not result.get("ok"):
            self._show_item_modal(
                item_type=self.ITEM_TYPE_ACHIEVEMENT,
                item_id=achievement_id,
                title="Achievement",
                description=msg or "Unavailable",
                can_use=False,
            )
            return

        # Hardware side-effect for rainbow mode
        power = result.get("power") or {}
        if power.get("hardware_action") == "rgb_rainbow":
            try:
                if result.get("toggled_off"):
                    self.npc.stop_blink()
                else:
                    self.npc.start_rainbow()
            except Exception as e:
                self.logger.debug(f"RGB rainbow start failed: {e}")

    # --- text helpers ---
    def _format_achievement_description(self, achievement):
        """Return structured description text for achievement modal."""
        base = achievement.get("desc", "") or ""
        action = achievement.get("action")
        power = get_achievement_powers().get(achievement.get("id"))
        if not power or not action or action == "info":
            return base

        lines = []
        dur = power.get("duration_ms")
        cd = power.get("cooldown_ms")
        if power.get("xp_boost_pct"):
            lines.append(f"+{power['xp_boost_pct']}% XP")
        if power.get("atk_delta"):
            lines.append(f"+{power['atk_delta']} ATK")
        if power.get("def_delta"):
            lines.append(f"+{power['def_delta']} DEF")
        if power.get("evasion_delta"):
            lines.append(f"+{power['evasion_delta']} EVA (converted to speed)")
        if power.get("temperament_delta"):
            delta = power['temperament_delta']
            lines.append(f"{'+' if delta>0 else ''}{delta} Temperament")
        if power.get("hardware_action") == "rgb_rainbow":
            lines.append("Rainbow LEDs active")
        detail = []
        if lines:
            detail.append("Effect:")
            for ln in lines:
                detail.append(f" • {ln}")
        if dur:
            detail.append(f"Duration: {dur//60000} min")
        if cd:
            detail.append(f"Cooldown: {cd//60000} min")
        if power.get("temperament_gate") is not None:
            detail.append(f"Use only if temperament < {power['temperament_gate']}")
        return base + ("\n\n" + "\n".join(detail) if detail else "")

    def _is_special_item_effect_active(self, item_id):
        """
        Check if a special item's effect is currently active.
        
        Used to hide the Use button when the effect is already active,
        similar to how care actions work.
        """
        # Get current care state to check for active effects
        try:
            state = get_care_state(prefs) or {}
            # Check if this item's effect matches any active care effect
            # Future: This would check against a special item effect registry
            activity = state.get("activity") or {}
            food = state.get("food") or {}
            
            # If this item maps to a care effect ID, check if it's active
            if activity.get("id") == item_id or food.get("id") == item_id:
                return True
        except Exception as e:
            self.logger.warning(f"Failed to check effect state: {e}")
        
        return False
