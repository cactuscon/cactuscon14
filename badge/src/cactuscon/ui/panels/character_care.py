"""Care panel - manage care effects and temperament."""

import lvgl as lv
import time

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.game.engine.characters import (
    get_care_catalog,
    get_care_state,
    set_care_effect,
)
from cactuscon.prefs import prefs

TEMPERAMENT_VAL_TO_STATE = {
    0: "Calm",
    1: "Content",
    2: "Alert",
    3: "Agitated",
    4: "Anxious",
    5: "Frustrated",
    6: "Upset",
    7: "Angry",
    8: "Furious",
    9: "Wrathful",
    10: "Raging",
}


class CharacterCarePanel(BasePanel):
    """Standalone care panel for activity/food effects."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._busy = False
        self._last_action_ms = 0
        self._last_error_msg = None
        self._last_error_ts = 0

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        header = lv.label(self.screen)
        header.set_text("Care")
        header.set_style_text_color(lv.color_hex(0x00FF00), 0)
        header.align(lv.ALIGN.TOP_LEFT, 10, 8)
        self.ui_elements["header"] = header

        back_btn = self.create_button(self.screen, "Back", width=60, height=26)
        back_btn.align(lv.ALIGN.TOP_RIGHT, -10, 6)
        back_btn.add_event_cb(self.on_back_pressed, lv.EVENT.CLICKED, None)
        self.ui_elements["back_btn"] = back_btn

        status_btn = lv.button(self.screen)
        status_btn.set_pos(10, 36)
        status_btn.set_size(200, 16)
        status_btn.set_style_bg_opa(0, 0)
        status_btn.set_style_border_width(0, 0)
        status_btn.set_style_pad_all(0, 0)
        status_btn.remove_flag(lv.obj.FLAG.SCROLLABLE)
        status_btn.add_event_cb(self._on_temperament_info, lv.EVENT.CLICKED, None)
        self.ui_elements["status_btn"] = status_btn

        status = lv.label(status_btn)
        status.set_style_text_color(lv.color_hex(0xAAAAAA), 0)
        status.set_text("Choose an effect")
        status.align(lv.ALIGN.LEFT_MID, 0, 0)
        self.ui_elements["status"] = status

        hint = lv.label(self.screen)
        hint.set_pos(10, 56)
        hint.set_style_text_color(lv.color_hex(0x777777), 0)
        hint.set_text("Effects last for a bit; one per category.")
        self.ui_elements["hint"] = hint

        catalog = get_care_catalog() or {}
        self.ui_elements["care_buttons"] = {}
        y = 78
        for category in ("activity", "food"):
            title = lv.label(self.screen)
            title.set_pos(10, y)
            title.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
            title.set_text("Activity" if category == "activity" else "Food")

            row = lv.obj(self.screen)
            row.set_size(300, 58)
            row.set_pos(10, y + 18)
            row.set_flex_flow(lv.FLEX_FLOW.ROW)
            row.set_flex_align(
                lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
            )
            row.set_style_pad_column(8, 0)
            row.set_style_pad_left(2, 0)
            row.set_style_pad_right(2, 0)
            row.remove_flag(lv.obj.FLAG.SCROLLABLE)

            btns = []
            for effect in catalog.get(category, []):
                btn = lv.button(row)
                btn_width = 140
                btn_height = 48
                btn.set_size(btn_width, btn_height)
                btn.set_style_radius(4, 0)
                btn.set_style_bg_color(lv.color_hex(0x222222), 0)
                btn.set_style_border_color(lv.color_hex(0x444444), 0)
                btn.set_style_border_width(1, 0)
                lbl = lv.label(btn)
                lbl.set_text(effect.get("name", ""))
                lbl.set_style_text_color(lv.color_hex(0x00FF00), 0)
                lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
                lbl.set_width(btn_width)
                lbl.align(lv.ALIGN.TOP_MID, 0, 4)

                sub = lv.label(btn)
                sub.set_text(self._format_effect_summary(effect))
                sub.set_style_text_font(lv.font_montserrat_12, 0)
                sub.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
                sub.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
                sub.center()
                sub.set_width(btn_width)
                sub.align(lv.ALIGN.TOP_MID, 0, 22)

                def _cb(evt, cat=category, eff_id=effect.get("id")):
                    self._on_effect_clicked(cat, eff_id)

                btn.add_event_cb(_cb, lv.EVENT.CLICKED, None)
                btns.append((btn, effect))
            self.ui_elements["care_buttons"][category] = btns
            y += 76

        self._refresh_state()

    def on_show(self):
        super().on_show()
        self._refresh_state()

    # --- helpers ---

    def _refresh_state(self):
        try:
            state = get_care_state(prefs) or {}
        except Exception as e:
            self.logger.warning(f"Care state load failed: {e}")
            state = {}
        try:
            catalog = get_care_catalog() or {}
        except Exception as e:
            self.logger.warning(f"Care catalog load failed: {e}")
            catalog = {}

        activity = state.get("activity") or {}
        food = state.get("food") or {}
        activity_id = activity.get("id")
        food_id = food.get("id")
        temp = state.get("temperament", 0)
        activity_cooldown = state.get("activity_cooldown", 0)
        food_cooldown = state.get("food_cooldown", 0)

        activity_locked = bool(activity_id) or activity_cooldown > 0
        food_locked = bool(food_id) or food_cooldown > 0

        status = self.ui_elements.get("status")
        hint = self.ui_elements.get("hint")
        active_activity = (
            self._effect_name("activity", activity_id, catalog) if activity_id else None
        )
        active_food = self._effect_name("food", food_id, catalog) if food_id else None
        temp_name = TEMPERAMENT_VAL_TO_STATE.get(temp, str(temp))
        temp_color = 0x00FF00 if temp <= 5 else 0xFFFF00 if temp <= 8 else 0xFF4444
        if status:
            parts = []
            # if activity_id or food_id:
            #     parts.append(f"Active: {self._effect_name('activity', activity_id, catalog)}")
            # if food_id:
            #     parts.append(f"Food: {self._effect_name('food', food_id, catalog)}")
            parts.append(f"Temperament: {temp_name}")
            status.set_style_text_color(lv.color_hex(temp_color), 0)
            status.set_text(" | ".join(parts) if parts else "Choose an effect")
        if hint:
            msgs = []
            if activity_id or food_id:
                msgs.append("Active effects: ")
            if activity_id:
                msgs.append(self._effect_name("activity", activity_id, catalog))
            if food_id:
                msgs.append(self._effect_name("food", food_id, catalog))
            if activity_cooldown and not activity_id:
                msgs.append("Activity cooling down")
            if food_cooldown and not food_id:
                msgs.append("Food cooling down")
            hint.set_text(
                str(msgs[0] + ", ".join([m for m in msgs[1:] if m]))
                if msgs
                else "Effects last for a bit; one per category."
            )

        for category, buttons in self.ui_elements.get("care_buttons", {}).items():
            active_id = activity_id if category == "activity" else food_id
            locked = activity_locked if category == "activity" else food_locked
            for btn, effect in buttons:
                if effect.get("id") == active_id:
                    btn.set_style_bg_color(lv.color_hex(0x1F4A1F), 0)
                else:
                    btn.set_style_bg_color(lv.color_hex(0x222222), 0)
                try:
                    if locked:
                        btn.add_flag(lv.obj.FLAG.DISABLED)
                    else:
                        btn.remove_flag(lv.obj.FLAG.DISABLED)
                except Exception:
                    pass

    def _on_temperament_info(self, evt):
        self._show_info_modal(
            "Temperament",
            "Higher temperament makes your creature less obedient.\n"
            "Care effects can raise or lower it.\n"
            "It does not affect stats, and lowers over time.",
        )

    def _show_info_modal(self, title_text, body_text):
        overlay = self.ui_elements.get("info_modal")
        if not overlay:
            overlay = lv.obj(self.screen)
            overlay.set_size(lv.pct(100), lv.pct(100))
            overlay.set_style_bg_color(lv.color_hex(0x000000), 0)
            overlay.set_style_bg_opa(lv.OPA._60, 0)
            overlay.remove_flag(lv.obj.FLAG.SCROLLABLE)
            overlay.add_flag(lv.obj.FLAG.HIDDEN)
            self.ui_elements["info_modal"] = overlay

            box = lv.obj(overlay)
            box.set_size(240, 140)
            box.align(lv.ALIGN.CENTER, 0, 0)
            box.set_style_bg_color(lv.color_hex(0x1A1A1A), 0)
            box.set_style_border_color(lv.color_hex(0x00FF00), 0)
            box.set_style_border_width(1, 0)
            box.set_style_radius(6, 0)
            box.set_style_pad_all(8, 0)
            box.remove_flag(lv.obj.FLAG.SCROLLABLE)
            self.ui_elements["info_modal_box"] = box

            title = lv.label(box)
            title.set_style_text_color(lv.color_hex(0x00FF00), 0)
            title.align(lv.ALIGN.TOP_LEFT, 0, 0)
            self.ui_elements["info_modal_title"] = title

            body = lv.label(box)
            body.set_width(220)
            if hasattr(lv.label, "LONG"):
                body.set_long_mode(lv.label.LONG.WRAP)
            body.align(lv.ALIGN.TOP_LEFT, 0, 18)
            body.set_style_text_color(lv.color_hex(0xDDDDDD), 0)
            self.ui_elements["info_modal_body"] = body

            close = self.create_button(box, "Close", width=70, height=24)
            close.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
            close.add_event_cb(self._close_info_modal, lv.EVENT.CLICKED, None)
            self.ui_elements["info_modal_close"] = close

        self.ui_elements["info_modal_title"].set_text(title_text)
        self.ui_elements["info_modal_body"].set_text(body_text)
        overlay.remove_flag(lv.obj.FLAG.HIDDEN)

    def _close_info_modal(self, evt):
        overlay = self.ui_elements.get("info_modal")
        if overlay:
            overlay.add_flag(lv.obj.FLAG.HIDDEN)

    def _effect_name(self, category, effect_id, catalog):
        for eff in catalog.get(category, []):
            if eff.get("id") == effect_id:
                return eff.get("name", effect_id)
        return effect_id

    def _effect_desc(self, category, effect_id, catalog):
        for eff in catalog.get(category, []):
            if eff.get("id") == effect_id:
                return eff.get("desc", "")
        return ""

    def _format_effect_summary(self, effect):
        """Build a short summary like [+XP, -Temp] from effect metadata."""
        parts = []
        xp = effect.get("xp_boost_pct", 0)
        if xp:
            parts.append(f"+{xp}% XP")

        atk = effect.get("atk_delta", 0)
        if atk:
            parts.append(f"{'+' if atk>0 else ''}{atk} Atk")

        defense = effect.get("def_delta", 0)
        if defense:
            parts.append(f"{'+' if defense>0 else ''}{defense} Def")

        temp_delta = effect.get("temperament_delta", 0)
        if temp_delta:
            parts.append(f"{'+' if temp_delta>0 else ''}{temp_delta} Temp")

        if not parts:
            desc = effect.get("desc", "")
            if desc:
                parts.append(desc.split(";")[0][:18])
        return ", ".join(parts) or ""

    # --- events ---

    def _show_error_throttled(self, msg, min_interval_ms=1000):
        """Prevent spamming the same error repeatedly within a short window."""
        try:
            now = time.ticks_ms()
            if (
                msg == self._last_error_msg
                and self._last_error_ts
                and time.ticks_diff(now, self._last_error_ts) < min_interval_ms
            ):
                return
            self._last_error_msg = msg
            self._last_error_ts = now
        except Exception:
            pass
        self.show_error(msg)

    def _on_effect_clicked(self, category, effect_id):
        # Simple debounce to avoid repeated trigger from stale touch
        try:
            now_ms = time.ticks_ms()
            if (
                self._last_action_ms
                and time.ticks_diff(now_ms, self._last_action_ms) < 800
            ):
                return
            self._last_action_ms = now_ms
        except Exception:
            pass

        if self._busy:
            return
        self._busy = True
        state = get_care_state(prefs) or {}
        current = state.get(category) or {}
        cooldown_key = (
            "activity_cooldown" if category == "activity" else "food_cooldown"
        )
        cooldown_until = state.get(cooldown_key, 0)

        if current:
            self._show_error_throttled("Effect already active")
            self._busy = False
            return
        if cooldown_until:
            self._show_error_throttled("Cooling down, please wait")
            self._busy = False
            return
        try:
            set_care_effect(prefs, category, effect_id)
        finally:
            self._busy = False
        self._refresh_state()
