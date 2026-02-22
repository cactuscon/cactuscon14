"""Handle edit panel - update player handle from Settings."""

import lvgl as lv

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.prefs import (
    prefs,
    HANDLE_KEY,
    LEGACY_HANDLE_KEY,
    HANDLE_PENDING_KEY,
    HANDLE_REG_ERROR_KEY,
)
from cactuscon import config
from cactuscon.handle_utils import HANDLE_MAX_LEN, normalize_handle, validate_handle
from cactiotpad.utils import default_device_id_generator


class HandleEditPanel(BasePanel):
    """Dedicated screen for editing the player handle."""

    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self._content_root = None
        self._content_root_y0 = 0
        self._kb_shift = 0
        self._handle_ta = None
        self._status_label = None
        self._keyboard = None
        self._keyboard_hidden = True
        self._kb_warned = set()
        self._original_handle = ""
        self._submit_btn = None
        self.api_client = None
        self.wifi = None

    def set_api_client(self, api_client):
        self.api_client = api_client

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
        self.ui_elements["content_root"] = self._content_root

        title = lv.label(self._content_root)
        title.set_text("Edit Handle")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 8)
        self.ui_elements["title"] = title

        screen_w, screen_h = self._get_screen_size()
        if screen_w and screen_w > 80:
            field_w = screen_w - 30
        else:
            field_w = lv.pct(90)

        self._handle_ta = lv.textarea(self._content_root)
        self._handle_ta.set_one_line(True)
        self._handle_ta.set_max_length(HANDLE_MAX_LEN)
        self._handle_ta.set_placeholder_text("yourhandle")
        self._handle_ta.set_width(field_w)
        self._handle_ta.set_height(36)
        self._handle_ta.align(lv.ALIGN.TOP_MID, 0, 50)
        self._handle_ta.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        self._handle_ta.set_style_border_color(lv.color_hex(0x00ff00), 0)
        self._handle_ta.set_style_border_width(1, 0)
        self._handle_ta.set_style_radius(4, 0)
        self._handle_ta.set_style_pad_left(8, 0)
        self._handle_ta.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        self._handle_ta.add_event_cb(self._on_textarea_clicked, lv.EVENT.CLICKED, None)
        self._handle_ta.add_event_cb(self._on_textarea_defocus, lv.EVENT.DEFOCUSED, None)
        self._handle_ta.add_event_cb(self._on_textarea_ready, lv.EVENT.READY, None)
        self._handle_ta.add_event_cb(self._on_textarea_cancel, lv.EVENT.CANCEL, None)
        self.ui_elements["handle_ta"] = self._handle_ta

        self._status_label = lv.label(self._content_root)
        self._status_label.set_text("")
        self._status_label.set_style_text_color(lv.color_hex(0x888888), 0)
        self._status_label.align(lv.ALIGN.TOP_MID, 0, 90)
        self.ui_elements["status"] = self._status_label

        btn_width = 90
        if screen_w and screen_w > 120:
            btn_width = max(70, min(120, (screen_w - 40) // 2))
        btn_height = 30
        btn_gap = 12
        btn_offset = (btn_width // 2) + (btn_gap // 2)
        btn_y = 120
        if screen_h and screen_h > 0:
            btn_y = min(btn_y, int(screen_h * 0.6))

        cancel_btn = self.create_button(
            self._content_root,
            "Cancel",
            callback=self._on_cancel_clicked,
            width=btn_width,
            height=btn_height,
        )
        cancel_btn.align(lv.ALIGN.TOP_MID, -btn_offset, btn_y)
        self.ui_elements["cancel_btn"] = cancel_btn

        submit_btn = self.create_button(
            self._content_root,
            "Submit",
            callback=self._on_submit_clicked,
            width=btn_width,
            height=btn_height,
        )
        submit_btn.align(lv.ALIGN.TOP_MID, btn_offset, btn_y)
        self.ui_elements["submit_btn"] = submit_btn
        self._submit_btn = submit_btn

        self._ensure_keyboard()

    def on_show(self):
        self.logger.info("Handle edit panel displayed")
        self._hide_keyboard()
        self._load_handle()
        self._set_status("")

    def on_hide(self):
        self._hide_keyboard()

    def on_cleanup(self):
        self._destroy_keyboard()

    def on_back_pressed(self, event=None):
        self._cancel_and_back()
        return True

    def _load_handle(self):
        handle = ""
        try:
            prefs.begin("cactuscon")
            handle = normalize_handle(
                prefs.get_string(HANDLE_KEY, prefs.get_string(LEGACY_HANDLE_KEY, ""))
            )
            prefs.end()
        except Exception:
            try:
                prefs.end()
            except Exception:
                pass
            handle = ""
        self._original_handle = handle or ""
        if self._handle_ta:
            try:
                self._handle_ta.set_text(self._original_handle)
            except Exception:
                pass

    def _get_handle_value(self):
        if not self._handle_ta:
            return ""
        try:
            text = self._handle_ta.get_text()
        except Exception:
            text = ""
        return normalize_handle(text)

    def _set_status(self, message, color=None):
        if not self._status_label:
            return
        self._status_label.set_text(message)
        if color is not None:
            self._status_label.set_style_text_color(color, 0)

    def _on_submit_clicked(self, event):
        self._save_handle()

    def _on_cancel_clicked(self, event):
        self._cancel_and_back()

    def _cancel_and_back(self):
        self._hide_keyboard()
        if self.game_ui:
            self.game_ui.show_panel("settings")

    def _save_handle(self):
        if not self._set_submit_enabled(False):
            return
        try:
            handle = self._get_handle_value()
            is_valid, normalized, error = validate_handle(handle)
            if not is_valid:
                self._set_status(error, lv.color_hex(0xFF6600))
                self._show_keyboard()
                return

            if normalized == (self._original_handle or ""):
                self._cancel_and_back()
                return

            # Handle changes must be accepted by API first, then persisted locally.
            if not self._push_handle_update(normalized):
                return

            try:
                prefs.begin("cactuscon", write=True, context="settings.save_handle")
                prefs.set_string(HANDLE_KEY, normalized)
                try:
                    prefs.set_string(LEGACY_HANDLE_KEY, normalized)
                except Exception:
                    pass
                prefs.end()
            except Exception as e:
                try:
                    prefs.end()
                except Exception:
                    pass
                self.logger.error(f"Failed to save handle: {e}")
                self._set_status("Save failed", lv.color_hex(0xFF0000))
                return

            self._apply_handle_runtime(normalized)
            self._cancel_and_back()
        finally:
            # If we navigated away, this is harmless; if we stayed due to error,
            # it guarantees the button is usable again.
            self._set_submit_enabled(True)

    def _set_submit_enabled(self, enabled):
        if not self._submit_btn:
            return True
        try:
            if enabled:
                self._submit_btn.remove_state(lv.STATE.DISABLED)
            else:
                if self._submit_btn.has_state(lv.STATE.DISABLED):
                    return False
                self._submit_btn.add_state(lv.STATE.DISABLED)
            return True
        except Exception:
            return True

    def _push_handle_update(self, handle):
        if not self.api_client:
            self._set_status("API unavailable", lv.color_hex(0xFF0000))
            return False
        api_timeout_s = self._api_timeout_s()

        wifi = self.wifi or (self.game_ui.wifi if self.game_ui else None)
        if not wifi:
            self._set_status("WiFi unavailable", lv.color_hex(0xFF0000))
            return False

        try:
            # For explicit API operations, keep auto-reconnect enabled.
            try:
                wifi.set_auto_reconnect(True)
            except Exception:
                pass

            if not wifi.is_connected():
                timeout_s = getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
                connected = wifi.ensure_connected(
                    timeout_s=timeout_s,
                    wait=True,
                    poll_interval_ms=100,
                    progress_callback=lambda: lv.task_handler(),
                    force=False,
                    enable_auto_reconnect=True,
                )
                if not connected:
                    self._set_status("WiFi offline", lv.color_hex(0xFF0000))
                    return False

            if not self.api_client.is_registered():
                self.show_spinner("Registering device...", pause_ms=60)
                self._set_status("Registering device...", lv.color_hex(0xFFFF00))
                try:
                    device_id = default_device_id_generator()
                except Exception as exc:
                    self.logger.warning(f"Handle update failed: device ID unavailable: {exc}")
                    self._set_status("Device ID unavailable", lv.color_hex(0xFF0000))
                    return False
                try:
                    self.api_client.register(
                        device_id=device_id,
                        handle=handle,
                        timeout=api_timeout_s,
                        max_retries=0,
                        retry=True,
                    )
                    self._clear_pending_registration()
                    return True
                except Exception as e:
                    self.logger.warning(f"Handle register API failed: {e}")
                    self._set_status("Registration failed", lv.color_hex(0xFF0000))
                    return False

            self.show_spinner("Updating handle...", pause_ms=60)
            self._set_status("Updating handle...", lv.color_hex(0xFFFF00))
            self.api_client.update_device(
                handle=handle,
                timeout=api_timeout_s,
                max_retries=0,
                retry=True,
            )
            return True
        except Exception as e:
            # Handle stale local auth/registration state:
            # update_device can fail as AuthenticationError(401 AUTH_FAILED) or
            # APIError(404 NOT_FOUND/NOT_REGISTERED) depending on backend/client path.
            status = getattr(e, "status_code", None)
            details = getattr(e, "details", None) or {}
            if status is None:
                status = details.get("status_code")
            code = (getattr(e, "error_code", "") or "").upper()
            if status in (401, 404) or code in (
                "AUTH_FAILED",
                "NOT_FOUND",
                "NOT_REGISTERED",
                "NO_DEVICE_ID",
            ):
                self.logger.info(
                    f"Handle update requires registration fallback (status={status}, code={code})"
                )
                if code == "AUTH_FAILED" or status == 401:
                    # Purge stale auth state before re-registering.
                    try:
                        self.api_client.auth.delete_api_key()
                    except Exception:
                        pass
                try:
                    self.show_spinner("Registering device...", pause_ms=60)
                    self._set_status("Registering device...", lv.color_hex(0xFFFF00))
                    device_id = default_device_id_generator()
                    self.api_client.register(
                        device_id=device_id,
                        handle=handle,
                        timeout=api_timeout_s,
                        max_retries=0,
                        retry=True,
                    )
                    self._clear_pending_registration()
                    return True
                except Exception as reg_e:
                    self.logger.warning(f"Handle register fallback failed: {reg_e}")
                    self._set_status("Registration failed", lv.color_hex(0xFF0000))
                    return False
            self.logger.warning(f"Handle update API failed: {e}")
            self._set_status("API update failed", lv.color_hex(0xFF0000))
            return False
        finally:
            self.hide_spinner()

    def _api_timeout_s(self):
        """Bound sync API time spent in UI callbacks to stay under watchdog budget."""
        timeout_s = int(getattr(config, "CACTIOT_TIMEOUT", 10) or 10)
        return max(2, min(timeout_s, 5))

    def _clear_pending_registration(self):
        try:
            prefs.begin("cactuscon", write=True, context="handle_edit.clear_pending")
            prefs.set_bool(HANDLE_PENDING_KEY, False)
            prefs.set_string(HANDLE_REG_ERROR_KEY, "")
            prefs.end()
        except Exception:
            try:
                prefs.end()
            except Exception:
                pass

    def _apply_handle_runtime(self, handle):
        if not handle:
            return
        if self.battle_manager and hasattr(self.battle_manager, "game_bt"):
            try:
                game_bt = self.battle_manager.game_bt
            except Exception:
                game_bt = None
            if game_bt:
                try:
                    game_bt.device_name = handle
                    if getattr(game_bt, "_is_advertising", False):
                        try:
                            game_bt.stop_advertising()
                            game_bt.start_advertising()
                        except Exception:
                            pass
                except Exception:
                    pass

    # --- Textarea events ---

    def _on_textarea_clicked(self, event):
        self._show_keyboard()

    def _on_textarea_defocus(self, event):
        if self._keyboard_is_visible():
            self._hide_keyboard()

    def _on_textarea_ready(self, event):
        self._save_handle()

    def _on_textarea_cancel(self, event):
        self._hide_keyboard()

    def _on_keyboard_ready(self, event):
        self._save_handle()

    def _on_keyboard_cancel(self, event):
        self._hide_keyboard()

    # --- Keyboard management (patterned after registration.py) ---

    def _show_keyboard(self):
        self._ensure_keyboard()
        if not self._keyboard or not self._handle_ta or self._keyboard_is_visible():
            return
        self._position_keyboard()
        if not self._bind_keyboard_textarea():
            return
        if not self._obj_show(self._keyboard):
            return
        if hasattr(self._keyboard, "set_cursor_manage"):
            self._keyboard.set_cursor_manage(True)
        if self._handle_ta and hasattr(self._handle_ta, "add_state") and hasattr(lv, "STATE"):
            if hasattr(lv.STATE, "FOCUSED"):
                self._handle_ta.add_state(lv.STATE.FOCUSED)
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
            if self._handle_ta and hasattr(self._handle_ta, "clear_state") and hasattr(lv, "STATE"):
                if hasattr(lv.STATE, "FOCUSED"):
                    self._handle_ta.clear_state(lv.STATE.FOCUSED)
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
        # Keep keyboard parented to this screen during preload; avoids flashing
        # on lv.layer_top() when panels are preloaded at boot.
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
        self.ui_elements["keyboard"] = self._keyboard

    def _position_keyboard(self):
        if not self._keyboard:
            return
        screen_w, screen_h = self._get_screen_size()
        if screen_w <= 0 or screen_h <= 0:
            return
        kb_h = screen_h // 2
        if kb_h > 140:
            kb_h = 140
        self._keyboard.set_size(screen_w, kb_h)
        self._keyboard.align(lv.ALIGN.BOTTOM_MID, 0, 0)

    def _apply_keyboard_shift(self):
        if not self._content_root or not self._handle_ta or not self._keyboard:
            return
        self._update_layout(self.screen)
        self._update_layout(self._content_root)
        self._update_layout(self._handle_ta)
        self._update_layout(self._keyboard)

        _, screen_h = self._get_screen_size()
        kb_y = self._get_abs_y(self._keyboard)
        kb_h = self._keyboard.get_height()
        if kb_h <= 0:
            kb_h = max(1, screen_h // 2)
        if kb_y <= 0 and screen_h > 0:
            kb_y = screen_h - kb_h

        ta_y = self._get_abs_y(self._handle_ta)
        ta_h = self._handle_ta.get_height()
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
            elif hasattr(obj, "clear_flag"):
                obj.clear_flag(lv.obj.FLAG.HIDDEN)
            else:
                return False
        except Exception as exc:
            self._warn_once("kb_show", "Show failed: {}".format(exc))
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
            else:
                return False
        except Exception as exc:
            self._warn_once("kb_hide", "Hide failed: {}".format(exc))
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
        if not self._keyboard or not self._handle_ta:
            return False
        if not hasattr(self._keyboard, "set_textarea"):
            self._warn_once("kb_bind", "Keyboard missing set_textarea")
            return False
        try:
            self._keyboard.set_textarea(self._handle_ta)
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
            pass
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
            self.logger.warning(message)
        except Exception:
            print(message)
