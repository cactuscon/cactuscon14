"""Registration panel - Player handle entry and device registration."""

import lvgl as lv
import gc
import ubinascii
import uhashlib
import urandom
import ujson

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.prefs import prefs, HANDLE_KEY, LEGACY_HANDLE_KEY, HANDLE_PENDING_KEY, HANDLE_REG_ERROR_KEY
from cactuscon.handle_utils import HANDLE_MAX_LEN, normalize_handle, validate_handle
from cactuscon import config
from cactiotpad.exceptions import NetworkError, APIError


class RegistrationPanel(BasePanel):
    """
    Registration screen - captures player handle for device registration.
    
    Uses embedded LVGL keyboard (like extras.py) for reliable text entry.
    """
    
    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self.api_client = None
        self._handle_value = ""
        self._handle_ta = None  # Textarea instead of button
        self._status_label = None
        self._register_btn = None
        self._skip_btn = None
        self._registering = False
        self._pending_character_redirect = False
        self._error_modal = None
        self._error_modal_msg = None
        self._error_modal_close = None
        self._device_info_label = None
        
        # Keyboard state (embedded like extras.py)
        self._keyboard = None
        self._keyboard_hidden = True
        self._kb_warned = set()
        self._content_root = None
        self._content_root_y0 = 0
        self._kb_shift = 0
        
        self.mac_str = None
        self._refresh_mac()

    def _generate_anon_handle(self):
        """Generate anonymized handle: Anon<hash8>."""
        if not self.mac_str:
            raise RuntimeError("Cannot generate anonymous handle: no MAC address available")
        rnd8 = urandom.getrandbits(32) % 100000000
        seed = "{}:{:08d}".format(self.mac_str, rnd8)
        digest = uhashlib.sha256(seed.encode()).digest()
        h8 = ubinascii.hexlify(digest)[:8].decode()
        return "Anon" + h8
    
    def set_api_client(self, api_client):
        """Set the API client for registration."""
        self.api_client = api_client
    
    def create_ui(self):
        """Create registration panel UI with embedded keyboard."""
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Content root for keyboard shift (like extras.py)
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
        
        # === TITLE ===
        title = lv.label(self._content_root)
        title.set_text("Device Registration")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 15)
        self.ui_elements['title'] = title
        
        # === INSTRUCTIONS ===
        instructions = lv.label(self._content_root)
        instructions.set_text("Enter your player handle\nto register this badge.")
        instructions.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        instructions.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        instructions.align(lv.ALIGN.TOP_MID, 0, 50)
        self.ui_elements['instructions'] = instructions
        
        # === HANDLE INPUT (textarea with click handler) ===
        self._handle_ta = lv.textarea(self._content_root)
        self._handle_ta.set_size(280, 40)
        self._handle_ta.align(lv.ALIGN.TOP_MID, 0, 100)
        self._handle_ta.set_one_line(True)
        self._handle_ta.set_max_length(HANDLE_MAX_LEN)
        self._handle_ta.set_placeholder_text("yourhandle")
        self._handle_ta.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        self._handle_ta.set_style_border_color(lv.color_hex(0x00ff00), 0)
        self._handle_ta.set_style_border_width(1, 0)
        self._handle_ta.set_style_radius(4, 0)
        self._handle_ta.set_style_pad_left(10, 0)
        self._handle_ta.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        
        # Event handlers for textarea
        self._handle_ta.add_event_cb(self._on_textarea_clicked, lv.EVENT.CLICKED, None)
        self._handle_ta.add_event_cb(self._on_textarea_defocus, lv.EVENT.DEFOCUSED, None)
        self._handle_ta.add_event_cb(self._on_textarea_ready, lv.EVENT.READY, None)
        self._handle_ta.add_event_cb(self._on_textarea_cancel, lv.EVENT.CANCEL, None)
        
        self.ui_elements['handle_ta'] = self._handle_ta
        
        # === STATUS MESSAGE ===
        self._status_label = lv.label(self._content_root)
        self._status_label.set_text("")
        self._status_label.set_style_text_color(lv.color_hex(0x888888), 0)
        self._status_label.align(lv.ALIGN.TOP_MID, 0, 150)
        self.ui_elements['status'] = self._status_label
        
        # === REGISTER BUTTON ===
        self._register_btn = lv.button(self._content_root)
        self._register_btn.set_size(200, 45)
        self._register_btn.align(lv.ALIGN.BOTTOM_MID, 0, -30)
        self._register_btn.add_event_cb(self._on_register_clicked, lv.EVENT.CLICKED, None)
        
        self._register_btn.set_style_bg_color(lv.color_hex(0x006600), 0)
        self._register_btn.set_style_bg_color(lv.color_hex(0x008800), lv.STATE.PRESSED)
        self._register_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        self._register_btn.set_style_border_width(2, 0)
        self._register_btn.set_style_radius(8, 0)
        
        btn_label = lv.label(self._register_btn)
        btn_label.set_text("Register")
        btn_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        btn_label.center()
        
        self.ui_elements['register_btn'] = self._register_btn

        # === SKIP BUTTON ===
        self._skip_btn = lv.button(self._content_root)
        self._skip_btn.set_size(35, 35)
        self._skip_btn.align(lv.ALIGN.TOP_RIGHT, -10, 10)
        self._skip_btn.add_event_cb(self._on_skip_clicked, lv.EVENT.CLICKED, None)

        self._skip_btn.set_style_bg_color(lv.color_hex(0x333333), 0)
        self._skip_btn.set_style_bg_color(lv.color_hex(0x555555), lv.STATE.PRESSED)
        self._skip_btn.set_style_border_color(lv.color_hex(0x888888), 0)
        self._skip_btn.set_style_border_width(1, 0)
        self._skip_btn.set_style_radius(6, 0)

        skip_label = lv.label(self._skip_btn)
        skip_label.set_text("X")
        skip_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        skip_label.center()

        self.ui_elements['skip_btn'] = self._skip_btn
        
        # === DEVICE INFO ===
        device_info = lv.label(self._content_root)
        if self.mac_str:
            device_info.set_text(f"Device: {self.mac_str}")
        else:
            device_info.set_text("Device: Unknown")
        device_info.set_style_text_color(lv.color_hex(0x444444), 0)
        device_info.align(lv.ALIGN.BOTTOM_MID, 0, -5)
        self.ui_elements['device_info'] = device_info
        self._device_info_label = device_info

        # === ERROR MODAL ===
        self._create_error_modal()
        
    # --- Textarea event handlers ---
    
    def _on_textarea_clicked(self, event):
        """Show keyboard when textarea is clicked."""
        self._show_keyboard()

    def _on_textarea_defocus(self, event):
        """Hide keyboard when textarea loses focus."""
        if self._keyboard_is_visible():
            self._hide_keyboard()

    def _on_textarea_ready(self, event):
        """Handle enter key in textarea."""
        self._hide_keyboard()

    def _on_textarea_cancel(self, event):
        """Handle cancel/escape in textarea."""
        self._hide_keyboard()

    def _on_keyboard_ready(self, event):
        """Keyboard READY event (enter pressed)."""
        self._hide_keyboard()

    def _on_keyboard_cancel(self, event):
        """Keyboard CANCEL event."""
        self._hide_keyboard()

    # --- Keyboard management (copied from extras.py) ---

    def _show_keyboard(self):
        """Show keyboard and bind to textarea."""
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
            except Exception:
                pass
        self._apply_keyboard_shift()

    def _hide_keyboard(self):
        """Hide keyboard and unbind textarea."""
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
        """Clean up keyboard."""
        if not self._keyboard:
            return
        try:
            self._keyboard.delete()
        except Exception:
            pass
        self._keyboard = None
        self._keyboard_hidden = True

    def _ensure_keyboard(self):
        """Create keyboard if not exists."""
        if self._keyboard:
            return
        # Use panel screen as parent during preload to avoid flash on layer_top().
        # The keyboard is moved to the foreground when shown.
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

    def _position_keyboard(self):
        """Position keyboard at bottom of screen."""
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

    def _apply_keyboard_shift(self):
        """Shift content up so textarea stays visible above keyboard."""
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
        """Restore content position after keyboard hidden."""
        if not self._content_root:
            return
        if self._kb_shift != 0:
            self._content_root.set_y(self._content_root_y0)
        self._kb_shift = 0

    def _obj_show(self, obj):
        """Show LVGL object."""
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
        """Hide LVGL object."""
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
        """Check if keyboard is visible."""
        if not self._keyboard:
            return False
        if hasattr(self._keyboard, "has_flag"):
            try:
                return not self._keyboard.has_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        return not self._keyboard_hidden

    def _bind_keyboard_textarea(self):
        """Bind keyboard to handle textarea."""
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
        """Force layout update on object."""
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
        """Get absolute Y position of object."""
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
        """Get screen dimensions."""
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
        """Log warning only once per key."""
        if key in self._kb_warned:
            return
        self._kb_warned.add(key)
        try:
            self.logger.warning(message)
        except Exception:
            print(message)

    # --- Registration logic ---

    def _get_handle_value(self):
        """Get current handle from textarea."""
        if self._handle_ta:
            text = self._handle_ta.get_text()
            return text.strip() if text else ""
        return ""

    def _on_skip_clicked(self, event):
        """Skip registration with anonymized handle."""
        if self._registering:
            return
        self._hide_keyboard()

        try:
            anon_handle = self._generate_anon_handle()
        except Exception as e:
            self.logger.error(f"Failed to generate anonymous handle: {e}")
            self._set_status("Cannot skip: device ID unavailable", lv.color_hex(0xFF0000))
            return
        
        self.logger.info(f"Registration skipped; using anonymized handle: {anon_handle}")
        self._clear_registration_error()
        if not self._save_local_handle(anon_handle, pending=False):
            self._show_error_modal("Failed to save handle locally. Please try again.")
            return

        if self.game_ui:
            self.game_ui.show_panel('character')
    
    def _on_register_clicked(self, event):
        """Handle register button click."""
        if self._registering:
            return
        self._hide_keyboard()
        
        handle = normalize_handle(self._get_handle_value())

        is_valid, normalized, error = validate_handle(handle)
        if not is_valid:
            self._show_error_modal(error)
            return

        self._registering = True
        self._set_status("Registering...", lv.color_hex(0xFFFF00))
        self._register_btn.add_state(lv.STATE.DISABLED)
        
        self._do_registration(normalized)
    
    def _do_registration(self, handle):
        """Perform the actual registration."""
        if not self.mac_str:
            self.logger.error("Cannot register: no device ID (MAC address unavailable)")
            self._on_registration_failed("Device ID unavailable")
            return

        if not self.api_client:
            self.logger.warning("API client not available; saving handle locally")
            self._on_registration_deferred(handle, None)
            return

        # Ensure WiFi is online before attempting registration. When panels are
        # preloaded, the WiFi loop may still be reconnecting in the background,
        # which previously resulted in an immediate failure that looked like
        # “not on WiFi”.
        wifi = getattr(self.game_ui, "wifi", None)
        if wifi and not wifi.is_connected():
            timeout_s = getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
            self.logger.info("WiFi disconnected; reconnecting before registration")
            # Keep LVGL responsive while waiting for network handshake completion.
            connected = wifi.ensure_connected(
                timeout_s=timeout_s,
                wait=True,
                poll_interval_ms=100,
                progress_callback=lambda: lv.task_handler(),
                force=False,
                enable_auto_reconnect=True,
            )

            if not connected:
                self.logger.warning("Registration deferred: WiFi still offline after reconnect attempt")
                self._on_registration_deferred(handle, NetworkError("WiFi offline"))
                return

        try:
            self.logger.info(f"Registering with handle: {handle}")
            success = self.api_client.register(
                self.mac_str,
                handle,
                None,
                timeout=self._api_timeout_s(),
                max_retries=0,
                retry=True,
            )

            if success:
                self._on_registration_success(handle)
            else:
                self._on_registration_failed("Registration failed")

        except Exception as e:
            if self._should_defer_registration(e):
                self._on_registration_deferred(handle, e)
            else:
                self.logger.error(f"Registration error: {e}")
                self._on_registration_failed(e)

    def _api_timeout_s(self):
        """Bound sync API time spent in UI callbacks to stay under watchdog budget."""
        timeout_s = int(getattr(config, "CACTIOT_TIMEOUT", 10) or 10)
        return max(2, min(timeout_s, 5))
    
    def _on_registration_success(self, handle):
        """Handle successful registration."""
        self.logger.info(f"Registration successful: {handle}")
        self._clear_registration_error()
        self._set_status("Registration complete!", lv.color_hex(0x00FF00))

        if not self._save_local_handle(handle, pending=False):
            self._save_registration_error("Failed to save handle locally")
            self._show_error_modal("Registration succeeded, but saving your handle failed.\nPlease try again.")
            self._registering = False
            self._register_btn.remove_state(lv.STATE.DISABLED)
            return

        self._registering = False
        
        if self.game_ui:
            self.game_ui.show_panel('character')
    
    def _on_registration_failed(self, error):
        """Handle failed registration."""
        msg = "Registration failed"
        try:
            detail = self._extract_api_detail(error)
            if isinstance(error, APIError) and getattr(error, "status_code", None) == 409:
                msg = "Handle already in use. Choose another."
            elif detail:
                msg = detail
            else:
                msg = str(error)
            if len(msg) > 80:
                msg = msg[:80]
        except Exception:
            pass

        self.logger.error(f"Registration failed: {error}")
        self._save_registration_error(msg)
        self._show_error_modal(f"Registration failed:\n{msg}")
        self._registering = False
        self._register_btn.remove_state(lv.STATE.DISABLED)

    def _on_registration_deferred(self, handle, error):
        """Handle offline registration."""
        if error:
            self.logger.warning(f"Registration deferred due to network/server error: {error}")
        else:
            self.logger.warning("Registration deferred (API unavailable)")

        if not self._save_local_handle(handle, pending=True):
            self._save_registration_error("Failed to save handle locally")
            self._show_error_modal("Failed to save handle locally.\nPlease try again.")
            self._registering = False
            self._register_btn.remove_state(lv.STATE.DISABLED)
            return

        self._set_status("Saved locally. Will sync when online.", lv.color_hex(0xFFFF00))

        self._registering = False
        self._register_btn.remove_state(lv.STATE.DISABLED)

        if self.game_ui:
            self.game_ui.show_panel('character')

    def _should_defer_registration(self, error):
        """Return True if registration should be deferred."""
        if isinstance(error, NetworkError):
            return True
        if isinstance(error, APIError) and getattr(error, "status_code", 0) >= 500:
            return True
        return False

    def _save_local_handle(self, handle, pending=False):
        """Persist handle locally."""
        try:
            prefs.begin("cactuscon", write=True, context="registration.save_handle")
            prefs.set_string(HANDLE_KEY, handle)
            try:
                prefs.set_string(LEGACY_HANDLE_KEY, handle)
            except Exception:
                pass
            prefs.set_bool(HANDLE_PENDING_KEY, bool(pending))
            prefs.end()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save handle: {e}")
            try:
                prefs.end()
            except Exception:
                pass
            return False
    
    def _extract_api_detail(self, error):
        if not isinstance(error, APIError):
            return None
        body = getattr(error, "response_body", None)
        if not body:
            return None
        try:
            parsed = ujson.loads(body)
            detail = parsed.get("detail")
            if detail:
                return str(detail)
        except Exception:
            pass
        return str(body)

    def _clear_registration_error(self):
        try:
            prefs.begin("cactuscon", write=True, context="registration.clear_error")
            prefs.set_string(HANDLE_REG_ERROR_KEY, "")
            prefs.end()
        except Exception:
            try:
                prefs.end()
            except Exception:
                pass

    def _save_registration_error(self, message):
        try:
            prefs.begin("cactuscon", write=True, context="registration.save_error")
            prefs.set_string(HANDLE_REG_ERROR_KEY, message or "")
            prefs.end()
        except Exception:
            try:
                prefs.end()
            except Exception:
                pass

    def _set_status(self, message, color):
        """Set status message."""
        if self._status_label:
            self._status_label.set_text(message)
            self._status_label.set_style_text_color(color, 0)

    def _create_error_modal(self):
        modal = lv.obj(self.screen)
        modal.set_size(lv.pct(100), lv.pct(100))
        modal.set_style_bg_color(lv.color_hex(0x000000), 0)
        try:
            modal.set_style_bg_opa(lv.OPA.COVER, 0)
        except Exception:
            modal.set_style_bg_opa(255, 0)
        modal.remove_flag(lv.obj.FLAG.SCROLLABLE)

        card = lv.obj(modal)
        card.set_size(260, 160)
        card.align(lv.ALIGN.CENTER, 0, 0)
        card.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        card.set_style_border_color(lv.color_hex(0xFF3333), 0)
        card.set_style_border_width(2, 0)
        card.set_style_radius(8, 0)
        card.set_style_pad_all(10, 0)

        title = lv.label(card)
        title.set_text("Registration Error")
        title.set_style_text_color(lv.color_hex(0xFF6666), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 0)

        msg = lv.label(card)
        msg.set_text("")
        msg.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        if hasattr(msg, "set_long_mode") and hasattr(lv, "LABEL_LONG"):
            msg.set_long_mode(lv.LABEL_LONG.WRAP)
        msg.set_width(240)
        msg.align(lv.ALIGN.TOP_MID, 0, 28)
        self._error_modal_msg = msg

        close_btn = lv.button(card)
        close_btn.set_size(90, 32)
        close_btn.align(lv.ALIGN.BOTTOM_MID, 0, 0)
        close_btn.set_style_bg_color(lv.color_hex(0x333333), 0)
        close_btn.set_style_border_color(lv.color_hex(0x888888), 0)
        close_btn.set_style_border_width(1, 0)
        close_btn.add_event_cb(self._on_error_modal_close, lv.EVENT.CLICKED, None)
        close_label = lv.label(close_btn)
        close_label.set_text("OK")
        close_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        close_label.center()
        self._error_modal_close = close_btn

        modal.add_flag(lv.obj.FLAG.HIDDEN)
        self._error_modal = modal

    def _show_error_modal(self, message):
        if self._error_modal_msg:
            self._error_modal_msg.set_text(message or "Unknown error")
        self._hide_keyboard()
        if self._error_modal:
            self._error_modal.remove_flag(lv.obj.FLAG.HIDDEN)
            try:
                self._error_modal.move_foreground()
            except Exception:
                pass

    def _hide_error_modal(self):
        if self._error_modal:
            self._error_modal.add_flag(lv.obj.FLAG.HIDDEN)

    def _on_error_modal_close(self, event):
        self._hide_error_modal()
    
    def on_show(self):
        """Called when panel is displayed."""
        self.logger.info("Registration panel displayed")
        self._registering = False
        self._pending_character_redirect = False
        self._hide_keyboard()
        self._refresh_mac()
        if self.wifi:
            try:
                self.wifi.set_auto_reconnect(True)
            except Exception:
                pass
        self._prime_wifi_connection()

        try:
            handle = normalize_handle(
                prefs.get_string(HANDLE_KEY, prefs.get_string(LEGACY_HANDLE_KEY, ""))
            )
            if handle and self._handle_ta:
                self._handle_ta.set_text(handle)
        except Exception:
            pass

        try:
            pending_error = prefs.get_string(HANDLE_REG_ERROR_KEY, "")
            if pending_error:
                self._show_error_modal(pending_error[:120])
                self._clear_registration_error()
            else:
                self._set_status("", lv.color_hex(0x888888))
        except Exception:
            pass

        if self.api_client and self.api_client.is_registered():
            self.logger.info("Already registered, navigating to home")
            self._pending_character_redirect = True

    def update(self):
        # Avoid re-entrant show_panel() calls during on_show(), which can leave
        # transition spinners stuck if a panel redirects while still loading.
        if self._pending_character_redirect and self.game_ui:
            self._pending_character_redirect = False
            self.game_ui.show_panel('character')

    def _prime_wifi_connection(self):
        """
        Start WiFi reconnect as soon as registration panel opens so submit path
        is less likely to block on network bring-up.
        """
        wifi = getattr(self, "wifi", None) or getattr(self.game_ui, "wifi", None)
        if not wifi:
            return
        try:
            if not wifi.is_connected():
                timeout_s = getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
                wifi.ensure_connected(
                    timeout_s=timeout_s,
                    wait=False,
                    force=False,
                    enable_auto_reconnect=True,
                )
        except Exception as e:
            self.logger.debug(f"Registration WiFi prime failed: {e}")

    def _refresh_mac(self):
        if self.mac_str:
            return
        wifi = getattr(self, "wifi", None) or getattr(self.game_ui, "wifi", None)
        if not wifi:
            return
        try:
            mac = wifi.get_mac_string(uppercase=True)
        except Exception:
            mac = None
        if mac:
            self.mac_str = mac
            if self._device_info_label:
                self._device_info_label.set_text(f"Device: {self.mac_str}")
    
    def on_hide(self):
        """Called when panel is hidden."""
        self.logger.debug("Registration panel hidden")
        self._hide_keyboard()

    def on_cleanup(self):
        """Clean up resources."""
        self._destroy_keyboard()
    
    def on_back_pressed(self):
        """Block back navigation during registration."""
        self.logger.debug("Back pressed on registration (blocked)")
        self._set_status("Registration required", lv.color_hex(0xFF6600))
        return True
