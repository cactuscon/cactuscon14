"""Extras-style on-screen keyboard adapter."""

import lvgl as lv


class WifiKeyboard:
    """Keyboard overlay using Extras panel behavior with modal-safe shift."""

    def __init__(self, screen, viewport_root, shift_root, logger=None):
        self.screen = screen
        self._viewport = viewport_root
        self._shift_root = shift_root
        self._logger = logger

        self._keyboard = None
        self._keyboard_hidden = True
        self._kb_warned = set()
        self._shift = 0
        self._shift_root_y0 = 0
        self._min_shift = 0

        self._textarea = None
        self._footer = None
        self._on_ready = None
        self._on_cancel = None

        try:
            self._shift_root_y0 = self._shift_root.get_y()
        except Exception:
            self._shift_root_y0 = 0

    def set_handlers(self, on_ready=None, on_cancel=None):
        self._on_ready = on_ready
        self._on_cancel = on_cancel

    def get_keyboard(self):
        return self._keyboard

    def get_shift(self):
        return self._shift

    def set_shift_root(self, shift_root):
        if not shift_root:
            return
        self._shift_root = shift_root
        try:
            self._shift_root_y0 = self._shift_root.get_y()
        except Exception:
            self._shift_root_y0 = 0
        if self.is_visible():
            self._apply_shift()

    def show(self, textarea, footer=None, min_shift=0):
        self._textarea = textarea
        self._footer = footer
        self._min_shift = min_shift or 0
        self._ensure_keyboard()
        if not self._keyboard or not self._textarea or self.is_visible():
            return False
        self._position_keyboard()
        if not self._bind_textarea():
            return False
        if not self._obj_show(self._keyboard):
            return False
        if hasattr(self._keyboard, "set_cursor_manage"):
            self._keyboard.set_cursor_manage(True)
        if self._textarea and hasattr(self._textarea, "add_state") and hasattr(lv, "STATE"):
            if hasattr(lv.STATE, "FOCUSED"):
                self._textarea.add_state(lv.STATE.FOCUSED)
        if hasattr(self._keyboard, "move_foreground"):
            try:
                self._keyboard.move_foreground()
            except Exception as exc:
                self._warn_once("kb_foreground", "Keyboard foreground failed: {}".format(exc))
        self._apply_shift()
        return True

    def hide(self):
        if not self._keyboard or not self.is_visible():
            return False
        self._restore_shift()
        self._obj_hide(self._keyboard)
        if hasattr(self._keyboard, "set_textarea"):
            try:
                self._keyboard.set_textarea(None)
            except Exception:
                pass
        try:
            if self._textarea and hasattr(self._textarea, "clear_state") and hasattr(lv, "STATE"):
                if hasattr(lv.STATE, "FOCUSED"):
                    self._textarea.clear_state(lv.STATE.FOCUSED)
        except Exception:
            pass
        self._min_shift = 0
        return True

    def destroy(self):
        if not self._keyboard:
            return
        try:
            self._keyboard.delete()
        except Exception:
            pass
        self._keyboard = None
        self._keyboard_hidden = True

    def is_visible(self):
        if not self._keyboard:
            return False
        if hasattr(self._keyboard, "has_flag"):
            try:
                return not self._keyboard.has_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        return not self._keyboard_hidden

    def _ensure_keyboard(self):
        if self._keyboard:
            return
        kb_parent = self.screen
        if hasattr(lv, "layer_top"):
            try:
                kb_parent = lv.layer_top()
            except Exception:
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

    def _on_keyboard_ready(self, event):
        if self._on_ready:
            try:
                self._on_ready(event)
            except Exception:
                pass

    def _on_keyboard_cancel(self, event):
        if self._on_cancel:
            try:
                self._on_cancel(event)
            except Exception:
                pass

    def _position_keyboard(self):
        if not self._keyboard:
            return
        screen_w, screen_h = self._get_screen_size()
        if screen_w <= 0:
            screen_w = 240
        if screen_h <= 0:
            screen_h = 320
        kb_h = screen_h // 2
        min_h = 140
        max_h = int(screen_h * 0.6)
        if kb_h < min_h:
            kb_h = min_h
        if kb_h > max_h:
            kb_h = max_h
        self._keyboard.set_size(screen_w, kb_h)
        self._keyboard.align(lv.ALIGN.BOTTOM_MID, 0, 0)

    def _apply_shift(self):
        if not self._shift_root or not self._keyboard:
            return
        self._update_layout(self.screen)
        self._update_layout(self._shift_root)
        if self._textarea:
            self._update_layout(self._textarea)
        if self._footer:
            self._update_layout(self._footer)
        self._update_layout(self._keyboard)

        kb_coords = self._get_coords(self._keyboard)
        ta_coords = self._get_coords(self._textarea) if self._textarea else None
        footer_coords = self._get_coords(self._footer) if self._footer else None

        if not kb_coords:
            if self._min_shift:
                self._shift = self._min_shift
                self._shift_root.set_y(self._shift_root_y0 - self._shift)
            return

        bottom_to_keep = None
        if ta_coords:
            bottom_to_keep = ta_coords[3]
        if footer_coords:
            bottom_to_keep = max(bottom_to_keep or footer_coords[3], footer_coords[3])

        if bottom_to_keep is None:
            if self._min_shift:
                self._shift = self._min_shift
                self._shift_root.set_y(self._shift_root_y0 - self._shift)
            return

        margin = 6
        shift = bottom_to_keep - kb_coords[1] + margin
        if shift < 0:
            shift = 0
        if self._min_shift and shift < self._min_shift:
            shift = self._min_shift

        max_shift = self._max_allowed_shift()
        if max_shift is not None and shift > max_shift:
            shift = max_shift

        if shift > 0:
            self._shift = shift
            self._shift_root.set_y(self._shift_root_y0 - shift)
        else:
            self._shift = 0
            self._shift_root.set_y(self._shift_root_y0)

    def _restore_shift(self):
        if not self._shift_root:
            return
        if self._shift != 0:
            self._shift_root.set_y(self._shift_root_y0)
        self._shift = 0
        self._min_shift = 0

    def _max_allowed_shift(self):
        root_coords = self._get_coords(self._shift_root)
        viewport_coords = self._get_coords(self._viewport)
        if not root_coords or not viewport_coords:
            return None
        # Keep root bottom within viewport top.
        root_bottom = root_coords[3]
        viewport_top = viewport_coords[1]
        max_shift = root_bottom - viewport_top
        if max_shift < 0:
            max_shift = 0
        return max_shift

    def _bind_textarea(self):
        if not self._keyboard or not self._textarea:
            return False
        if not hasattr(self._keyboard, "set_textarea"):
            self._warn_once("kb_bind", "Keyboard missing set_textarea")
            return False
        try:
            self._keyboard.set_textarea(self._textarea)
        except Exception as exc:
            self._warn_once("kb_bind", "Keyboard bind failed: {}".format(exc))
            return False
        return True

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

    def _get_coords(self, obj):
        if not obj:
            return None
        try:
            coords = obj.get_coords()
            if hasattr(coords, "x1"):
                return (coords.x1, coords.y1, coords.x2, coords.y2)
        except Exception:
            return None
        return None

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

    def _warn_once(self, key, message):
        if key in self._kb_warned:
            return
        self._kb_warned.add(key)
        try:
            if self._logger:
                self._logger.warning(message)
            else:
                print(message)
        except Exception:
            print(message)
