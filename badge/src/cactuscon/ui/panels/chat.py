"""Chat panel - device-to-device messaging UI.

Note on exception handling:
    This module uses defensive `except Exception: pass` patterns extensively for
    LVGL widget operations. This is intentional for embedded UI resilience:
    
    - LVGL objects may be deleted/invalid when the UI transitions
    - Widget state can be inconsistent during rapid user interaction
    - Memory pressure on ESP32 can cause unpredictable failures
    
    Silent failures in UI updates are preferred over crashes. Critical operations
    (like data persistence or network) DO log errors via logger.error().
"""

# 1. Standard library imports
import gc
import time

# 2. MicroPython-specific imports (with fallbacks)
try:
    import ujson
except ImportError:
    import json as ujson

try:
    import ubinascii
except ImportError:
    ubinascii = None

import bluetooth

# 3. Third-party library imports
import lvgl as lv

# 4. Local package imports
from cactuscon import config
from cactuscon.utils import Logger
from cactuscon.hw.bluetooth import BluetoothManager
from cactuscon.ui.panels.base_panel import BasePanel, ListContainer
from cactiotpad.crypto import generate_symkey1, derive_symkey2, derive_session_hash_and_key
from cactiotpad.exceptions import NetworkError, APIError, AuthenticationError
from cactiotpad.utils import default_device_id_generator

# Use centralized config for chat constants
CHAT_ADV_PREFIX = config.CHAT_ADV_PREFIX
CHAT_SERVICE_UUID_TEMPLATE = "CC14C001-0000-0000-0000-CAC71B072026"
CHAT_CHAR_UUID = bluetooth.UUID("CC14C002-C0DE-4BAD-9E14-CAC71B072026")


