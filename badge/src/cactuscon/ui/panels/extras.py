"""Extras panel - bonus features and unlock codes."""

import gc
import lvgl as lv

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.utils import mem_info
from cactuscon import unlocks


def _add_back_button(panel, handler):
    btn_back = lv.button(panel.screen)
    btn_back.set_size(60, 30)
    btn_back.align(lv.ALIGN.TOP_RIGHT, -10, 8)
    btn_back.add_event_cb(handler, lv.EVENT.CLICKED, None)
    btn_back.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
    btn_back.set_style_border_color(lv.color_hex(0x00ff00), 0)
    btn_back.set_style_border_width(1, 0)

    label = lv.label(btn_back)
    label.set_text("Back")
    label.set_style_text_color(lv.color_hex(0x00ff00), 0)
    label.center()

    panel.ui_elements['btn_back'] = btn_back
    return btn_back


class ExtrasPanel(BasePanel):
    """Extras screen with unlock code entry."""

    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self._content_root = None
        self._content_root_y0 = 0
        self._kb_shift = 0
        self._code_ta = None
        self._status_label = None
        self._status_timer = None
        self._keyboard = None
        self._keyboard_hidden = True
        self._kb_warned = set()

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        self._content_root = lv.obj(self.screen)
        self._content_root.set_size(lv.pct(100), lv.pct(100))
        self._content_root.set_pos(0, 0)
        self._content_root.remove_flag(lv.obj.FLAG.SCROLLABLE)
        try:
            if hasattr(lv, "OPA") and hasattr(lv.OPA, "TRANSP"):
                self._content_root.set_style_bg_opa(lv.OPA.TRANSP, 0)
            else:
                self._content_root.set_style_bg_opa(0, 0)
        except Exception:
            pass
        self._content_root.set_style_border_width(0, 0)
        self._content_root_y0 = 0
        self._kb_shift = 0
        self.ui_elements['content_root'] = self._content_root

        title = lv.label(self.screen)
        title.set_text("Extras")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        info = lv.label(self._content_root)
        info.set_text("Complete challenges for unlock codes!")
        info.set_style_text_color(lv.color_hex(0x888888), 0)
        info.align(lv.ALIGN.TOP_LEFT, 15, 40)
        self.ui_elements['info'] = info

        section = lv.label(self._content_root)
        section.set_text("Unlock code")
        section.set_style_text_color(lv.color_hex(0x00ff00), 0)
        section.align(lv.ALIGN.TOP_LEFT, 15, 70)
        self.ui_elements['unlock_section'] = section

        enter_label = lv.label(self._content_root)
        enter_label.set_text("Enter code")
        enter_label.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        enter_label.align(lv.ALIGN.TOP_LEFT, 15, 95)
        self.ui_elements['enter_label'] = enter_label

        self._code_ta = lv.textarea(self._content_root)
        self._code_ta.set_size(210, 30)
        self._code_ta.align(lv.ALIGN.TOP_MID, 0, 112)
        self._code_ta.set_one_line(True)
        self._code_ta.set_max_length(32)
        self._code_ta.set_placeholder_text("Enter code...")
        self._code_ta.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        self._code_ta.set_style_border_color(lv.color_hex(0x00ff00), 0)
        self._code_ta.set_style_border_width(1, 0)
        self._code_ta.set_style_radius(4, 0)
        self._code_ta.set_style_pad_left(8, 0)
        self._code_ta.add_event_cb(self._on_textarea_clicked, lv.EVENT.CLICKED, None)
        self._code_ta.add_event_cb(self._on_textarea_defocus, lv.EVENT.DEFOCUSED, None)
        self._code_ta.add_event_cb(self._on_textarea_ready, lv.EVENT.READY, None)
        self._code_ta.add_event_cb(self._on_textarea_cancel, lv.EVENT.CANCEL, None)
        self.ui_elements['code_ta'] = self._code_ta

        submit_btn = self.create_button(
            self._content_root,
            "Submit",
            width=120,
            height=30,
            callback=self._on_submit_clicked,
        )
        submit_btn.align(lv.ALIGN.TOP_MID, 0, 150)
        self.ui_elements['submit_btn'] = submit_btn

        self._status_label = lv.label(self._content_root)
        self._status_label.set_text("")
        self._status_label.set_style_text_color(lv.color_hex(0x888888), 0)
        self._status_label.align(lv.ALIGN.TOP_MID, 0, 185)
        self.ui_elements['status'] = self._status_label

        self._ensure_keyboard()

    def on_show(self):
        gc.collect()
        mem_info("[MEM] extras entry")
        if self._status_label:
            self._status_label.set_text("")
        self._hide_keyboard()
        mem_info("[MEM] extras after UI build")

    def on_hide(self):
        self._hide_keyboard()
        self._stop_status_timer()

    def on_cleanup(self):
        self._destroy_keyboard()
        self._stop_status_timer()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('main_menu')
            return True
        return False

    def _on_textarea_defocus(self, event):
        if self._keyboard_is_visible():
            self._hide_keyboard()

    def _on_textarea_ready(self, event):
        self._hide_keyboard()

    def _on_textarea_cancel(self, event):
        self._hide_keyboard()

    def _on_textarea_clicked(self, event):
        self._show_keyboard()

    def _on_keyboard_ready(self, event):
        self._submit_code()
        self._hide_keyboard()

    def _on_keyboard_cancel(self, event):
        self._hide_keyboard()

    def _on_submit_clicked(self, event):
        self._submit_code()

    def _show_keyboard(self):
        self._ensure_keyboard()
        if not self._keyboard or not self._code_ta or self._keyboard_is_visible():
            return
        self._position_keyboard()
        if not self._bind_keyboard_textarea():
            return
        if not self._obj_show(self._keyboard):
            return
        if hasattr(self._keyboard, "set_cursor_manage"):
            self._keyboard.set_cursor_manage(True)
        if self._code_ta and hasattr(self._code_ta, "add_state") and hasattr(lv, "STATE"):
            if hasattr(lv.STATE, "FOCUSED"):
                self._code_ta.add_state(lv.STATE.FOCUSED)
        if hasattr(self._keyboard, "move_foreground"):
            try:
                self._keyboard.move_foreground()
            except Exception as exc:
                self._warn_once("kb_foreground", "Keyboard foreground failed: {}".format(exc))
        self._apply_keyboard_shift()

    def _hide_keyboard(self):
        if not self._keyboard or not self._keyboard_is_visible():
            return
        self._restore_keyboard_shift()
        self._obj_hide(self._keyboard)
        if hasattr(self._keyboard, "set_textarea"):
            self._keyboard.set_textarea(None)
        try:
            if self._code_ta and hasattr(self._code_ta, "clear_state") and hasattr(lv, "STATE"):
                if hasattr(lv.STATE, "FOCUSED"):
                    self._code_ta.clear_state(lv.STATE.FOCUSED)
        except Exception:
            pass

    def _destroy_keyboard(self):
        if not self._keyboard:
            return
        try:
            self._keyboard.delete()
        except Exception:
            pass
        self._keyboard = None
        self._keyboard_hidden = True

    def _ensure_keyboard(self):
        if self._keyboard:
            return
        # Keep keyboard on this panel's screen during preload to avoid flash.
        kb_parent = self.screen
        try:
            self._keyboard = lv.keyboard(kb_parent)
        except Exception as exc:
            self._warn_once("kb_create", "Keyboard create failed: {}".format(exc))
            self._keyboard = None
            return
        self._position_keyboard()
        if hasattr(self._keyboard, "set_mode") and hasattr(lv, "KEYBOARD_MODE"):
            if hasattr(lv.KEYBOARD_MODE, "TEXT"):
                self._keyboard.set_mode(lv.KEYBOARD_MODE.TEXT)
        self._keyboard.add_event_cb(self._on_keyboard_ready, lv.EVENT.READY, None)
        self._keyboard.add_event_cb(self._on_keyboard_cancel, lv.EVENT.CANCEL, None)
        self._obj_hide(self._keyboard)
        self.ui_elements['keyboard'] = self._keyboard

    def _apply_keyboard_shift(self):
        if not self._content_root or not self._code_ta or not self._keyboard:
            return
        self._update_layout(self.screen)
        self._update_layout(self._content_root)
        self._update_layout(self._code_ta)
        self._update_layout(self._keyboard)

        _, screen_h = self._get_screen_size()
        kb_y = self._get_abs_y(self._keyboard)
        kb_h = self._keyboard.get_height()
        if kb_h <= 0:
            kb_h = max(1, screen_h // 2)
        if kb_y <= 0 and screen_h > 0:
            kb_y = screen_h - kb_h

        ta_y = self._get_abs_y(self._code_ta)
        ta_h = self._code_ta.get_height()
        ta_bottom = ta_y + ta_h

        margin = 6
        overlap = ta_bottom - (kb_y - margin)
        shift = overlap if overlap > 0 else 0

        if shift > 0:
            self._kb_shift = shift
            self._content_root.set_y(self._content_root_y0 - shift)
        else:
            self._kb_shift = 0
            self._content_root.set_y(self._content_root_y0)

    def _restore_keyboard_shift(self):
        if not self._content_root:
            return
        if self._kb_shift != 0:
            self._content_root.set_y(self._content_root_y0)
        self._kb_shift = 0

    def _obj_show(self, obj):
        if not obj:
            return False
        try:
            if hasattr(obj, "remove_flag"):
                obj.remove_flag(lv.obj.FLAG.HIDDEN)
            elif hasattr(obj, "set_flag"):
                obj.set_flag(lv.obj.FLAG.HIDDEN, False)
            elif hasattr(obj, "clear_flag"):
                obj.clear_flag(lv.obj.FLAG.HIDDEN)
            else:
                self._warn_once("kb_show", "Keyboard show unsupported")
                return False
        except Exception as exc:
            self._warn_once("kb_show", "Keyboard show failed: {}".format(exc))
            return False
        if obj == self._keyboard:
            self._keyboard_hidden = False
        return True

    def _obj_hide(self, obj):
        if not obj:
            return False
        try:
            if hasattr(obj, "add_flag"):
                obj.add_flag(lv.obj.FLAG.HIDDEN)
            elif hasattr(obj, "set_flag"):
                obj.set_flag(lv.obj.FLAG.HIDDEN, True)
            else:
                self._warn_once("kb_hide", "Keyboard hide unsupported")
                return False
        except Exception as exc:
            self._warn_once("kb_hide", "Keyboard hide failed: {}".format(exc))
            return False
        if obj == self._keyboard:
            self._keyboard_hidden = True
        return True

    def _keyboard_is_visible(self):
        if not self._keyboard:
            return False
        if hasattr(self._keyboard, "has_flag"):
            try:
                return not self._keyboard.has_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        return not self._keyboard_hidden

    def _bind_keyboard_textarea(self):
        if not self._keyboard or not self._code_ta:
            return False
        if not hasattr(self._keyboard, "set_textarea"):
            self._warn_once("kb_bind", "Keyboard missing set_textarea")
            return False
        try:
            self._keyboard.set_textarea(self._code_ta)
        except Exception as exc:
            self._warn_once("kb_bind", "Keyboard bind failed: {}".format(exc))
            return False
        return True

    def _update_layout(self, obj):
        if not obj:
            return
        try:
            obj.update_layout()
        except Exception:
            try:
                if hasattr(lv, "obj_update_layout"):
                    lv.obj_update_layout(obj)
            except Exception:
                pass

    def _get_abs_y(self, obj):
        if not obj:
            return 0
        try:
            coords = obj.get_coords()
            if hasattr(coords, "y1"):
                return coords.y1
        except Exception:
            pass
        y = 0
        current = obj
        while current is not None:
            try:
                y += current.get_y()
            except Exception:
                pass
            try:
                current = current.get_parent()
            except Exception:
                break
        return y

    def _get_screen_size(self):
        width = 0
        height = 0
        try:
            width = self.screen.get_width()
            height = self.screen.get_height()
        except Exception:
            width = 0
            height = 0
        if (width <= 0 or height <= 0) and hasattr(lv, "display_get_default"):
            try:
                disp = lv.display_get_default()
                width = disp.get_hor_res()
                height = disp.get_ver_res()
            except Exception:
                pass
        return width, height

    def _position_keyboard(self):
        if not self._keyboard:
            return
        screen_w, screen_h = self._get_screen_size()
        if screen_w <= 0:
            screen_w = 240
        if screen_h <= 0:
            screen_h = 320
        kb_h = screen_h // 2
        if kb_h > 140:
            kb_h = 140
        self._keyboard.set_size(screen_w, kb_h)
        self._keyboard.align(lv.ALIGN.BOTTOM_MID, 0, 0)

    def _warn_once(self, key, message):
        if key in self._kb_warned:
            return
        self._kb_warned.add(key)
        try:
            self.logger.warning(message)
        except Exception:
            print(message)

    def _set_status(self, text, ok=None):
        if not self._status_label:
            return
        self._status_label.set_text(text or "")
        if ok is None:
            color = lv.color_hex(0x888888)
        elif ok:
            color = lv.color_hex(0x00ff00)
        else:
            color = lv.color_hex(0xFF6600)
        self._status_label.set_style_text_color(color, 0)
        self._update_status_timer(text)

    def _update_status_timer(self, text):
        prefix = "Too many attempts. Wait "
        if text and text.startswith(prefix):
            self._start_status_timer()
        else:
            self._stop_status_timer()

    def _start_status_timer(self):
        if self._status_timer:
            return
        self._status_timer = lv.timer_create(self._refresh_status, 1000, None)
        self._refresh_status(self._status_timer)

    def _stop_status_timer(self):
        if self._status_timer:
            try:
                self._status_timer.delete()
            except Exception:
                pass
            self._status_timer = None

    def _refresh_status(self, timer=None):
        if not self._status_label:
            self._stop_status_timer()
            return
        remaining = unlocks.get_lockout_remaining_seconds()
        if remaining > 0:
            self._status_label.set_text(f"Too many attempts. Wait {remaining}s.")
        else:
            self._status_label.set_text("")
            self._stop_status_timer()

    def _submit_code(self):
        if not self._code_ta:
            return
        try:
            code = self._code_ta.get_text()
        except Exception:
            code = ""
        ok, message = unlocks.try_redeem(
            code,
            context={
                "panel": "extras",
                "game_ui": self.game_ui,
                "battle_manager": self.battle_manager,
            },
        )
        self._set_status(message, ok=ok)
        if ok:
            try:
                self._code_ta.set_text("")
            except Exception:
                pass
