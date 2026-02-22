"""WiFi Connect flow panel (list + password)."""

import gc
import time
import lvgl as lv

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.utils import mem_info
from cactuscon.ui.wifi_flow.wifi_views import build_list_view, build_password_view, build_status_overlay, PAGE_SIZE
from cactuscon.ui.wifi_flow.wifi_keyboard import WifiKeyboard
from cactuscon.ui.wifi_flow import wifi_debug


class WifiConnectFlowPanel(BasePanel):
    """Two-step WiFi connect flow (SSID list -> password)."""

    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self._wifi_mgr = None

        self._content_root = None
        self._keyboard = None

        self._view_root = None
        self._list_view = None
        self._password_view = None
        self._active_view = None

        self._networks = []
        self._page_index = 0
        self._selected_ssid = None
        self._row_index_by_obj = {}

        self._status_overlay = None
        self._status_spinner = None
        self._status_label = None
        self._status_ssid_label = None
        self._connect_timer = None
        self._overlay_timer = None
        self._scan_timer = None
        self._connect_started_ms = None
        self._connect_timeout_ms = None
        self._scanning = False
        self._connecting = False
        self._scan_seq = 0
        self._scan_nav_counter = 0
        self._nav_counter = 0
        self._remember_choice = False
        self._remember_ssid = None
        self._remember_password = None
        self._connect_attempt_ssid = None
        self._connect_attempt_password = None
        self._last_connect_success = False
        self._last_connect_ssid = None
        self._overlay_nav_to_settings = False
        self._saved_auto_reconnect = None

    def _now_ms(self):
        if hasattr(time, "ticks_ms"):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _elapsed_ms(self, start_ms):
        if start_ms is None:
            return 0
        if hasattr(time, "ticks_diff"):
            return time.ticks_diff(self._now_ms(), start_ms)
        return self._now_ms() - start_ms

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
        self.ui_elements["content_root"] = self._content_root

        self._keyboard = WifiKeyboard(self.screen, self.screen, self._content_root, self.logger)
        self._keyboard.set_handlers(self._on_keyboard_ready, self._on_keyboard_cancel)

        overlay = build_status_overlay(self._content_root)
        self._status_overlay = overlay["overlay"]
        self._status_spinner = overlay["spinner"]
        self._status_label = overlay.get("label_primary") or overlay.get("label")
        self._status_ssid_label = overlay.get("label_secondary")

        self._show_list_view()

    def on_show(self):
        gc.collect()
        mem_info("[MEM] wifi flow entry")
        self._ensure_wifi_manager()
        self._pause_background_reconnect()
        if self._active_view != "list":
            self._show_list_view()
        self._begin_scan(reset_page=True, delay_ms=30)
        self._hide_keyboard()
        self._hide_status_overlay()
        self._snapshot("on_show")
        mem_info("[MEM] wifi flow ready")

    def on_hide(self):
        self._hide_keyboard()
        self._stop_connect_timer()
        self._hide_status_overlay()
        self._stop_scan_timer()
        self._scanning = False
        self._resume_background_reconnect()

    def on_cleanup(self):
        self._hide_keyboard()
        self._stop_connect_timer()
        self._stop_scan_timer()
        self._resume_background_reconnect()
        if self._keyboard:
            self._keyboard.destroy()
        self._keyboard = None

    def _ensure_wifi_manager(self):
        if self._wifi_mgr:
            return self._wifi_mgr
        if self.game_ui and hasattr(self.game_ui, "wifi") and self.game_ui.wifi:
            self._wifi_mgr = self.game_ui.wifi
            return self._wifi_mgr
        self.logger.debug("WiFi manager not available from GameUI")
        return None

    def _show_list_view(self):
        self._destroy_view()
        self._list_view = build_list_view(self._content_root, self.create_button)
        self._view_root = self._list_view["root"]
        self._active_view = "list"
        if self._keyboard:
            self._keyboard.set_shift_root(self._view_root)
        self._row_index_by_obj = {}
        for idx, row in enumerate(self._list_view["rows"]):
            row_btn = row["btn"]
            row_btn.add_event_cb(self._on_row_clicked, lv.EVENT.CLICKED, None)
            self._row_index_by_obj[row_btn] = idx
        self._list_view["btn_back"].add_event_cb(self._on_back_from_list, lv.EVENT.CLICKED, None)
        self._list_view["btn_reconnect"].add_event_cb(self._on_reconnect_clicked, lv.EVENT.CLICKED, None)
        self._list_view["btn_refresh"].add_event_cb(self._on_refresh_clicked, lv.EVENT.CLICKED, None)
        self._list_view["btn_prev"].add_event_cb(self._on_prev_clicked, lv.EVENT.CLICKED, None)
        self._list_view["btn_next"].add_event_cb(self._on_next_clicked, lv.EVENT.CLICKED, None)

    def _show_password_view(self, ssid):
        self._destroy_view()
        self._selected_ssid = ssid
        self._password_view = build_password_view(self._content_root, self.create_button)
        self._view_root = self._password_view["root"]
        self._active_view = "password"
        if self._keyboard:
            self._keyboard.set_shift_root(self._view_root)

        label = self._password_view.get("ssid_label")
        if label:
            label.set_text("Network: {}".format(ssid or "---"))

        self._password_view["btn_back"].add_event_cb(self._on_back_from_password, lv.EVENT.CLICKED, None)
        self._password_view["btn_connect"].add_event_cb(self._on_connect_clicked, lv.EVENT.CLICKED, None)

        ta = self._password_view.get("password_ta")
        if ta:
            ta.add_event_cb(self._on_password_clicked, lv.EVENT.CLICKED, None)
            ta.add_event_cb(self._on_password_defocus, lv.EVENT.DEFOCUSED, None)
            ta.add_event_cb(self._on_password_ready, lv.EVENT.READY, None)
            ta.add_event_cb(self._on_password_cancel, lv.EVENT.CANCEL, None)

    def _destroy_view(self):
        if self._view_root:
            try:
                self._view_root.delete()
            except Exception:
                pass
        self._view_root = None
        self._active_view = None
        self._row_index_by_obj = {}
        self._list_view = None
        self._password_view = None

    def _refresh_scan(self, reset_page=False):
        wifi = self._ensure_wifi_manager()
        if not wifi:
            results = []
        else:
            if hasattr(wifi, "scan_networks"):
                results = wifi.scan_networks()
            else:
                results = wifi.refresh_scan()
        if results is None:
            results = []
        if (not results) and wifi and hasattr(wifi, "get_last_error") and wifi.get_last_error():
            self.logger.warning("[WIFI-FLOW] scan empty: {}".format(wifi.get_last_error()))
        self._apply_scan_results(results, reset_page=reset_page, seq=self._scan_seq)

    def _pause_background_reconnect(self):
        wifi = self._ensure_wifi_manager()
        if not wifi:
            return
        if self._saved_auto_reconnect is None:
            try:
                if hasattr(wifi, "pause_background_reconnect"):
                    self._saved_auto_reconnect = bool(
                        wifi.pause_background_reconnect(
                            reason="wifi flow scan", force_radio=True
                        )
                    )
                    return
            except Exception:
                self._saved_auto_reconnect = None
        try:
            if hasattr(wifi, "get_auto_reconnect"):
                self._saved_auto_reconnect = bool(wifi.get_auto_reconnect())
            if hasattr(wifi, "set_auto_reconnect"):
                wifi.set_auto_reconnect(False)
            if hasattr(wifi, "cancel_connect"):
                wifi.cancel_connect("wifi flow scan", force_radio=True)
        except Exception:
            pass

    def _resume_background_reconnect(self):
        wifi = self._ensure_wifi_manager()
        if not wifi:
            self._saved_auto_reconnect = None
            return
        if self._saved_auto_reconnect is None:
            return
        try:
            if hasattr(wifi, "resume_background_reconnect"):
                wifi.resume_background_reconnect(
                    self._saved_auto_reconnect, reconnect_if_needed=False
                )
            elif hasattr(wifi, "set_auto_reconnect"):
                wifi.set_auto_reconnect(self._saved_auto_reconnect)
        except Exception:
            pass
        self._saved_auto_reconnect = None

    def _update_list_page(self):
        if not self._list_view:
            return
        total = len(self._networks)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._page_index >= total_pages:
            self._page_index = total_pages - 1
        if self._page_index < 0:
            self._page_index = 0

        page_label = self._list_view.get("page_label")
        if page_label:
            page_label.set_text("Page {}/{}".format(self._page_index + 1, total_pages))

        start = self._page_index * PAGE_SIZE
        for idx, row in enumerate(self._list_view["rows"]):
            entry_idx = start + idx
            row_btn = row["btn"]
            if entry_idx < total:
                entry = self._networks[entry_idx]
                ssid = entry.get("ssid", "---")
                rssi = entry.get("rssi")
                row["ssid"].set_text(ssid)
                if rssi is None or rssi <= -999:
                    row["rssi"].set_text("")
                else:
                    row["rssi"].set_text("{} dBm".format(rssi))
                row["active"] = True
                row["entry_idx"] = entry_idx
                self._set_row_state(row_btn, True)
            else:
                if total == 0 and idx == 0:
                    row["ssid"].set_text("No networks")
                else:
                    row["ssid"].set_text("")
                row["rssi"].set_text("")
                row["active"] = False
                row["entry_idx"] = None
                self._set_row_state(row_btn, False)

        # Prev/Next are logic-gated; no DISABLED state used.

    def _set_row_state(self, row_btn, active):
        if not row_btn:
            return
        try:
            if active:
                row_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
                row_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
            else:
                row_btn.set_style_bg_color(lv.color_hex(0x101010), 0)
                row_btn.set_style_border_color(lv.color_hex(0x333333), 0)
        except Exception:
            pass

    def _get_row_index(self, event):
        target = None
        try:
            if hasattr(event, "get_target_obj"):
                target = event.get_target_obj()
        except Exception:
            pass
        if target is None:
            try:
                if hasattr(event, "get_target"):
                    target = event.get_target()
            except Exception:
                pass
        return self._row_index_by_obj.get(target)

    def _on_row_clicked(self, event):
        if self._scanning:
            return
        idx = self._get_row_index(event)
        if idx is None:
            return
        row = self._list_view["rows"][idx]
        if not row.get("active"):
            return
        entry_idx = row.get("entry_idx")
        if entry_idx is None or entry_idx < 0 or entry_idx >= len(self._networks):
            return
        ssid = self._networks[entry_idx].get("ssid")
        if not ssid:
            return
        self._show_password_view(ssid)
        self._snapshot("to_password")

    def _on_back_from_list(self, event):
        if self.game_ui:
            self.game_ui.show_panel("settings")

    def _on_back_from_password(self, event):
        if self._connecting:
            self._debug_blocked("back")
            return
        self._hide_keyboard()
        self._stop_connect_timer()
        self._hide_status_overlay()
        self._show_list_view()
        self._update_list_page()
        self._snapshot("back_to_list")

    def _on_refresh_clicked(self, event):
        self._begin_scan(reset_page=True, delay_ms=30)
        self._snapshot("refresh")

    def _on_reconnect_clicked(self, event=None):
        if self._connecting:
            self._debug_blocked("reconnect")
            return
        self._hide_keyboard()
        wifi = self._ensure_wifi_manager()
        saved_ssid, saved_password = (None, None)
        if wifi:
            try:
                saved_ssid, saved_password = wifi.load_saved_credentials()
            except Exception:
                saved_ssid, saved_password = (None, None)
        if not saved_ssid:
            try:
                if wifi and wifi.is_connected():
                    ssid = wifi.get_ssid() or ""
                    self._show_status_overlay("ALREADY CONNECTED", spinner=False, ssid=ssid, success=True)
                    self._schedule_overlay_hide(1100, nav_to_settings=False)
                    self._snapshot("reconnect_already_connected")
                    return
            except Exception:
                pass
            self._show_status_overlay("NO SAVED WIFI", spinner=False, ssid=None, success=False)
            self._schedule_overlay_hide(1100, nav_to_settings=False)
            self._snapshot("reconnect_no_saved")
            return
        self._remember_choice = False
        self._remember_ssid = None
        self._remember_password = None
        self._start_connect_attempt(saved_ssid, saved_password or "")
        self._snapshot("reconnect_saved")

    def _on_prev_clicked(self, event):
        if self._scanning:
            self._debug_nav("prev", self._page_index, self._page_index, len(self._networks), self._total_pages())
            return
        before = self._page_index
        total = len(self._networks)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if self._page_index > 0:
            self._page_index -= 1
            self._update_list_page()
            self._nav_counter += 1
        after = self._page_index
        self._debug_nav("prev", before, after, total, total_pages)

    def _on_next_clicked(self, event):
        if self._scanning:
            self._debug_nav("next", self._page_index, self._page_index, len(self._networks), self._total_pages())
            return
        total = len(self._networks)
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        before = self._page_index
        if (self._page_index + 1) < total_pages:
            self._page_index += 1
            self._update_list_page()
            self._nav_counter += 1
        after = self._page_index
        self._debug_nav("next", before, after, total, total_pages)

    def _remember_checked(self):
        if not self._password_view:
            return False
        cb = self._password_view.get("remember_cb")
        if not cb:
            return False
        try:
            return (cb.get_state() & lv.STATE.CHECKED) != 0
        except Exception:
            pass
        try:
            if hasattr(cb, "obj_has_state"):
                return cb.obj_has_state(lv.STATE.CHECKED)
        except Exception:
            pass
        return False

    def _on_connect_clicked(self, event=None):
        if not self._selected_ssid:
            return
        if self._connecting:
            self._debug_blocked("connect")
            return
        self._hide_keyboard()
        self._last_connect_success = False
        self._last_connect_ssid = None
        password = ""
        ta = self._password_view.get("password_ta") if self._password_view else None
        if ta:
            try:
                password = ta.get_text() or ""
            except Exception:
                password = ""
        password = password.strip()
        self._remember_choice = self._remember_checked()
        self._remember_ssid = self._selected_ssid
        self._remember_password = password
        self._start_connect_attempt(self._selected_ssid, password)

    def _start_connect_attempt(self, ssid, password):
        self._selected_ssid = ssid
        self._connect_attempt_ssid = ssid
        self._connect_attempt_password = password or ""
        self._last_connect_success = False
        self._last_connect_ssid = None

        wifi = self._ensure_wifi_manager()
        started = bool(wifi and wifi.start_connect(ssid, password, timeout_s=15))
        if not started:
            self._connecting = False
            self._set_password_status("Connect failed", ok=False)
            self._show_status_overlay("CONNECT FAILED", spinner=False, ssid=ssid or None, success=False)
            self._schedule_overlay_hide(1100, nav_to_settings=False)
            return

        self._connecting = True
        self._connect_started_ms = self._now_ms()
        self._connect_timeout_ms = 15000
        self._set_password_status("Connecting...", ok=None)
        self._show_status_overlay("CONNECTING TO", spinner=True, ssid=ssid, success=False)
        self._start_connect_timer()

    def _on_password_clicked(self, event):
        if self._connecting:
            self._debug_blocked("password")
            return
        self._show_keyboard()

    def _on_password_defocus(self, event):
        self._hide_keyboard()

    def _on_password_ready(self, event):
        self._on_connect_clicked(event)

    def _on_password_cancel(self, event):
        self._hide_keyboard()

    def _on_keyboard_ready(self, event):
        self._on_connect_clicked(event)

    def _on_keyboard_cancel(self, event):
        self._hide_keyboard()

    def _show_keyboard(self):
        if not self._keyboard or not self._password_view:
            return
        footer = self._password_view.get("footer")
        ta = self._password_view.get("password_ta")
        if not ta:
            return
        self._keyboard.show(ta, footer=footer, min_shift=40)
        self._snapshot("keyboard_show")

    def _hide_keyboard(self):
        if self._keyboard:
            self._keyboard.hide()
            self._snapshot("keyboard_hide")

    def _start_connect_timer(self):
        if self._connect_timer:
            return
        self._connect_timer = lv.timer_create(self._on_connect_timer, 300, None)

    def _stop_connect_timer(self):
        if self._connect_timer:
            try:
                self._connect_timer.delete()
            except Exception:
                pass
            self._connect_timer = None
        self._connect_started_ms = None
        self._connect_timeout_ms = None

    def _on_connect_timer(self, timer):
        if self._connect_timeout_ms is not None and self._elapsed_ms(self._connect_started_ms) >= self._connect_timeout_ms:
            self._stop_connect_timer()
            self._connecting = False
            self._show_status_overlay("CONNECTION TIMEOUT", spinner=False, ssid=self._selected_ssid or None, success=False)
            self._schedule_overlay_hide(1300, nav_to_settings=False)
            self._set_password_status("Connection timeout", ok=False)
            self._debug_connect_terminal("timeout", "timeout")
            return

        wifi = self._ensure_wifi_manager()
        result = wifi.poll_connect() if wifi else {"state": "fail", "reason": "wlan unavailable"}
        state = result.get("state")
        if state == "connecting":
            return

        self._stop_connect_timer()
        if state == "success":
            self._connecting = False
            ssid = self._selected_ssid or ""
            ok_symbol = self._symbol_ok()
            if ok_symbol:
                success_text = "{} CONNECTED".format(ok_symbol)
            else:
                success_text = "CONNECTED"
            self._set_password_status("Connected", ok=True)
            self._show_status_overlay(success_text, spinner=False, ssid=ssid, success=True)
            if self._connect_attempt_ssid:
                try:
                    wifi.save_last_successful_credentials(
                        self._connect_attempt_ssid, self._connect_attempt_password or ""
                    )
                except Exception:
                    pass
            if self._remember_choice:
                try:
                    wifi.save_credentials(self._remember_ssid, self._remember_password)
                except Exception:
                    pass
            self._last_connect_success = True
            self._last_connect_ssid = ssid
            if self.game_ui and ssid:
                self.game_ui.wifi_status_message = "Connected to {}".format(ssid)
            self._schedule_overlay_hide(1200, nav_to_settings=True)
            self._debug_connect_terminal("success", "got_ip")
            return

        if state not in ("fail", "idle"):
            state = "fail"
        reason = result.get("reason", "connect_fail")
        message = self._reason_to_message(reason)
        self._connecting = False
        self._show_status_overlay(message.upper(), spinner=False, ssid=self._selected_ssid or None, success=False)
        self._schedule_overlay_hide(1300, nav_to_settings=False)
        self._set_password_status(message, ok=False)
        self._last_connect_success = False
        self._last_connect_ssid = None
        self._debug_connect_terminal("fail", reason)

    def _reason_to_message(self, reason):
        if reason == "wrong_password":
            return "Wrong password"
        if reason == "no_ap":
            return "Network not found"
        if reason == "timeout":
            return "Connection timeout"
        if reason == "connect_fail":
            return "Connect failed"
        if reason == "wlan unavailable":
            return "WiFi unavailable"
        return "Connect failed"

    def _set_password_status(self, text, ok=None):
        if not self._password_view:
            return
        label = self._password_view.get("status_label")
        if not label:
            return
        try:
            if ok is False and text:
                text = text.upper()
            label.set_text(text or "")
            if ok is None:
                color = lv.color_hex(0x888888)
            elif ok:
                color = lv.color_hex(0x00ff00)
            else:
                color = lv.color_hex(0xFF6600)
            label.set_style_text_color(color, 0)
        except Exception:
            pass

    def _symbol_ok(self):
        try:
            if hasattr(lv, "SYMBOL") and hasattr(lv.SYMBOL, "OK"):
                return lv.SYMBOL.OK
        except Exception:
            pass
        return None

    def _set_overlay_text(self, primary, secondary=None, primary_color=None, secondary_color=None):
        if self._status_label:
            try:
                self._status_label.set_text(primary or "")
                if primary_color is not None:
                    self._status_label.set_style_text_color(primary_color, 0)
            except Exception:
                pass
        if self._status_ssid_label:
            try:
                self._status_ssid_label.set_text(secondary or "")
                if secondary_color is not None:
                    self._status_ssid_label.set_style_text_color(secondary_color, 0)
            except Exception:
                pass

    def _show_status_overlay(self, message, spinner=True, ssid=None, success=False):
        if not self._status_overlay:
            return
        if success:
            primary_color = lv.color_hex(0x00ff00)
            secondary_color = lv.color_hex(0xFFFFFF)
        else:
            primary_color = lv.color_hex(0xDDDDDD)
            secondary_color = lv.color_hex(0x888888)
        self._set_overlay_text(message, ssid, primary_color=primary_color, secondary_color=secondary_color)
        if self._status_spinner:
            try:
                if spinner:
                    self._status_spinner.remove_flag(lv.obj.FLAG.HIDDEN)
                else:
                    self._status_spinner.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
        try:
            self._status_overlay.remove_flag(lv.obj.FLAG.HIDDEN)
            if hasattr(self._status_overlay, "move_foreground"):
                self._status_overlay.move_foreground()
        except Exception:
            pass

    def _hide_status_overlay(self):
        if self._status_overlay:
            try:
                self._status_overlay.add_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(self._status_overlay, "move_background"):
                    self._status_overlay.move_background()
            except Exception:
                pass
        self._debug_overlay_state("overlay_hide")
        self._stop_overlay_timer()
        if self._active_view == "password":
            self._connecting = False

    def _schedule_overlay_hide(self, delay_ms, nav_to_settings=False):
        self._stop_overlay_timer()
        self._overlay_nav_to_settings = nav_to_settings
        self._overlay_timer = lv.timer_create(self._on_overlay_timer, delay_ms, None)

    def _stop_overlay_timer(self):
        if self._overlay_timer:
            try:
                self._overlay_timer.delete()
            except Exception:
                pass
            self._overlay_timer = None
        self._overlay_nav_to_settings = False

    def _on_overlay_timer(self, timer):
        nav_to_settings = self._overlay_nav_to_settings
        self._overlay_nav_to_settings = False
        self._hide_status_overlay()
        self._debug_overlay_state("overlay_timer_hide")
        if nav_to_settings and self.game_ui:
            self.game_ui.show_panel("settings")

    def _begin_scan(self, reset_page=False, delay_ms=30):
        self._scan_seq += 1
        self._scan_nav_counter = self._nav_counter
        self._scanning = True
        self._show_scanning_placeholders()
        self._schedule_scan(delay_ms, reset_page=reset_page, seq=self._scan_seq)

    def _apply_scan_results(self, results, reset_page=False, seq=None):
        if seq is not None and seq != self._scan_seq:
            return
        self._networks = results or []
        if reset_page and self._nav_counter == self._scan_nav_counter:
            self._page_index = 0
        self._update_list_page()
        self._scanning = False

    def _debug_overlay_state(self, label):
        if not wifi_debug.WIFI_FLOW_DEBUG:
            return
        if not self._status_overlay:
            return
        hidden = None
        try:
            if hasattr(self._status_overlay, "has_flag") and hasattr(lv.obj.FLAG, "HIDDEN"):
                hidden = self._status_overlay.has_flag(lv.obj.FLAG.HIDDEN)
        except Exception:
            hidden = None
        coords = self._coords(self._status_overlay)
        self.logger.info("[WIFI-FLOW] {} hidden={} coords={}".format(label, hidden, coords))

    def _show_scanning_placeholders(self):
        if not self._list_view:
            return
        for idx, row in enumerate(self._list_view["rows"]):
            if idx == 0:
                row["ssid"].set_text("Scanning...")
            else:
                row["ssid"].set_text("")
            row["rssi"].set_text("")

    def _schedule_scan(self, delay_ms, reset_page=False, seq=None):
        self._stop_scan_timer()
        self._scan_timer = lv.timer_create(lambda t: self._on_scan_timer(t, reset_page, seq), delay_ms, None)

    def _stop_scan_timer(self):
        if self._scan_timer:
            try:
                self._scan_timer.delete()
            except Exception:
                pass
            self._scan_timer = None

    def _on_scan_timer(self, timer, reset_page, seq):
        self._stop_scan_timer()
        if seq is not None and seq != self._scan_seq:
            return
        self._refresh_scan(reset_page=reset_page)

    def _debug_nav(self, action, before, after, total, total_pages):
        if not wifi_debug.WIFI_FLOW_DEBUG:
            return
        edge = None
        if action == "prev":
            edge = before <= 0
        elif action == "next":
            edge = (before + 1) >= total_pages
        self.logger.info(
            "[WIFI-FLOW] nav={} total={} pages={} page {}->{} edge={} scanning={}".format(
                action,
                total,
                total_pages,
                before,
                after,
                edge,
                self._scanning,
            )
        )

    def _debug_blocked(self, action):
        if not wifi_debug.WIFI_FLOW_DEBUG:
            return
        self.logger.info("[WIFI-FLOW] blocked action={} connecting={}".format(action, self._connecting))

    def _debug_connect_terminal(self, state, reason):
        if not wifi_debug.WIFI_FLOW_DEBUG:
            return
        hidden = None
        try:
            if self._status_overlay and hasattr(self._status_overlay, "has_flag") and hasattr(lv.obj.FLAG, "HIDDEN"):
                hidden = self._status_overlay.has_flag(lv.obj.FLAG.HIDDEN)
        except Exception:
            hidden = None
        self.logger.info(
            "[WIFI-FLOW] connect_terminal state={} reason={} connecting={} overlay_hidden={}".format(
                state,
                reason,
                self._connecting,
                hidden,
            )
        )

    def _total_pages(self):
        total = len(self._networks)
        return max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)

    def _coords(self, obj):
        if not obj:
            return None
        try:
            coords = obj.get_coords()
            if hasattr(coords, "x1"):
                return (coords.x1, coords.y1, coords.x2, coords.y2)
        except Exception:
            return None
        return None

    def _snapshot(self, label):
        if not wifi_debug.WIFI_FLOW_DEBUG:
            return
        viewport_coords = self._coords(self._content_root)
        viewport_size = None
        if viewport_coords:
            viewport_size = (
                viewport_coords[2] - viewport_coords[0] + 1,
                viewport_coords[3] - viewport_coords[1] + 1,
            )
        footer_coords = None
        footer_in_bounds = None
        if self._active_view == "list" and self._list_view:
            footer_coords = self._coords(self._list_view.get("footer"))
        elif self._active_view == "password" and self._password_view:
            footer_coords = self._coords(self._password_view.get("footer"))

        if viewport_coords and footer_coords:
            viewport_y1 = viewport_coords[1]
            viewport_y2 = viewport_coords[3]
            footer_in_bounds = footer_coords[1] >= viewport_y1 and footer_coords[3] <= viewport_y2

        kb = self._keyboard.get_keyboard() if self._keyboard else None
        kb_parent = None
        kb_coords = None
        if kb:
            try:
                kb_parent = kb.get_parent()
            except Exception:
                kb_parent = None
            kb_coords = self._coords(kb)

        wifi_debug.snapshot(
            self.logger,
            label,
            viewport_coords,
            viewport_size,
            footer_coords,
            footer_in_bounds,
            kb_parent,
            kb_coords,
            self._keyboard.get_shift() if self._keyboard else 0,
        )