class ChatPanel(BasePanel):
    """
    Chat UI panel with chat list + modal overlays for chat history and pairing.
    """

    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=config.LOG_LEVEL, **kwargs):
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self.logger = Logger(logger_level)
        self.api_client = None
        self.wifi = None

        self._chat_list = None
        self._chat_buttons = {}
        self._active_session_hash = None

        self._chat_modal = None
        self._chat_modal_title = None
        self._chat_modal_content = None
        self._chat_modal_messages = None
        self._chat_input_ta = None
        self._chat_send_btn = None
        self._chat_delete_modal = None
        self._chat_delete_msg = None
        self._chat_delete_confirm_btn = None
        self._chat_status_label = None
        self._chat_page_size = 10
        self._chat_loaded_count = 0
        self._chat_total_count = 0
        self._chat_history_limited = False

        self._add_modal = None
        self._add_submit_btn = None
        self._add_symkey_label = None
        self._add_status = None
        self._pairing_symkey1 = None
        self._content_root = None
        self._content_root_y0 = 0
        self._kb_shift = 0

        self._delete_modal = None
        self._delete_list = None
        self._delete_status = None
        self._pending_session = None

        self._keyboard = None
        self._keyboard_hidden = True
        self._kb_warned = set()
        self._active_textarea = None

        # BLE pairing state
        self.bt = None
        self._bt_scanning = False
        self._bt_receiving = False
        self._bt_devices = []
        self._bt_list_dirty = False
        self._bt_selected = None
        self._bt_local_symkey1 = None
        self._bt_peer_symkey1 = None
        self._bt_peer_device_id = None
        self._bt_session_hash = None
        self._bt_confirm_code = None

        # BLE UI
        self._bt_list = None
        self._bt_receive_btn = None
        self._bt_confirm_btn = None
        self._bt_cancel_btn = None
        self._confirm_submit_btn = None
        self._bt_code_label = None
        self._bt_adv_label = None
        self._confirm_modal = None
        self._confirm_content = None
        self._confirm_code_label = None
        self._confirm_name_ta = None
        self._confirm_status_label = None
        self._confirm_hidden_for_spinner = False
        self._api_action_inflight = False

        # Periodic server sync while chat panel is visible (power-aware cadence)
        self._chat_sync_interval_ms = 60_000
        self._last_chat_sync_ms = 0
        self._active_chat_poll_interval_ms = 30_000
        self._last_active_chat_poll_ms = 0
        # Guard fast panel flapping: let WiFi radio settle before reconnect.
        self._last_chat_hide_ms = 0
        self._wifi_rearm_delay_ms = 1200
        self._wifi_rearm_ready_ms = 0
        self._wifi_rearm_pending = False
        
    def set_api_client(self, api_client):
        self.api_client = api_client

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        btn_back = lv.button(self.screen)
        btn_back.set_size(60, 30)
        btn_back.align(lv.ALIGN.TOP_LEFT, 10, 8)
        btn_back.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        btn_back.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn_back.set_style_border_width(1, 0)
        btn_back.add_event_cb(self._on_back, lv.EVENT.CLICKED, None)
        label_back = lv.label(btn_back)
        label_back.set_text("Back")
        label_back.set_style_text_color(lv.color_hex(0x00ff00), 0)
        label_back.center()

        title = lv.label(self.screen)
        title.set_text("Chats")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 12)
        self.ui_elements['title'] = title

        btn_add = lv.button(self.screen)
        btn_add.set_size(44, 34)
        btn_add.align(lv.ALIGN.TOP_RIGHT, -10, 8)
        btn_add.set_style_bg_color(lv.color_hex(0x00ff00), 0)
        btn_add.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn_add.set_style_border_width(2, 0)
        btn_add.add_event_cb(self._on_add_clicked, lv.EVENT.CLICKED, None)
        label_add = lv.label(btn_add)
        label_add.set_text("+")
        label_add.set_style_text_color(lv.color_hex(0x000000), 0)
        label_add.set_style_text_font(lv.font_montserrat_16, 0)
        label_add.center()
        self.ui_elements['btn_add'] = btn_add

        self._chat_list = ListContainer(self.screen)
        try:
            screen_w = self.screen.get_width()
            if screen_w and screen_w > 24:
                self._chat_list.set_size(screen_w - 14, 200)
            else:
                self._chat_list.set_size(lv.pct(100), 200)
        except Exception:
            self._chat_list.set_size(lv.pct(100), 200)
        self._chat_list.obj.align(lv.ALIGN.TOP_MID, 0, 50)
        self._chat_list.obj.set_style_bg_color(lv.color_hex(0x000000), 0)
        self._chat_list.obj.set_style_border_width(0, 0)
        # Keep list items left-aligned so the right side remains a scroll lane.
        try:
            self._chat_list.obj.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.START)
        except Exception:
            pass
        self.ui_elements['chat_list'] = self._chat_list.obj
        # Static scroll lane on the right side to visually distinguish the area.
        lane_h = 200
        try:
            measured_h = self._chat_list.obj.get_height()
            if measured_h and measured_h > 0:
                lane_h = measured_h
        except Exception:
            pass
        self._chat_scroll_lane = lv.obj(self.screen)
        self._chat_scroll_lane.set_size(12, lane_h)
        self._chat_scroll_lane.set_style_bg_color(lv.color_hex(0x333333), 0)
        self._chat_scroll_lane.set_style_bg_opa(255, 0)
        self._chat_scroll_lane.set_style_border_width(0, 0)
        self._chat_scroll_lane.set_style_radius(2, 0)
        try:
            self._chat_scroll_lane.clear_flag(lv.obj.FLAG.CLICKABLE)
        except Exception:
            pass
        try:
            self._chat_scroll_lane.align_to(self._chat_list.obj, lv.ALIGN.TOP_RIGHT, 2, 0)
        except Exception:
            self._chat_scroll_lane.align(lv.ALIGN.TOP_RIGHT, -2, 50)
        try:
            self._chat_scroll_lane.move_foreground()
        except Exception:
            pass
        self.ui_elements['chat_scroll_lane'] = self._chat_scroll_lane

        self._create_chat_modal()
        self._create_add_modal()
        self._create_delete_modal()
        self._create_confirm_modal()

    def on_show(self):
        gc.collect()
        if self.game_ui:
            try:
                self.game_ui.chat_has_unread = False
            except Exception:
                pass
        if self.wifi:
            try:
                self.wifi.set_auto_reconnect(True)
            except Exception:
                pass
            # Chat expects WiFi to be available while the panel is open; kick a
            # connect attempt early (non-blocking).
            self._kick_wifi_connect()
        self._schedule_wifi_rearm()
        self._last_chat_sync_ms = 0
        self.show_spinner("Loading chats...")
        self._spinner_pause()
        try:
            self._refresh_chat_list()
            self._hide_modal(self._chat_modal)
            self._hide_modal(self._add_modal)
            self._hide_modal(self._delete_modal)
        finally:
            self.hide_spinner()

    def on_hide(self):
        self._last_chat_hide_ms = self._ticks_ms()
        self._wifi_rearm_pending = False
        self._hide_keyboard()
        self._bt_stop_all()

    def on_cleanup(self):
        self._last_chat_hide_ms = self._ticks_ms()
        self._wifi_rearm_pending = False
        self._hide_keyboard()
        self._bt_stop_all()

    def update(self):
        # Process deferred BLE callbacks for pairing flow
        if self.bt:
            try:
                self.bt.process_pending()
            except Exception:
                pass
        self._bt_update_scan_state()
        self._maybe_rearm_wifi()
        if self._bt_list_dirty:
            self._bt_refresh_list()
            self._bt_list_dirty = False
        self._maybe_poll_active_chat_session()

    def _on_back(self, event):
        if self.game_ui:
            self.game_ui.show_panel('main_menu')

    def _on_add_clicked(self, event):
        self._open_add_modal()

    # ------------------------------------------------------------------
    # Chat list
    # ------------------------------------------------------------------

    def _refresh_chat_list(self):
        if not self._chat_list:
            return
        self._chat_buttons = {}
        self._chat_list.clean()

        sessions = {}
        if self.api_client:
            try:
                sessions = self.api_client.storage.get_chat_sessions().get("sessions", {})
            except Exception as exc:
                self.logger.debug(f"Chat sessions load failed: {exc}")
        items = []
        for session_hash, meta in sessions.items():
            last_ts = self._last_message_ts(session_hash)
            items.append((session_hash, self._display_chat_handle(meta), last_ts))
        items.sort(key=lambda row: (row[2] is None, row[2] or ""), reverse=True)

        for session_hash, handle, last_ts in items:
            text = handle
            if last_ts:
                text = "{}  ({})".format(handle, last_ts.split("T")[0])
            btn = self._chat_list.add_btn(None, text)
            try:
                btn.set_width(lv.pct(78))
            except Exception:
                pass
            btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
            btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
            btn.set_style_border_width(1, 0)
            event_type = lv.EVENT.CLICKED
            try:
                if hasattr(lv.EVENT, "SHORT_CLICKED"):
                    event_type = lv.EVENT.SHORT_CLICKED
            except Exception:
                pass
            btn.add_event_cb(self._on_chat_selected, event_type, None)
            self._chat_buttons[id(btn)] = session_hash
            # Also map child label target IDs; some LVGL builds deliver click
            # events on child objects instead of the button itself.
            try:
                lbl = btn.get_child(0)
                if lbl:
                    lbl.add_event_cb(self._on_chat_selected, event_type, None)
                    self._chat_buttons[id(lbl)] = session_hash
            except Exception:
                pass

    def _last_message_ts(self, session_hash):
        if not self.api_client:
            return None
        try:
            return self.api_client.last_chat_message_ts(session_hash)
        except Exception as exc:
            self.logger.debug(f"Last message timestamp lookup failed: {exc}")
            return None

    def _on_chat_selected(self, event):
        btn = self._get_event_target(event)
        session_hash = None
        # Walk up parent chain in case label/child object received event.
        for _ in range(4):
            if not btn:
                break
            session_hash = self._chat_buttons.get(id(btn))
            if session_hash:
                break
            try:
                btn = btn.get_parent()
            except Exception:
                break
        if not session_hash:
            return
        self.show_spinner("Loading chat...")
        self._spinner_pause()
        self._open_chat_modal(session_hash)
        self.hide_spinner()

    # ------------------------------------------------------------------
    # Chat modal
    # ------------------------------------------------------------------

    def _create_chat_modal(self):
        self._chat_modal = self._create_modal()
        content = lv.obj(self._chat_modal)
        content.set_size(lv.pct(100), lv.pct(100))
        content.align(lv.ALIGN.TOP_MID, 0, 0)
        content.set_style_bg_opa(0, 0)
        content.set_style_border_width(0, 0)
        content.set_style_pad_all(8, 0)
        content.set_style_pad_row(3, 0)
        content.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        content.add_flag(lv.obj.FLAG.SCROLLABLE)
        if hasattr(content, "set_scroll_dir") and hasattr(lv, "DIR"):
            content.set_scroll_dir(lv.DIR.VER)
        if hasattr(lv, "EVENT") and hasattr(lv.EVENT, "SCROLL_END"):
            content.add_event_cb(self._on_chat_scroll_end, lv.EVENT.SCROLL_END, None)
        self._chat_modal_content = content

        header = lv.obj(content)
        header.set_width(lv.pct(100))
        header.set_height(34)
        header.set_style_bg_opa(0, 0)
        header.set_style_border_width(0, 0)
        header.remove_flag(lv.obj.FLAG.SCROLLABLE)

        close_btn = lv.button(header)
        close_btn.set_size(60, 28)
        close_btn.align(lv.ALIGN.LEFT_MID, 0, 0)
        close_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        close_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        close_btn.set_style_border_width(1, 0)
        close_btn.add_event_cb(self._close_chat_modal, lv.EVENT.CLICKED, None)
        close_label = lv.label(close_btn)
        close_label.set_text("Back")
        close_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        close_label.center()

        self._chat_modal_title = lv.label(header)
        self._chat_modal_title.set_text("Chat")
        self._chat_modal_title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        self._chat_modal_title.align(lv.ALIGN.CENTER, 0, 0)

        delete_btn = lv.button(header)
        delete_btn.set_size(28, 28)
        delete_btn.align(lv.ALIGN.RIGHT_MID, 0, 0)
        delete_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        delete_btn.set_style_border_color(lv.color_hex(0xFF3333), 0)
        delete_btn.set_style_border_width(1, 0)
        delete_btn.add_event_cb(self._open_chat_delete_modal, lv.EVENT.CLICKED, None)
        delete_label = lv.label(delete_btn)
        delete_label.set_text("X")
        delete_label.set_style_text_color(lv.color_hex(0xFF6666), 0)
        delete_label.center()

        input_row = lv.obj(content)
        input_row.set_width(lv.pct(100))
        input_row.set_height(32)
        input_row.set_style_bg_opa(0, 0)
        input_row.set_style_border_width(0, 0)
        input_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        input_row.set_style_pad_column(6, 0)
        input_row.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        input_row.remove_flag(lv.obj.FLAG.SCROLLABLE)

        self._chat_input_ta = lv.textarea(input_row)
        self._chat_input_ta.set_height(32)
        self._chat_input_ta.set_one_line(True)
        self._chat_input_ta.set_max_length(160)
        self.style_textarea(self._chat_input_ta)
        self._chat_input_ta.set_placeholder_text("Type message")
        self._chat_input_ta.add_event_cb(self._on_chat_input_focus, lv.EVENT.CLICKED, None)
        self._chat_input_ta.add_event_cb(self._on_ta_defocus, lv.EVENT.DEFOCUSED, None)
        self._chat_input_ta.add_event_cb(self._on_ta_ready, lv.EVENT.READY, None)
        self._chat_input_ta.add_event_cb(self._on_ta_cancel, lv.EVENT.CANCEL, None)

        send_btn = lv.button(input_row)
        send_btn.set_size(32, 32)
        send_btn.set_style_bg_color(lv.color_hex(0x00ff00), 0)
        send_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        send_btn.set_style_border_width(1, 0)
        send_btn.add_event_cb(self._on_chat_send, lv.EVENT.CLICKED, None)
        send_label = lv.label(send_btn)
        send_label.set_text(">")
        send_label.set_style_text_color(lv.color_hex(0x000000), 0)
        send_label.center()
        try:
            total_w = content.get_width()
            if not total_w or total_w <= 0:
                total_w = 240
            input_w = max(120, total_w - 80)
            self._chat_input_ta.set_width(input_w)
        except Exception:
            self._chat_input_ta.set_width(lv.pct(100))
        self._chat_send_btn = send_btn

        self._chat_status_label = lv.label(content)
        self._chat_status_label.set_text("")
        self._chat_status_label.set_style_text_color(lv.color_hex(0x888888), 0)
        self._chat_status_label.add_flag(lv.obj.FLAG.HIDDEN)

        self._chat_modal_messages = lv.obj(content)
        self._chat_modal_messages.set_width(lv.pct(100))
        self._chat_modal_messages.set_style_bg_opa(0, 0)
        self._chat_modal_messages.set_style_border_width(0, 0)
        self._chat_modal_messages.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self._chat_modal_messages.set_style_pad_row(6, 0)
        self._chat_modal_messages.remove_flag(lv.obj.FLAG.SCROLLABLE)

        self._create_chat_delete_modal()
        self._hide_modal(self._chat_modal)

    def _create_chat_delete_modal(self):
        self._chat_delete_modal = self._create_modal()
        card = lv.obj(self._chat_delete_modal)
        card.set_size(240, 140)
        card.align(lv.ALIGN.CENTER, 0, 0)
        card.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        card.set_style_border_color(lv.color_hex(0xFF3333), 0)
        card.set_style_border_width(2, 0)
        card.set_style_radius(8, 0)
        card.set_style_pad_all(10, 0)

        title = lv.label(card)
        title.set_text("Delete Chat")
        title.set_style_text_color(lv.color_hex(0xFF6666), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 0)

        msg = lv.label(card)
        msg.set_text("Delete this chat?")
        msg.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        if hasattr(msg, "set_long_mode") and hasattr(lv, "LABEL_LONG"):
            msg.set_long_mode(lv.LABEL_LONG.WRAP)
        msg.set_width(220)
        msg.align(lv.ALIGN.TOP_MID, 0, 28)
        self._chat_delete_msg = msg

        actions = lv.obj(card)
        actions.set_size(lv.pct(100), 34)
        actions.align(lv.ALIGN.BOTTOM_MID, 0, 0)
        actions.set_style_bg_opa(0, 0)
        actions.set_style_border_width(0, 0)
        actions.set_flex_flow(lv.FLEX_FLOW.ROW)
        actions.set_style_pad_column(10, 0)
        actions.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)

        cancel_btn = lv.button(actions)
        cancel_btn.set_size(90, 30)
        cancel_btn.set_style_bg_color(lv.color_hex(0x333333), 0)
        cancel_btn.set_style_border_color(lv.color_hex(0x888888), 0)
        cancel_btn.set_style_border_width(1, 0)
        cancel_btn.add_event_cb(lambda e: self._hide_modal(self._chat_delete_modal), lv.EVENT.CLICKED, None)
        cancel_label = lv.label(cancel_btn)
        cancel_label.set_text("Cancel")
        cancel_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        cancel_label.center()

        confirm_btn = lv.button(actions)
        confirm_btn.set_size(90, 30)
        confirm_btn.set_style_bg_color(lv.color_hex(0x550000), 0)
        confirm_btn.set_style_border_color(lv.color_hex(0xFF3333), 0)
        confirm_btn.set_style_border_width(1, 0)
        confirm_btn.add_event_cb(self._confirm_delete_active_chat, lv.EVENT.CLICKED, None)
        confirm_label = lv.label(confirm_btn)
        confirm_label.set_text("Delete")
        confirm_label.set_style_text_color(lv.color_hex(0xFF6666), 0)
        confirm_label.center()

        self._hide_modal(self._chat_delete_modal)

    def _format_delete_error(self, exc):
        if isinstance(exc, AuthenticationError):
            return "Not registered"
        if isinstance(exc, NetworkError):
            return "Network error"
        if isinstance(exc, APIError):
            detail = self._extract_api_detail(exc)
            if detail:
                return detail[:80]
        try:
            msg = str(exc)
            return msg[:80] if msg else "Delete failed"
        except Exception:
            return "Delete failed"

    def _format_send_error(self, exc):
        # Special-case: 409 means the peer never accepted pairing (session exists locally only).
        if isinstance(exc, APIError):
            status = getattr(exc, "status_code", None)
            code = getattr(exc, "error_code", "") or ""
            if status == 409 or code == "CHAT_SESSION_UNPAIRED":
                return "Other device not paired. Delete chat and re-pair."
            detail = self._extract_api_detail(exc)
            if detail:
                return detail[:80]
        if isinstance(exc, AuthenticationError):
            return "Not registered"
        if isinstance(exc, NetworkError):
            return "Network error"
        try:
            msg = str(exc)
            return msg[:80] if msg else "Send failed"
        except Exception:
            return "Send failed"

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
        except Exception as exc:
            self.logger.debug(f"API error detail parse failed: {exc}")
        return str(body)

    def _open_chat_modal(self, session_hash):
        self._active_session_hash = session_hash
        self._content_root = self._chat_modal_content
        self._content_root_y0 = 0
        self._kb_shift = 0
        if self._chat_modal_title:
            title = "Chat"
            if self.api_client:
                meta = self.api_client.get_chat_session(session_hash) or {}
                handle = self._display_chat_handle(meta)
                if handle:
                    title = "{}".format(handle)
            self._chat_modal_title.set_text(title)
        self._chat_loaded_count = 0
        self._chat_total_count = self._count_chat_messages(session_hash)
        self._chat_history_limited = False
        self._last_active_chat_poll_ms = 0
        if self._chat_input_ta:
            try:
                self._chat_input_ta.set_text("")
            except Exception:
                pass
        self._render_chat_messages(reset=True)
        self._show_modal(self._chat_modal)
        try:
            self._chat_modal.move_foreground()
        except Exception:
            pass

    def _close_chat_modal(self, event=None):
        self._hide_keyboard()
        self._active_session_hash = None
        self._last_active_chat_poll_ms = 0
        # Default keyboard-shift root for add-contact modal workflow.
        self._content_root = self.ui_elements.get("add_content")
        self._content_root_y0 = 0
        self._kb_shift = 0
        self._hide_modal(self._chat_modal)

    def _on_chat_input_focus(self, event):
        self._active_textarea = self._chat_input_ta
        self._show_keyboard()

    def _on_chat_send(self, event=None):
        if self._api_action_inflight:
            return
        session_hash = self._active_session_hash
        if not session_hash or not self.api_client:
            return
        msg = ""
        if self._chat_input_ta:
            try:
                msg = (self._chat_input_ta.get_text() or "").strip()
            except Exception:
                msg = ""
        if not msg:
            return

        meta = self.api_client.get_chat_session(session_hash) or {}
        session_key = meta.get("session_key")
        if not session_key:
            self._set_chat_status("Missing session key", error=True)
            return

        if not self._require_wifi_for_action(
            status_cb=lambda text, is_err: self._set_chat_status(text, error=bool(is_err))
        ):
            return

        self._api_action_inflight = True
        self._set_chat_composer_enabled(False)
        try:
            self._hide_keyboard()
            self.show_spinner("Sending...")
            self._spinner_pause()
            # Reduce the chance of an allocation-triggered freeze during urequests.
            try:
                gc.collect()
            except Exception:
                pass
            encrypted = self.api_client.encrypt_message(session_key, msg)
            resp = self.api_client.send_chat_message(
                session_hash,
                encrypted,
                timeout=getattr(config, "CACTIOT_TIMEOUT", None),
                max_retries=0,
                retry=False,
            )
            ts = None
            if isinstance(resp, dict):
                ts = resp.get("ts")
            if not ts:
                self._set_chat_status("Send not confirmed", error=True)
                return
            self.api_client.store_chat_message(session_hash, ts, encrypted, sender="self")
            self._chat_total_count += 1
            self._chat_loaded_count += 1
            if not self._prepend_chat_row(ts, msg, sender="self"):
                # Fallback if LVGL child reordering isn't available on this build.
                self._render_chat_messages(reset=True)
            try:
                self._chat_input_ta.set_text("")
            except Exception:
                pass
            self._set_chat_status("")
        except Exception as exc:
            self.logger.info(f"[CHAT] send failed: {exc}")
            self._set_chat_status(self._format_send_error(exc), error=True)
        finally:
            self.hide_spinner()
            self._set_chat_composer_enabled(True)
            self._api_action_inflight = False

    def _on_chat_scroll_end(self, event):
        if not self._active_session_hash:
            return
        if not self._is_scroll_at_bottom(self._chat_modal_content):
            return
        if self._chat_history_limited:
            return
        if self._chat_loaded_count >= self._chat_total_count:
            return
        if self._is_low_memory():
            self._chat_history_limited = True
            self._set_chat_status("History limit reached (low memory)", error=True)
            return
        self._render_chat_messages(reset=False)

    def _count_chat_messages(self, session_hash):
        if not self.api_client:
            return 0
        try:
            return int(self.api_client.count_chat_messages(session_hash) or 0)
        except Exception as exc:
            self.logger.debug(f"Count chat messages failed: {exc}")
            return 0

    def _render_chat_messages(self, reset=False):
        if not self._chat_modal_messages or not self._active_session_hash or not self.api_client:
            return
        if reset:
            self._chat_loaded_count = 0
            self._clear_chat_message_rows()

        batch = self._load_chat_batch(self._active_session_hash, self._chat_loaded_count, self._chat_page_size)
        if not batch:
            if self._chat_loaded_count == 0:
                self._set_chat_status("No messages yet")
            return

        for row in batch:
            line = lv.label(self._chat_modal_messages)
            try:
                if hasattr(lv.label, "LONG"):
                    line.set_long_mode(lv.label.LONG.WRAP)
                else:
                    line.set_long_mode(0)  # WRAP fallback for stripped bindings
            except Exception:
                pass
            line.set_width(lv.pct(100))
            line.set_text(self._format_chat_row_text(row))
            line.set_style_text_color(self._chat_row_color(row), 0)
        self._chat_loaded_count += len(batch)

    def _clear_chat_message_rows(self):
        if not self._chat_modal_messages:
            return
        while self._chat_modal_messages.get_child_count() > 0:
            child = self._chat_modal_messages.get_child(0)
            try:
                child.delete()
            except Exception:
                break

    def _load_chat_batch(self, session_hash, loaded, page_size):
        if not self.api_client:
            return []
        try:
            selected = self.api_client.get_chat_batch(
                session_hash,
                offset=loaded,
                limit=page_size,
                newest_first=True,
            )
        except Exception as exc:
            self.logger.warning(f"Load chat batch failed: {exc}")
            return []
        meta = self.api_client.get_chat_session(session_hash) or {}
        session_key = meta.get("session_key")
        rows = []
        for entry in selected:
            raw = entry.get("msg") or ""
            text = raw
            sender = entry.get("sender") or "peer"
            if session_key and raw:
                try:
                    text = self.api_client.decrypt_message(session_key, raw)
                except Exception as exc:
                    self.logger.debug(f"Chat message decrypt failed: {exc}")
                    text = "[decrypt error]"
            ts = entry.get("ts") or ""
            rows.append({"ts": ts, "text": text, "sender": sender})
        return rows

    def _set_chat_status(self, text, error=False):
        if not self._chat_status_label:
            return
        self._chat_status_label.set_text(text or "")
        color = lv.color_hex(0xFF8800) if error else lv.color_hex(0x888888)
        self._chat_status_label.set_style_text_color(color, 0)
        if text:
            self._chat_status_label.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            self._chat_status_label.add_flag(lv.obj.FLAG.HIDDEN)

    def _prepend_chat_row(self, ts, text, sender="self"):
        if not self._chat_modal_messages:
            return False
        try:
            line = lv.label(self._chat_modal_messages)
            try:
                if hasattr(lv.label, "LONG"):
                    line.set_long_mode(lv.label.LONG.WRAP)
                else:
                    line.set_long_mode(0)  # WRAP fallback for stripped bindings
            except Exception:
                pass
            line.set_width(lv.pct(100))
            row = {"ts": ts or "", "text": text or "", "sender": sender}
            line.set_text(self._format_chat_row_text(row))
            line.set_style_text_color(self._chat_row_color(row), 0)
            if hasattr(line, "move_to_index"):
                line.move_to_index(0)
                return True
        except Exception:
            return False
        return False

    def _chat_row_color(self, row):
        sender = (row.get("sender") or "peer").lower()
        if sender == "peer":
            return lv.color_hex(0x00ff00)
        return lv.color_hex(0xCCCCCC)

    def _chat_sender_label(self, row):
        sender = (row.get("sender") or "peer").lower()
        if sender == "self":
            return "You"
        meta = self.api_client.get_chat_session(self._active_session_hash) or {}
        return self._display_chat_handle(meta) or "Peer"

    def _format_message_ts(self, ts):
        # Input typically ISO-ish, output YYMMDD HH:MM:SS
        ts = (ts or "").strip()
        if len(ts) >= 19 and ts[4] == "-" and ts[7] == "-":
            yy = ts[2:4]
            mm = ts[5:7]
            dd = ts[8:10]
            hh = ts[11:13]
            mi = ts[14:16]
            ss = ts[17:19]
            return "{}{}{} {}:{}:{}".format(yy, mm, dd, hh, mi, ss)
        return ts[:17]

    def _format_chat_row_text(self, row):
        ts = self._format_message_ts(row.get("ts"))
        who = self._chat_sender_label(row)
        return "{} {}: {}".format(ts, who, row.get("text", ""))

    def _is_scroll_at_bottom(self, obj):
        if not obj:
            return False
        try:
            if hasattr(obj, "get_scroll_bottom"):
                return obj.get_scroll_bottom() <= 2
        except Exception:
            pass
        return False

    def _is_low_memory(self):
        try:
            # Force a collection before measuring so transient garbage
            # doesn't trip the low-memory guard.
            gc.collect()
            free = gc.mem_free()
            alloc = gc.mem_alloc()
            total = free + alloc
            if total <= 0:
                return False
            return (free / total) < 0.10
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Add contact modal
    # ------------------------------------------------------------------

    def _create_add_modal(self):
        self._add_modal = self._create_modal()

        content = lv.obj(self._add_modal)
        content.set_size(lv.pct(100), lv.pct(100))
        content.align(lv.ALIGN.TOP_MID, 0, 0)
        content.set_style_bg_opa(0, 0)
        content.set_style_border_width(0, 0)
        content.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        content.set_style_pad_row(6, 0)
        content.set_style_pad_all(8, 0)
        content.set_style_pad_bottom(24, 0)
        content.add_flag(lv.obj.FLAG.SCROLLABLE)
        if hasattr(content, "set_scroll_dir") and hasattr(lv, "DIR"):
            content.set_scroll_dir(lv.DIR.VER)
        if hasattr(content, "set_scrollbar_mode") and hasattr(lv, "SCROLLBAR_MODE"):
            content.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)
        self.ui_elements["add_content"] = content
        self._content_root = content
        self._content_root_y0 = 0
        self._kb_shift = 0

        header = lv.obj(content)
        header.set_width(lv.pct(100))
        header.set_height(34)
        header.set_style_bg_opa(0, 0)
        header.set_style_border_width(0, 0)
        header.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["add_header"] = header

        close_btn = lv.button(header)
        close_btn.set_size(60, 28)
        close_btn.align(lv.ALIGN.LEFT_MID, 0, 0)
        close_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        close_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        close_btn.set_style_border_width(1, 0)
        close_btn.add_event_cb(self._close_add_modal, lv.EVENT.CLICKED, None)
        close_label = lv.label(close_btn)
        close_label.set_text("Back")
        close_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        close_label.center()

        title = lv.label(header)
        title.set_text("Add Contact")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.CENTER, 0, 0)
        self.ui_elements["add_title"] = title

        submit_btn = lv.button(header)
        submit_btn.set_size(60, 26)
        submit_btn.align(lv.ALIGN.RIGHT_MID, 0, 0)
        submit_btn.set_style_bg_color(lv.color_hex(0x00ff00), 0)
        submit_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        submit_btn.set_style_border_width(1, 0)
        submit_btn.add_event_cb(self._on_add_submit, lv.EVENT.CLICKED, None)
        submit_label = lv.label(submit_btn)
        submit_label.set_text("Scan")
        submit_label.set_style_text_color(lv.color_hex(0x000000), 0)
        submit_label.center()
        self._add_submit_btn = submit_btn

        symkey_label = lv.label(content)
        symkey_label.set_text("Key (share this): --")
        symkey_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        symkey_label.add_flag(lv.obj.FLAG.HIDDEN)
        self._add_symkey_label = symkey_label

        receive_btn = lv.button(content)
        receive_btn.set_size(120, 28)
        receive_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        receive_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        receive_btn.set_style_border_width(1, 0)
        receive_btn.add_event_cb(self._on_receive_toggle, lv.EVENT.CLICKED, None)
        receive_label = lv.label(receive_btn)
        receive_label.set_text("Receive")
        receive_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        receive_label.center()
        self._bt_receive_btn = receive_btn

        adv_label = lv.label(content)
        adv_label.set_text("Your peering ID: --")
        adv_label.set_style_text_font(lv.font_montserrat_12, 0)
        adv_label.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        self._bt_adv_label = adv_label

        list_label = lv.label(content)
        list_label.set_text("Nearby peers")
        list_label.set_style_text_color(lv.color_hex(0xCCCCCC), 0)

        self._bt_list = ListContainer(content, width=lv.pct(100), height=120)
        self._bt_list.obj.set_style_bg_color(lv.color_hex(0x000000), 0)
        self._bt_list.obj.set_style_border_width(1, 0)
        self._bt_list.obj.set_style_border_color(lv.color_hex(0x333333), 0)

        self._bt_code_label = lv.label(content)
        self._bt_code_label.set_text("")
        self._bt_code_label.set_style_text_color(lv.color_hex(0xFFFF00), 0)

        self._add_status = lv.label(self._add_modal)
        self._add_status.set_text("")
        self._add_status.set_style_text_color(lv.color_hex(0x888888), 0)
        self._add_status.align(lv.ALIGN.BOTTOM_LEFT, 10, -10)

        self._ensure_keyboard()
        self._hide_modal(self._add_modal)

    def _open_add_modal(self):
        self._pending_session = None
        self._add_status.set_text("")
        if self._confirm_status_label:
            self._confirm_status_label.set_text("")
        self.show_spinner("Preparing pairing...")
        self._spinner_pause()
        try:
            self._kick_wifi_connect()
            device_id = self._get_local_device_id()
            from cactiotpad.crypto import generate_symkey1
            if self.api_client:
                try:
                    pairing = self.api_client.start_pairing()
                    self._pairing_symkey1 = pairing.get("symkey1")
                    device_id = pairing.get("device_id") or device_id
                except Exception as exc:
                    if not self._wifi_snapshot().get("is_connected"):
                        self._add_status.set_text("Offline - connect WiFi")
                    self.logger.debug(f"Pairing start failed: {exc}")
                    self._pairing_symkey1 = generate_symkey1()
            else:
                if not self._wifi_snapshot().get("is_connected"):
                    self._add_status.set_text("Offline - connect WiFi")
                self._pairing_symkey1 = generate_symkey1()
            compact_device = self._compact_device_id(device_id) if device_id else None
            self._add_symkey_label.set_text("Key (share this): {}".format(
                self._build_pairing_key(compact_device, self._pairing_symkey1)
            ))
            if self._confirm_name_ta:
                self._confirm_name_ta.set_text("")
            self._bt_start_scan()
            self._show_modal(self._add_modal)
        finally:
            self.hide_spinner()

    def _close_add_modal(self, event=None):
        self._hide_keyboard()
        self._hide_modal(self._add_modal)

    def _on_add_submit(self, event):
        self.logger.info("[CHAT] Add modal rescan clicked")
        try:
            self._bt_start_scan()
        except Exception as exc:
            self._add_status.set_text("Scan failed")
            self.logger.debug(f"Chat scan error: {exc}")

    def _try_store_pending_session(self):
        if not self._pending_session:
            return True
        data = self.api_client.storage.get_chat_sessions()
        sessions = data.get("sessions", {})
        sessions[self._pending_session["session_hash"]] = {
            "handle": self._pending_session["handle"],
            "symkey2": self._pending_session["symkey2"],
            "session_key": self._pending_session["session_key"],
            "peer_device_id": self._pending_session["peer_device_id"],
        }
        data["sessions"] = sessions
        size = len(ujson.dumps(data))
        if size > 4096:
            return False
        self.api_client.storage.set_chat_sessions(data)
        return True

    # ------------------------------------------------------------------
    # Delete-old-chats modal
    # ------------------------------------------------------------------

    def _create_delete_modal(self):
        self._delete_modal = self._create_modal()

        title = lv.label(self._delete_modal)
        title.set_text("Storage Full")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 10)

        info = lv.label(self._delete_modal)
        info.set_text("Delete chats to make room")
        info.set_style_text_color(lv.color_hex(0xCCCCCC), 0)
        info.align(lv.ALIGN.TOP_MID, 0, 35)

        self._delete_list = lv.obj(self._delete_modal)
        self._delete_list.set_size(lv.pct(100), 170)
        self._delete_list.align(lv.ALIGN.TOP_MID, 0, 60)
        self._delete_list.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self._delete_list.set_style_pad_row(6, 0)
        self._delete_list.set_style_pad_all(8, 0)
        self._delete_list.set_style_bg_color(lv.color_hex(0x000000), 0)
        self._delete_list.set_style_border_width(0, 0)

        done_btn = lv.button(self._delete_modal)
        done_btn.set_size(90, 28)
        done_btn.align(lv.ALIGN.BOTTOM_RIGHT, -10, -10)
        done_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        done_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        done_btn.set_style_border_width(1, 0)
        done_btn.add_event_cb(self._on_delete_done, lv.EVENT.CLICKED, None)
        done_label = lv.label(done_btn)
        done_label.set_text("Done")
        done_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        done_label.center()

        self._delete_status = lv.label(self._delete_modal)
        self._delete_status.set_text("")
        self._delete_status.set_style_text_color(lv.color_hex(0x888888), 0)
        self._delete_status.align(lv.ALIGN.BOTTOM_LEFT, 10, -10)

        self._hide_modal(self._delete_modal)

    def _create_confirm_modal(self):
        self._confirm_modal = self._create_modal()
        self._confirm_content = lv.obj(self._confirm_modal)
        self._confirm_content.set_size(lv.pct(100), lv.pct(100))
        self._confirm_content.align(lv.ALIGN.TOP_MID, 0, 0)
        self._confirm_content.set_style_bg_opa(0, 0)
        self._confirm_content.set_style_border_width(0, 0)
        self._confirm_content.set_style_pad_all(10, 0)
        self._confirm_content.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self._confirm_content.set_style_pad_row(8, 0)
        try:
            self._confirm_content.set_flex_align(
                lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER
            )
        except Exception:
            pass

        name_label = lv.label(self._confirm_content)
        name_label.set_text("Contact Name (2+ chars)")
        name_label.set_style_text_color(lv.color_hex(0xCCCCCC), 0)

        self._confirm_name_ta = lv.textarea(self._confirm_content)
        self._confirm_name_ta.set_size(220, 32)
        self._confirm_name_ta.set_one_line(True)
        self._confirm_name_ta.set_max_length(24)
        self.style_textarea(self._confirm_name_ta)
        self._confirm_name_ta.set_placeholder_text("e.g. Alice")
        self._confirm_name_ta.add_event_cb(self._on_confirm_name_focus, lv.EVENT.CLICKED, None)
        self._confirm_name_ta.add_event_cb(self._on_ta_defocus, lv.EVENT.DEFOCUSED, None)
        self._confirm_name_ta.add_event_cb(self._on_ta_ready, lv.EVENT.READY, None)
        self._confirm_name_ta.add_event_cb(self._on_ta_cancel, lv.EVENT.CANCEL, None)

        title = lv.label(self._confirm_content)
        title.set_text("Confirm Code On Both Devices")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)

        code = lv.label(self._confirm_content)
        code.set_text("----")
        code.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        code.set_style_text_font(lv.font_montserrat_16, 0)
        self._confirm_code_label = code

        # Keep all confirm content centered as requested.
        for lbl in (name_label, title, code):
            try:
                lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
                lbl.set_width(lv.pct(100))
            except Exception:
                pass

        try:
            self._confirm_name_ta.set_align(lv.ALIGN.CENTER)
        except Exception:
            pass

        self._confirm_status_label = lv.label(self._confirm_content)
        self._confirm_status_label.set_text("")
        self._confirm_status_label.set_style_text_color(lv.color_hex(0xFF8800), 0)

        actions = lv.obj(self._confirm_content)
        actions.set_size(lv.pct(100), 40)
        actions.set_style_bg_opa(0, 0)
        actions.set_style_border_width(0, 0)
        actions.remove_flag(lv.obj.FLAG.SCROLLABLE)

        confirm_btn = lv.button(actions)
        confirm_btn.set_size(120, 32)
        confirm_btn.align(lv.ALIGN.LEFT_MID, 0, 0)
        confirm_btn.set_style_bg_color(lv.color_hex(0x00ff00), 0)
        confirm_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        confirm_btn.set_style_border_width(1, 0)
        confirm_btn.add_event_cb(self._on_confirm_pair, lv.EVENT.CLICKED, None)
        confirm_label = lv.label(confirm_btn)
        confirm_label.set_text("Confirm")
        confirm_label.set_style_text_color(lv.color_hex(0x000000), 0)
        confirm_label.center()

        cancel_btn = lv.button(actions)
        cancel_btn.set_size(120, 32)
        cancel_btn.align(lv.ALIGN.RIGHT_MID, 0, 0)
        cancel_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        cancel_btn.set_style_border_color(lv.color_hex(0xFF6600), 0)
        cancel_btn.set_style_border_width(1, 0)
        cancel_btn.add_event_cb(self._on_cancel_pair, lv.EVENT.CLICKED, None)
        cancel_label = lv.label(cancel_btn)
        cancel_label.set_text("Cancel")
        cancel_label.set_style_text_color(lv.color_hex(0xFF6600), 0)
        cancel_label.center()

        self._hide_modal(self._confirm_modal)

    def _open_delete_modal(self):
        self._delete_status.set_text("")
        self.show_spinner("Loading chats...")
        self._spinner_pause()
        try:
            self._refresh_delete_list()
            self._show_modal(self._delete_modal)
        finally:
            self.hide_spinner()

    def _refresh_delete_list(self):
        if not self._delete_list:
            return
        for i in range(self._delete_list.get_child_count()):
            child = self._delete_list.get_child(i)
            try:
                child.delete()
            except Exception:
                pass

        if not self.api_client:
            return
        sessions = self.api_client.storage.get_chat_sessions().get("sessions", {})
        candidates = []
        for session_hash, meta in sessions.items():
            empty = self._is_chat_empty(session_hash)
            last_ts = self._last_message_ts(session_hash) or ""
            candidates.append((session_hash, meta.get("handle") or "Unknown", empty, last_ts))

        empties = [c for c in candidates if c[2]]
        nonempties = [c for c in candidates if not c[2]]
        nonempties.sort(key=lambda row: row[3])
        ordered = empties + nonempties

        self._delete_buttons = {}
        for session_hash, handle, empty, last_ts in ordered:
            row = lv.obj(self._delete_list)
            row.set_size(lv.pct(100), 28)
            row.set_flex_flow(lv.FLEX_FLOW.ROW)
            row.set_style_pad_column(8, 0)
            row.set_style_bg_opa(0, 0)

            label = lv.label(row)
            label.set_text(handle)
            label.set_style_text_color(lv.color_hex(0xCCCCCC), 0)

            btn = lv.button(row)
            btn.set_size(28, 24)
            btn.set_style_bg_color(lv.color_hex(0x550000), 0)
            btn.set_style_border_color(lv.color_hex(0xFF3333), 0)
            btn.set_style_border_width(1, 0)
            btn.add_event_cb(self._on_delete_chat, lv.EVENT.CLICKED, None)
            x_label = lv.label(btn)
            x_label.set_text("X")
            x_label.set_style_text_color(lv.color_hex(0xFF6666), 0)
            x_label.center()

            self._delete_buttons[id(btn)] = session_hash

    def _on_delete_chat(self, event):
        btn = self._get_event_target(event)
        session_hash = self._delete_buttons.get(id(btn))
        if not session_hash:
            return
        if self._api_action_inflight:
            return
        if not self._require_wifi_for_action(
            status_cb=lambda text, is_err: self._delete_status.set_text(text)
        ):
            return
        if not self.api_client:
            self._delete_status.set_text("API not ready")
            return
        self._api_action_inflight = True
        self._set_obj_enabled(btn, False)
        self.show_spinner("Deleting chat...")
        self._spinner_pause()
        try:
            self.api_client.delete_chat_session_remote(session_hash)
        except Exception as exc:
            self._delete_status.set_text(self._format_delete_error(exc))
            self.logger.debug(f"Chat delete failed: {exc}")
            self.hide_spinner()
            self._set_obj_enabled(btn, True)
            self._api_action_inflight = False
            return
        self._refresh_delete_list()
        self.hide_spinner()
        self._api_action_inflight = False

    def _open_chat_delete_modal(self, event=None):
        if not self._active_session_hash:
            return
        if self._chat_delete_msg:
            name = "this chat"
            if self.api_client:
                meta = self.api_client.get_chat_session(self._active_session_hash) or {}
                handle = self._display_chat_handle(meta)
                if handle:
                    name = handle
            self._chat_delete_msg.set_text(f"Delete chat with {name}?")
        self._show_modal(self._chat_delete_modal)
        try:
            self._chat_delete_modal.move_foreground()
        except Exception:
            pass

    def _confirm_delete_active_chat(self, event=None):
        session_hash = self._active_session_hash
        if not session_hash:
            return
        if self._api_action_inflight:
            return
        if not self._require_wifi_for_action(
            status_cb=lambda text, is_err: self._set_chat_status(text, error=True)
        ):
            return
        if not self.api_client:
            self._set_chat_status("API not ready", error=True)
            return
        self._hide_modal(self._chat_delete_modal)
        self._api_action_inflight = True
        self.show_spinner("Deleting chat...")
        self._spinner_pause()
        try:
            self.api_client.delete_chat_session_remote(session_hash)
        except Exception as exc:
            self._set_chat_status(self._format_delete_error(exc), error=True)
            self.logger.debug(f"Chat delete failed: {exc}")
            self.hide_spinner()
            self._api_action_inflight = False
            return
        self._active_session_hash = None
        self._refresh_chat_list()
        self.hide_spinner()
        self._api_action_inflight = False
        self._hide_modal(self._chat_modal)

    def _on_delete_done(self, event):
        self.show_spinner("Saving...")
        self._spinner_pause()
        if self._pending_session and self._try_store_pending_session():
            session_hash = self._pending_session["session_hash"]
            self._pending_session = None
            self._hide_modal(self._delete_modal)
            self._hide_modal(self._add_modal)
            self._refresh_chat_list()
            self.hide_spinner()
            return
        self._delete_status.set_text("Still full")
        self.hide_spinner()

    def _is_chat_empty(self, session_hash):
        return self._count_chat_messages(session_hash) == 0

    # ------------------------------------------------------------------
    # Keyboard helpers
    # ------------------------------------------------------------------

    def _ensure_keyboard(self):
        if self._keyboard:
            return
        # Keep keyboard on this screen to avoid preload flash; size/position set here.
        self._keyboard = lv.keyboard(self.screen)
        self._position_keyboard()
        if hasattr(self._keyboard, "set_mode") and hasattr(lv, "KEYBOARD_MODE"):
            if hasattr(lv.KEYBOARD_MODE, "TEXT"):
                self._keyboard.set_mode(lv.KEYBOARD_MODE.TEXT)
        self._keyboard.add_event_cb(self._on_keyboard_ready, lv.EVENT.READY, None)
        self._keyboard.add_event_cb(self._on_keyboard_cancel, lv.EVENT.CANCEL, None)
        self._obj_hide(self._keyboard)
        self.ui_elements["keyboard"] = self._keyboard

    def _show_keyboard(self):
        self._ensure_keyboard()
        textarea = self._active_textarea
        if not self._keyboard or not textarea or self._keyboard_is_visible():
            return
        self._position_keyboard()
        if not self._bind_keyboard_textarea():
            return
        if not self._obj_show(self._keyboard):
            return
        if hasattr(self._keyboard, "set_cursor_manage"):
            self._keyboard.set_cursor_manage(True)
        if textarea and hasattr(textarea, "add_state") and hasattr(lv, "STATE"):
            if hasattr(lv.STATE, "FOCUSED"):
                textarea.add_state(lv.STATE.FOCUSED)
        if hasattr(self._keyboard, "move_foreground"):
            try:
                self._keyboard.move_foreground()
            except Exception as exc:
                self._warn_once("kb_foreground", "Keyboard foreground failed: {}".format(exc))
        self._apply_keyboard_shift()

    def _hide_keyboard(self):
        if not self._keyboard or not self._keyboard_is_visible():
            return
        if hasattr(self._keyboard, "set_textarea"):
            self._keyboard.set_textarea(None)
        self._restore_keyboard_shift()
        # Clear focused state on any active textarea
        try:
            if hasattr(lv, "STATE") and hasattr(lv.STATE, "FOCUSED"):
                try:
                    if self._chat_input_ta:
                        self._chat_input_ta.clear_state(lv.STATE.FOCUSED)
                    if self._confirm_name_ta:
                        self._confirm_name_ta.clear_state(lv.STATE.FOCUSED)
                except Exception:
                    pass
        except Exception:
            pass
        self._obj_hide(self._keyboard)

    def _on_keyboard_ready(self, event):
        self._hide_keyboard()

    def _on_keyboard_cancel(self, event):
        self._hide_keyboard()

    def _on_confirm_name_focus(self, event):
        self._active_textarea = self._confirm_name_ta
        self._show_keyboard()

    def _on_ta_ready(self, event):
        if self._active_textarea == self._chat_input_ta:
            self._on_chat_send(event)
        self._hide_keyboard()
        self._active_textarea = None

    def _on_ta_cancel(self, event):
        self._hide_keyboard()
        self._active_textarea = None

    def _on_ta_defocus(self, event):
        if self._keyboard_is_visible():
            self._hide_keyboard()
        self._active_textarea = None

    # ------------------------------------------------------------------
    # BLE pairing helpers
    # ------------------------------------------------------------------

    def _bt_reset_state(self):
        self._bt_scanning = False
        self._bt_receiving = False
        self._bt_devices = []
        self._bt_selected = None
        self._bt_local_symkey1 = None
        self._bt_peer_symkey1 = None
        self._bt_peer_device_id = None
        self._bt_session_hash = None
        self._bt_confirm_code = None
        if self._bt_code_label:
            self._bt_code_label.set_text("")
        if self._bt_list:
            try:
                self._bt_list.clean()
            except Exception:
                pass
        if self._bt_adv_label:
            self._bt_adv_label.set_text("Your Device ID: --")

    def _bt_stop_all(self):
        if not self.bt:
            return
        try:
            if self.bt.is_scanning():
                self.bt.stop_scan()
        except Exception:
            pass
        try:
            if hasattr(self.bt, "clear_devices"):
                self.bt.clear_devices()
        except Exception:
            pass
        try:
            if self.bt.adv_active:
                self.bt.stop_advertising()
        except Exception:
            pass
        try:
            if self.bt.is_server_running():
                self.bt.stop_gatt_server()
        except Exception:
            pass
        self._bt_reset_state()

    def _bt_start_scan(self):
        if not self.bt:
            self._add_status.set_text("Bluetooth unavailable")
            return
        self._bt_stop_all()
        self._bt_receiving = False
        try:
            self.bt.set_data_callback(self._bt_on_client_data)
        except Exception:
            pass
        try:
            self.bt.start_scan(callback=self._bt_on_scan_result)
            self._bt_scanning = True
            self._add_status.set_text("Scanning nearby peers...")
        except Exception as exc:
            self._add_status.set_text("Scan failed")
            self.logger.info(f"[CHAT] scan start failed: {exc}")

    def _bt_update_scan_state(self):
        if not self.bt or not self._bt_scanning:
            return
        try:
            if self.bt.is_scanning():
                return
        except Exception:
            return
        self._bt_scanning = False
        # Clear stale scan status once controller reports scan complete.
        try:
            if self._add_status and self._add_status.get_text() == "Scanning nearby peers...":
                self._add_status.set_text("")
        except Exception:
            pass

    def _bt_start_receive(self):
        if not self.bt:
            self._add_status.set_text("Bluetooth unavailable")
            return
        self._bt_stop_all()
        self._bt_receiving = True
        self._bt_local_symkey1 = generate_symkey1()
        try:
            # Setup GATT server for incoming pairing
            service_uuid = BluetoothManager.create_device_uuid(CHAT_SERVICE_UUID_TEMPLATE)
            self.bt.service_uuid = service_uuid
            self.bt.char_uuid = CHAT_CHAR_UUID
            self.bt.setup_gatt_server(service_uuid, CHAT_CHAR_UUID)
            self.bt.set_server_data_callback(self._bt_on_server_data)
            # Advertise with device id in name
            device_id = self._compact_device_id(self._get_local_device_id())
            adv_name = "{}{}".format(CHAT_ADV_PREFIX, device_id or "UNKNOWN")
            self.bt.start_advertising(name=adv_name)
            if self._bt_adv_label:
                self._bt_adv_label.set_text("Your BLE name: {}".format(adv_name))
            self._add_status.set_text("Receiving pairing...")
        except Exception as exc:
            self._add_status.set_text("Receive failed")
            self.logger.info(f"[CHAT] receive start failed: {exc}")

    def _bt_on_scan_result(self, device):
        try:
            if not device or not device.name:
                return
            name = device.name
            if isinstance(name, (bytes, bytearray, memoryview)):
                try:
                    name = bytes(name).decode("utf-8")
                except Exception:
                    return
            if not isinstance(name, str):
                return
            if device.rssi is not None and device.rssi < -70:
                return
            if not name.startswith(CHAT_ADV_PREFIX):
                return
            # Keep a simple list of devices
            device.name = name
            self._bt_devices.append(device)
            self._bt_list_dirty = True
        except Exception:
            # Avoid raising into BluetoothManager callback
            return

    def _bt_refresh_list(self):
        if not self._bt_list:
            return
        self._bt_list.clean()
        seen = set()
        for dev in self._bt_devices:
            name = dev.name or "Unknown"
            key = (name, getattr(dev, "addr", None))
            if key in seen:
                continue
            seen.add(key)
            label = "{} ({} dBm)".format(name, dev.rssi)
            btn = self._bt_list.add_btn(None, label)
            try:
                btn.add_event_cb(lambda e, d=dev: self._bt_select_device(d), lv.EVENT.CLICKED, None)
            except Exception:
                pass

    def _bt_select_device(self, device):
        if not self.bt or not device:
            return
        try:
            state = self.bt.get_state()
            if state not in (0, 1):  # IDLE or SCANNING
                self._add_status.set_text("BT busy")
                return
        except Exception:
            pass
        if self.bt.is_connected():
            self._add_status.set_text("Already connected")
            return
        self._bt_selected = device
        self._bt_local_symkey1 = generate_symkey1()
        self._add_status.set_text("Connecting to peer...")

        def _on_connect(conn_handle, addr_type, addr):
            try:
                # Discover services/characteristics for chat
                self.bt.service_uuid = BluetoothManager.create_device_uuid(CHAT_SERVICE_UUID_TEMPLATE)
                self.bt.char_uuid = CHAT_CHAR_UUID
                self.bt.ble.gattc_discover_services(conn_handle)
                time.sleep_ms(800)
                if self.bt.char_handle is None:
                    self.bt.ble.gattc_discover_characteristics(conn_handle, 1, 65535)
                    time.sleep_ms(800)
                if self.bt.char_handle is None:
                    self._add_status.set_text("BT discovery failed")
                    return
                # Send our device id (6 bytes) + symkey1 (4 bytes)
                device_hex = self._compact_device_id(self._get_local_device_id()) or ""
                payload = bytes.fromhex(device_hex) + bytes.fromhex(self._bt_local_symkey1)
                self.bt.write_data(payload, wait_for_response=True)
                self._add_status.set_text("Waiting for peer...")
            except Exception as exc:
                self._add_status.set_text("BT connect failed")
                self.logger.info(f"[CHAT] connect failed: {exc}")

        try:
            # Ensure target UUIDs are set before connect
            self.bt.service_uuid = BluetoothManager.create_device_uuid(CHAT_SERVICE_UUID_TEMPLATE)
            self.bt.char_uuid = CHAT_CHAR_UUID
            self.bt.connect(device.addr, device.addr_type, callback=_on_connect)
        except Exception as exc:
            self._add_status.set_text("BT connect failed")
            self.logger.info(f"[CHAT] connect start failed: {exc}")

    def _bt_on_server_data(self, conn_handle, data):
        # Server received client payload: 6 bytes device id + 4 bytes symkey1
        try:
            if not data or len(data) < 10:
                return
            raw = bytes(data)
            peer_device_hex = raw[:6].hex()
            peer_symkey1 = raw[6:10].hex()
            self._bt_peer_device_id = self._canonical_device_id(peer_device_hex)
            self._bt_peer_symkey1 = peer_symkey1
            if not self._bt_local_symkey1:
                self._bt_local_symkey1 = generate_symkey1()
            # Respond with our symkey1 only (4 bytes)
            self.bt.server_notify(bytes.fromhex(self._bt_local_symkey1), conn_handle)
            self._bt_finalize_pairing()
        except Exception as exc:
            self.logger.info(f"[CHAT] server data failed: {exc}")

    def _bt_on_client_data(self, data):
        # Client received server notify: symkey1 only (4 bytes)
        try:
            if not data or len(data) != 4:
                return
            self._bt_peer_symkey1 = bytes(data).hex()
            # Peer device id from advertisement name
            if self._bt_selected and self._bt_selected.name.startswith(CHAT_ADV_PREFIX):
                compact = self._bt_selected.name[len(CHAT_ADV_PREFIX):]
                self._bt_peer_device_id = self._canonical_device_id(compact)
            self._bt_finalize_pairing()
        except Exception as exc:
            self.logger.info(f"[CHAT] client data failed: {exc}")

    def _bt_finalize_pairing(self):
        if not self._bt_peer_device_id or not self._bt_peer_symkey1 or not self._bt_local_symkey1:
            return
        try:
            device_id = self._get_local_device_id()
            symkey2 = derive_symkey2(self._bt_local_symkey1, self._bt_peer_symkey1, device_id, self._bt_peer_device_id)
            session_hash, _ = derive_session_hash_and_key(
                self._bt_local_symkey1, self._bt_peer_symkey1, symkey2, device_id, self._bt_peer_device_id
            )
            self._bt_session_hash = session_hash
            code = int(session_hash[:8], 16) % 10000
            self._bt_confirm_code = "{:04d}".format(code)
            if self._confirm_code_label:
                self._confirm_code_label.set_text(self._bt_confirm_code)
            if self._confirm_modal:
                self._content_root = self._confirm_content
                self._content_root_y0 = 0
                self._kb_shift = 0
                self._show_modal(self._confirm_modal)
                if hasattr(self._confirm_modal, "move_foreground"):
                    try:
                        self._confirm_modal.move_foreground()
                    except Exception:
                        pass
            if self._add_status:
                self._add_status.set_text("Confirm with peer")
        except Exception as exc:
            self._add_status.set_text("Pairing failed")
            self.logger.info(f"[CHAT] finalize failed: {exc}")

    def _on_receive_toggle(self, event):
        if self._bt_receiving:
            self._bt_stop_all()
            self._add_status.set_text("Receive off")
        else:
            self._bt_start_receive()

    def _on_confirm_pair(self, event):
        self.logger.info("[CHAT] Confirm pressed")
        if self._api_action_inflight:
            return
        self._api_action_inflight = True
        self._set_chat_api_buttons_enabled(False)
        if self._confirm_status_label:
            self._confirm_status_label.set_text("")
        if not self._bt_session_hash or not self._bt_peer_device_id:
            self._add_status.set_text("No pairing to confirm")
            self._set_chat_api_buttons_enabled(True)
            self._api_action_inflight = False
            return
        try:
            handle = (self._confirm_name_ta.get_text() or "").strip() if self._confirm_name_ta else ""
        except Exception:
            handle = ""
        if len(handle) < 2:
            if self._confirm_status_label:
                self._confirm_status_label.set_text("Enter contact name (2+ chars)")
            self._set_chat_api_buttons_enabled(True)
            self._api_action_inflight = False
            return
        if not self._require_wifi_for_action(
            status_cb=lambda text, is_err: self._confirm_status_label.set_text(text) if self._confirm_status_label else None
        ):
            self._set_chat_api_buttons_enabled(True)
            self._api_action_inflight = False
            return
        # Reuse existing flow to create session via API
        if self._confirm_modal:
            self._hide_modal(self._confirm_modal)
            self._confirm_hidden_for_spinner = True
        self.show_spinner("Creating chat...")
        self._add_status.set_text("Creating chat...")
        if not self.api_client:
            self._add_status.set_text("API not ready")
            self.logger.info("[CHAT] Confirm blocked: api_client=None")
            if self._confirm_modal and self._confirm_hidden_for_spinner:
                self._show_modal(self._confirm_modal)
                self._confirm_hidden_for_spinner = False
            self.hide_spinner()
            self._set_chat_api_buttons_enabled(True)
            self._api_action_inflight = False
            return
        try:
            # derive again to get session key
            device_id = self._get_local_device_id()
            self.logger.info(f"[CHAT] Confirm device_id={device_id} peer={self._bt_peer_device_id}")
            symkey2 = derive_symkey2(self._bt_local_symkey1, self._bt_peer_symkey1, device_id, self._bt_peer_device_id)
            session_hash, session_key = derive_session_hash_and_key(
                self._bt_local_symkey1, self._bt_peer_symkey1, symkey2, device_id, self._bt_peer_device_id
            )
            self.logger.info(f"[CHAT] Registering session {session_hash[:8]}...")
            self.api_client.register_chat_session(session_hash, self._bt_peer_device_id)
            self._pending_session = {
                "session_hash": session_hash,
                "handle": handle,
                "symkey2": symkey2,
                "session_key": session_key,
                "peer_device_id": self._bt_peer_device_id,
            }
            if self._try_store_pending_session():
                self._add_status.set_text("Added")
                self._bt_stop_all()
                if self._confirm_modal:
                    self._hide_modal(self._confirm_modal)
                    self._confirm_hidden_for_spinner = False
                self._hide_modal(self._add_modal)
                self._refresh_chat_list()
                self.logger.info("[CHAT] Confirm complete")
            else:
                self.logger.info("[CHAT] Confirm failed: session store full")
            self.hide_spinner()
        except Exception as exc:
            self._add_status.set_text("API error")
            self.logger.info(f"[CHAT] confirm failed: {exc}")
            if self._confirm_modal and self._confirm_hidden_for_spinner:
                self._show_modal(self._confirm_modal)
                self._confirm_hidden_for_spinner = False
            self.hide_spinner()
        finally:
            self._set_chat_api_buttons_enabled(True)
            self._api_action_inflight = False

    def _on_confirm_pressed(self, event):
        self.logger.info("[CHAT] Confirm button pressed")

    def _on_cancel_pressed(self, event):
        self.logger.info("[CHAT] Cancel button pressed")

    def _on_cancel_pair(self, event):
        self._bt_stop_all()
        if self._confirm_modal:
            self._hide_modal(self._confirm_modal)
        self._content_root = self.ui_elements.get("add_content")
        self._content_root_y0 = 0
        self._kb_shift = 0
        self._hide_modal(self._add_modal)

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

    def _apply_keyboard_shift(self):
        if not self._content_root or not self._active_textarea or not self._keyboard:
            return
        self._update_layout(self.screen)
        self._update_layout(self._content_root)
        self._update_layout(self._active_textarea)
        self._update_layout(self._keyboard)

        _, screen_h = self._get_screen_size()
        kb_y = self._get_abs_y(self._keyboard)
        kb_h = self._keyboard.get_height()
        if kb_h <= 0:
            kb_h = max(1, screen_h // 2)
        if kb_y <= 0 and screen_h > 0:
            kb_y = screen_h - kb_h

        ta_y = self._get_abs_y(self._active_textarea)
        ta_h = self._active_textarea.get_height()
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

    def _bind_keyboard_textarea(self):
        textarea = self._active_textarea
        if not self._keyboard or not textarea:
            return False
        if not hasattr(self._keyboard, "set_textarea"):
            self._warn_once("kb_bind", "Keyboard missing set_textarea")
            return False
        try:
            self._keyboard.set_textarea(textarea)
        except Exception as exc:
            self._warn_once("kb_bind", "Keyboard bind failed: {}".format(exc))
            return False
        return True

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

    def _get_event_target(self, event):
        try:
            if hasattr(event, "get_target_obj"):
                return event.get_target_obj()
        except Exception:
            pass
        try:
            if hasattr(event, "get_target"):
                return event.get_target()
        except Exception:
            pass
        return None

    def _set_obj_enabled(self, obj, enabled):
        if not obj:
            return
        try:
            if enabled:
                obj.remove_state(lv.STATE.DISABLED)
            else:
                obj.add_state(lv.STATE.DISABLED)
        except Exception:
            pass

    def _set_chat_api_buttons_enabled(self, enabled):
        # Buttons that can trigger API-affecting chat actions.
        for obj in (self._add_submit_btn, self._bt_confirm_btn, self._confirm_submit_btn):
            self._set_obj_enabled(obj, enabled)

    def _set_chat_composer_enabled(self, enabled):
        self._set_obj_enabled(self._chat_send_btn, enabled)
        if self._chat_input_ta:
            try:
                if enabled:
                    self._chat_input_ta.remove_state(lv.STATE.DISABLED)
                else:
                    self._chat_input_ta.add_state(lv.STATE.DISABLED)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Utils
    # ------------------------------------------------------------------

    def _create_modal(self):
        modal = lv.obj(self.screen)
        modal.set_size(lv.pct(100), lv.pct(100))
        modal.set_style_bg_color(lv.color_hex(0x000000), 0)
        try:
            modal.set_style_bg_opa(lv.OPA.COVER, 0)
        except Exception:
            modal.set_style_bg_opa(255, 0)
        modal.remove_flag(lv.obj.FLAG.SCROLLABLE)
        return modal

    def _show_modal(self, modal):
        if modal:
            modal.remove_flag(lv.obj.FLAG.HIDDEN)

    def _hide_modal(self, modal):
        if modal:
            modal.add_flag(lv.obj.FLAG.HIDDEN)

    def _spinner_pause(self, ms=60):
        """Legacy wrapper - use self.spinner_pause() instead."""
        self.spinner_pause(ms)

    def _get_local_device_id(self):
        def _normalize(device_id):
            # Keep device-id format stable for key ordering: lowercase aa:bb:..:ff
            self.logger.info(f"[CHAT] Local device ID raw: {device_id}")
            return self._canonical_device_id(self._compact_device_id(device_id)) if device_id else None

        if self.api_client:
            try:
                device_id = self.api_client.auth.get_device_id()
                if device_id:
                    normalized = _normalize(device_id)
                    if normalized:
                        return normalized
            except Exception:
                pass
        # Fall back to canonical device-id generator (lowercase chars with colons)
        try:
            device_id = default_device_id_generator()
            normalized = _normalize(device_id)
            if normalized:
                return normalized
        except Exception:
            pass
        # Last resort: app-owned WiFi manager MAC (canonicalized).
        wifi = getattr(self, "wifi", None) or (self.game_ui.wifi if self.game_ui else None)
        if wifi:
            try:
                mac = wifi.get_mac_string(uppercase=False)
                if mac:
                    return _normalize(mac)
            except Exception:
                pass
        return None

    def _compact_device_id(self, device_id):
        """Return device ID with all non-hex removed (for human entry/display)."""
        if not device_id:
            return None
        hex_chars = "".join(c for c in device_id if c.lower() in "0123456789abcdef")
        return hex_chars.lower()

    def _looks_like_device_id(self, value):
        compact = self._compact_device_id(value)
        return bool(compact and len(compact) == 12)

    def _display_chat_handle(self, meta):
        if not isinstance(meta, dict):
            return "Unknown"
        handle = (meta.get("handle") or "").strip()
        peer_id = (meta.get("peer_device_id") or "").strip()
        if not handle:
            return "Unknown"
        if self._looks_like_device_id(handle):
            return "Unknown"
        if peer_id and handle.lower() == peer_id.lower():
            return "Unknown"
        return handle

    def _canonical_device_id(self, user_value):
        """
        Normalize human-entered device ID (no separators) into canonical
        lowercase hex with colons (aa:bb:cc:dd:ee:ff). Returns None if invalid.
        """
        if not user_value:
            return None
        compact = self._compact_device_id(user_value)
        if len(compact) != 12:
            return None
        parts = [compact[i:i+2] for i in range(0, 12, 2)]
        return ":".join(parts)

    def _build_pairing_key(self, compact_device_id, symkey1_hex):
        if not compact_device_id or not symkey1_hex:
            return "--"
        if len(compact_device_id) != 12 or len(symkey1_hex) != 8:
            return "--"
        if not ubinascii:
            return "--"
        raw = ubinascii.unhexlify((compact_device_id + symkey1_hex).encode("utf-8"))
        b64 = ubinascii.b2a_base64(raw).decode("utf-8").strip()
        # URL-safe, no padding
        return b64.replace("+", "-").replace("/", "_").rstrip("=")

    def _wifi_snapshot(self):
        wifi = getattr(self, "wifi", None)
        if not wifi:
            return {"is_connected": False, "connecting": False, "active": False}
        try:
            snap = wifi.get_status_snapshot()
            if isinstance(snap, dict):
                snap.setdefault("connecting", bool(getattr(wifi, "connecting", False)))
                return snap
        except Exception:
            pass
        # Fallback if snapshot isn't available.
        try:
            return {"is_connected": bool(wifi.is_connected()), "connecting": bool(getattr(wifi, "connecting", False))}
        except Exception:
            return {"is_connected": False, "connecting": False, "active": False}

    def _kick_wifi_connect(self):
        """Ask WiFiManager to connect if not already connected/connecting."""
        wifi = getattr(self, "wifi", None)
        if not wifi and self.game_ui:
            wifi = getattr(self.game_ui, "wifi", None)
            if wifi:
                self.wifi = wifi
        if not wifi:
            return False
        try:
            return bool(
                wifi.ensure_connected(
                    wait=False,
                    timeout_s=getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10),
                    force=False,
                    enable_auto_reconnect=True,
                )
            )
        except Exception:
            return False

    def _require_wifi_for_action(self, status_cb=None):
        """
        Return True if WiFi is currently connected.

        If not connected, kick a reconnect attempt (non-blocking) and return False
        so callers can bail quickly (avoids blocking HTTP calls while offline).

        status_cb: callable(text, error_bool) to display UI feedback.
        """
        wifi = getattr(self, "wifi", None)
        if not wifi and self.game_ui:
            wifi = getattr(self.game_ui, "wifi", None)
            if wifi:
                self.wifi = wifi
        if not wifi:
            if status_cb:
                try:
                    status_cb("WiFi unavailable", True)
                except Exception:
                    pass
            return False

        snapshot = self._wifi_snapshot()
        is_connected = bool(snapshot.get("is_connected"))
        is_connecting = bool(snapshot.get("connecting"))
        is_active = bool(snapshot.get("active"))

        if is_connected:
            return True

        if is_connecting:
            if status_cb:
                try:
                    status_cb("Connecting WiFi... try again", True)
                except Exception:
                    pass
            return False

        self._kick_wifi_connect()

        if status_cb:
            try:
                if not is_active:
                    status_cb("Starting WiFi...", True)
                else:
                    status_cb("Connecting WiFi...", True)
            except Exception:
                pass
        return False

    def _ticks_ms(self):
        try:
            return time.ticks_ms()
        except Exception:
            return int(time.time() * 1000)

    def _ticks_diff(self, now_ms, last_ms):
        try:
            return time.ticks_diff(now_ms, last_ms)
        except Exception:
            return now_ms - last_ms

    def _schedule_wifi_rearm(self):
        now_ms = self._ticks_ms()
        if self._last_chat_hide_ms:
            elapsed = self._ticks_diff(now_ms, self._last_chat_hide_ms)
            remaining = self._wifi_rearm_delay_ms - elapsed
            if remaining > 0:
                self._wifi_rearm_ready_ms = now_ms + remaining
                self._wifi_rearm_pending = True
                return
        self._wifi_rearm_pending = True
        self._wifi_rearm_ready_ms = now_ms

    def _maybe_rearm_wifi(self):
        if not self._wifi_rearm_pending:
            return
        if not self.wifi:
            self._wifi_rearm_pending = False
            return
        now_ms = self._ticks_ms()
        if self._ticks_diff(now_ms, self._wifi_rearm_ready_ms) < 0:
            return
        self._wifi_rearm_pending = False
        self._kick_wifi_connect()

    def _maybe_poll_active_chat_session(self):
        # Poll only the open chat session, and only when user is not typing.
        if not self._active_session_hash or not self.api_client or not self.wifi:
            return
        if self._keyboard_is_visible() or self._api_action_inflight:
            return
        now_ms = self._ticks_ms()
        if (
            self._last_active_chat_poll_ms
            and self._ticks_diff(now_ms, self._last_active_chat_poll_ms) < self._active_chat_poll_interval_ms
        ):
            return
        self._last_active_chat_poll_ms = now_ms
        try:
            if not self._wifi_snapshot().get("is_connected"):
                self._kick_wifi_connect()
                return
            new_count = int(
                self.api_client.sync_chat_messages(self._active_session_hash, limit=20, ack=True) or 0
            )
            if new_count > 0:
                self._chat_total_count = self._count_chat_messages(self._active_session_hash)
                self._render_chat_messages(reset=True)
        except Exception:
            pass

    def _maybe_sync_remote_messages(self):
        if not self.api_client or not self.wifi:
            return
        now_ms = self._ticks_ms()
        if self._last_chat_sync_ms and self._ticks_diff(now_ms, self._last_chat_sync_ms) < self._chat_sync_interval_ms:
            return
        self._last_chat_sync_ms = now_ms

        try:
            if not self._wifi_snapshot().get("is_connected"):
                self._kick_wifi_connect()
                return
        except Exception:
            return

        try:
            sessions = self.api_client.storage.get_chat_sessions().get("sessions", {})
        except Exception:
            sessions = {}
        if not sessions:
            return

        new_count = 0
        for session_hash in sessions.keys():
            try:
                new_count += int(self.api_client.sync_chat_messages(session_hash, limit=20, ack=True) or 0)
            except Exception:
                pass
        if new_count > 0:
                self._refresh_chat_list()
                if self._active_session_hash:
                    try:
                        self._chat_total_count = self._count_chat_messages(self._active_session_hash)
                        self._render_chat_messages(reset=True)
                    except Exception:
                        pass
