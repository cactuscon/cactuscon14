"""Battle matchmaking panel - Scan and challenge opponents via BLE."""

import lvgl as lv
import time
from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.hw import pixels
from cactuscon.game.comms import (
    SESSION_CHALLENGING,
    SESSION_CHALLENGED,
    SESSION_HANDSHAKING,
    SESSION_EXCHANGING_DATA,
)

# BLE chat pairing advertisements use this prefix; hide them in battle lists.
CHAT_ADV_PREFIX = "CC14PEER"

# Persist "Open for Battle" preference across panel unloads.
_OPEN_FOR_BATTLE_PREF = False

class BattleMatchmakingPanel(BasePanel):
    """
    Battle matchmaking screen.
    
    Integrates with BattleManager to scan for opponents and initiate challenges.
    Uses flat layout with scrollable opponent list in center.
    """
    
    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        """
        Initialize matchmaking panel.
        
        Args:
            screen: TFT screen object
            game_ui: Parent GameUI manager
            battle_manager: BattleManager instance for scanning/challenging
            logger_level: Logging level
        """
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        
        # State
        self.scanning = False
        self.opponents = []
        self.opponent_buttons = []  # Track opponent buttons for cleanup
        self.button_to_opponent = {}  # Map button id to opponent index
        self.last_scan_time = 0
        self.scan_duration_ms = 2000  # Default scan window when initiated
        # Default to not advertising; user can toggle on after scan completes
        # open_for_battle tracks current runtime state; preference persists across panel unloads.
        self.open_for_battle = False
        self.open_for_battle_pref = _OPEN_FOR_BATTLE_PREF
        self._challenge_inflight = False
        self._last_challenge_ms = 0
        self._challenge_debounce_ms = 650
        self._accept_inflight = False
        self._accept_started_ms = 0
        self._accept_timeout_ms = 8000

        # Challenge dialog state
        self.pending_challenge_addr = None
        self.pending_challenge_name = None
        self.challenge_dialog = None

        # Prefer shared app singleton when provided; fallback for legacy paths.
        self.pixels = kwargs.get("pixels") or pixels.NeoPixelController()
        self._pixels_mode_snapshot = None

    def set_pixels(self, pixels_controller):
        """Inject shared NeoPixel controller from application/GameUI."""
        self.pixels = pixels_controller
    
    def create_ui(self):
        """Create matchmaking UI with opponent list."""
        # Set screen background
        self.screen.set_style_bg_color(lv.color_black(), 0)
        
        # Disable scrolling on main screen
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Title at top
        title = lv.label(self.screen)
        title.set_text("Find Opponent")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title
        
        # Scan button (top right area)
        btn_scan = lv.button(self.screen)
        btn_scan.set_size(70, 30)
        btn_scan.align(lv.ALIGN.TOP_RIGHT, -80, 8)
        btn_scan.add_event_cb(self._on_scan_clicked, lv.EVENT.CLICKED, None)
        btn_scan.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        btn_scan.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn_scan.set_style_border_width(1, 0)
        
        scan_label = lv.label(btn_scan)
        scan_label.set_text("Scan")
        scan_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        scan_label.center()
        self.ui_elements['btn_scan'] = btn_scan
        self.ui_elements['scan_label'] = scan_label
        
        # Back button (top right)
        btn_back = lv.button(self.screen)
        btn_back.set_size(60, 30)
        btn_back.align(lv.ALIGN.TOP_RIGHT, -10, 8)
        btn_back.add_event_cb(self.on_back_pressed, lv.EVENT.CLICKED, None)
        btn_back.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        btn_back.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn_back.set_style_border_width(1, 0)
        
        back_label = lv.label(btn_back)
        back_label.set_text("Back")
        back_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        back_label.center()
        self.ui_elements['btn_back'] = btn_back
        
        # Opponent list container (scrollable area in center)
        list_container = lv.obj(self.screen)
        list_container.set_size(300, 150)
        list_container.align(lv.ALIGN.CENTER, 0, 10)
        list_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        list_container.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        list_container.set_style_bg_color(lv.color_hex(0x0a0a0a), 0)
        list_container.set_style_border_color(lv.color_hex(0x333333), 0)
        list_container.set_style_border_width(1, 0)
        list_container.set_style_pad_all(5, 0)
        list_container.set_style_pad_row(5, 0)
        # Keep this container scrollable for opponent list
        self.ui_elements['list_container'] = list_container
        
        # Bottom toggle to advertise as open for battle
        toggle_container = lv.obj(self.screen)
        toggle_container.set_size(300, 24)
        toggle_container.align(lv.ALIGN.BOTTOM_MID, 0, -8)
        toggle_container.set_style_bg_opa(lv.OPA.TRANSP, 0)
        toggle_container.set_style_border_width(0, 0)
        toggle_container.set_style_pad_all(0, 0)
        toggle_container.set_flex_flow(lv.FLEX_FLOW.ROW)
        toggle_container.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        toggle_container.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements['toggle_container'] = toggle_container

        toggle_label = lv.label(toggle_container)
        toggle_label.set_text("Open for Battle")
        toggle_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        self.ui_elements['toggle_label'] = toggle_label

        toggle_open = lv.switch(toggle_container)
        # Base track (off)
        toggle_open.set_style_bg_color(lv.color_hex(0x0c0c0c), lv.PART.MAIN | lv.STATE.DEFAULT)
        toggle_open.set_style_bg_color(lv.color_hex(0x0c0c0c), lv.PART.MAIN | lv.STATE.PRESSED)
        # Indicator/track (on)
        toggle_open.set_style_bg_color(lv.color_hex(0x006600), lv.PART.INDICATOR | lv.STATE.DEFAULT)
        toggle_open.set_style_bg_color(lv.color_hex(0x00aa00), lv.PART.INDICATOR | lv.STATE.CHECKED)
        toggle_open.set_style_bg_color(lv.color_hex(0x004400), lv.PART.INDICATOR | lv.STATE.PRESSED)
        toggle_open.set_style_border_color(lv.color_hex(0x00ff00), lv.STATE.CHECKED)
        toggle_open.set_style_border_width(2, lv.STATE.CHECKED)
        # reduce size
        toggle_open.set_size(50, 24)
        # Thumb color
        if hasattr(toggle_open, "set_style_bg_color"):
            toggle_open.set_style_bg_color(lv.color_hex(0x00ff00), lv.PART.KNOB | lv.STATE.CHECKED)
            toggle_open.set_style_bg_color(lv.color_hex(0x007700), lv.PART.KNOB | lv.STATE.PRESSED)
        toggle_open.add_event_cb(self._on_toggle_open, lv.EVENT.VALUE_CHANGED, None)
        self.ui_elements['toggle_open'] = toggle_open
        
        # Challenge dialog (hidden by default) - will be shown when receiving challenge
        self._create_challenge_dialog()
    
    def _create_challenge_dialog(self):
        """Create the challenge accept/decline dialog (hidden initially)."""
        # Modal background overlay
        dialog_bg = lv.obj(self.screen)
        dialog_bg.set_size(320, 240)
        dialog_bg.set_pos(0, 0)
        dialog_bg.set_style_bg_color(lv.color_hex(0x000000), 0)
        dialog_bg.set_style_bg_opa(lv.OPA._70, 0)
        dialog_bg.set_style_border_width(0, 0)
        dialog_bg.add_flag(lv.obj.FLAG.HIDDEN)
        dialog_bg.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements['challenge_bg'] = dialog_bg
        
        # Dialog box
        dialog = lv.obj(dialog_bg)
        dialog.set_size(280, 140)
        dialog.align(lv.ALIGN.CENTER, 0, 0)
        dialog.set_style_bg_color(lv.color_hex(0x1a1a3a), 0)
        dialog.set_style_border_color(lv.color_hex(0x00ff00), 0)
        dialog.set_style_border_width(2, 0)
        dialog.set_style_radius(10, 0)
        dialog.set_style_pad_all(10, 0)
        dialog.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements['challenge_dialog'] = dialog
        self.challenge_dialog = dialog
        
        # Challenge title
        challenge_title = lv.label(dialog)
        challenge_title.set_text("Challenge!")
        challenge_title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        challenge_title.align(lv.ALIGN.TOP_MID, 0, 5)
        self.ui_elements['challenge_title'] = challenge_title
        
        # Challenger name
        challenger_label = lv.label(dialog)
        challenger_label.set_text("Someone wants to battle!")
        challenger_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        challenger_label.align(lv.ALIGN.CENTER, 0, -15)
        self.ui_elements['challenger_name'] = challenger_label
        
        # Accept button
        btn_accept = lv.button(dialog)
        btn_accept.set_size(100, 35)
        btn_accept.align(lv.ALIGN.BOTTOM_LEFT, 20, -10)
        btn_accept.set_style_bg_color(lv.color_hex(0x00aa00), 0)
        btn_accept.set_style_bg_color(lv.color_hex(0x00dd00), lv.STATE.PRESSED)
        btn_accept.add_event_cb(self._on_accept_challenge, lv.EVENT.CLICKED, None)
        
        accept_label = lv.label(btn_accept)
        accept_label.set_text("Accept")
        accept_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        accept_label.center()
        self.ui_elements['btn_accept'] = btn_accept
        
        # Decline button
        btn_decline = lv.button(dialog)
        btn_decline.set_size(100, 35)
        btn_decline.align(lv.ALIGN.BOTTOM_RIGHT, -20, -10)
        btn_decline.set_style_bg_color(lv.color_hex(0xaa0000), 0)
        btn_decline.set_style_bg_color(lv.color_hex(0xdd0000), lv.STATE.PRESSED)
        btn_decline.add_event_cb(self._on_decline_challenge, lv.EVENT.CLICKED, None)
        
        decline_label = lv.label(btn_decline)
        decline_label.set_text("Decline")
        decline_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        decline_label.center()
        self.ui_elements['btn_decline'] = btn_decline
    
    def show_challenge_dialog(self, opponent_name, opponent_addr):
        """
        Show the challenge accept/decline dialog.
        
        Called by BattleManager when a challenge is received.
        
        Args:
            opponent_name: Name of the challenger
            opponent_addr: BLE address of the challenger
        """
        self.pending_challenge_addr = opponent_addr
        self.pending_challenge_name = opponent_name
        self._accept_inflight = False
        self._accept_started_ms = 0
        
        # Update challenger name in dialog
        if 'challenger_name' in self.ui_elements:
            self.ui_elements['challenger_name'].set_text(f"{opponent_name} wants to battle!")
        
        # Show dialog
        if 'challenge_bg' in self.ui_elements:
            self.ui_elements['challenge_bg'].remove_flag(lv.obj.FLAG.HIDDEN)
        
        self.logger.info(f"Challenge dialog shown for {opponent_name}")
    
    def hide_challenge_dialog(self):
        """Hide the challenge dialog."""
        if 'challenge_bg' in self.ui_elements:
            self.ui_elements['challenge_bg'].add_flag(lv.obj.FLAG.HIDDEN)
        
        self.pending_challenge_addr = None
        self.pending_challenge_name = None
    
    def _on_accept_challenge(self, event):
        """Handle accept button click."""
        self.logger.info(f"Accepting challenge from {self.pending_challenge_name}")
        
        if self.battle_manager and self.pending_challenge_addr:
            self.show_spinner("Accepting challenge...")
            self._update_status("Accepting challenge...")
            success = self.battle_manager.accept_challenge(self.pending_challenge_addr)
            if not success:
                self.logger.warning("Accept challenge failed (stale/expired request)")
                self.hide_spinner()
                self._update_status("Challenge expired")
                self._restore_open_for_battle_after_challenge("accept_failed")
                self.hide_challenge_dialog()
                return
            self._accept_inflight = True
            self._accept_started_ms = time.ticks_ms()
        
        self.hide_challenge_dialog()
    
    def _on_decline_challenge(self, event):
        """Handle decline button click."""
        self.logger.info(f"Declining challenge from {self.pending_challenge_name}")
        
        if self.battle_manager and self.pending_challenge_addr:
            self.battle_manager.decline_challenge(self.pending_challenge_addr)
        
        self.hide_challenge_dialog()
        self._update_status("Challenge declined")
        self._restore_open_for_battle_after_challenge("decline")
    
    def on_show(self):
        """Enter matchmaking mode when panel is shown."""
        self.logger.info("Battle matchmaking panel shown")
        # Always reset local challenge latch when reopening this panel.
        # A previous session/navigation can otherwise leave taps blocked.
        self._challenge_inflight = False
        self._last_challenge_ms = 0
        self._accept_inflight = False
        self._accept_started_ms = 0
        self.hide_challenge_dialog()
        for btn in self.opponent_buttons:
            try:
                if hasattr(btn, "clear_state"):
                    btn.clear_state(lv.STATE.DISABLED)
                elif hasattr(btn, "remove_state"):
                    btn.remove_state(lv.STATE.DISABLED)
            except Exception:
                pass
        # If user navigated back here from an interrupted pre-battle flow,
        # clear stale protocol session state before any new scan/challenge.
        if self.battle_manager and hasattr(self.battle_manager, "cleanup_stale_session"):
            try:
                self.battle_manager.cleanup_stale_session("battle_matchmaking.on_show")
            except Exception as e:
                self.logger.debug(f"cleanup_stale_session failed: {e}")
        # Restore persisted preference when reopening this panel.
        self._set_open_for_battle(self.open_for_battle_pref, persist=False)
        
        # Start initial scan
        self._start_scan()

    def on_hide(self):
        """Stop scanning when panel is hidden."""
        if self.scanning and self.battle_manager:
            self.battle_manager.stop_opponent_scan()
            self.scanning = False
            self.hide_spinner()
        
        # Exit matchmaking mode (return to IDLE) only if not already in battle
        if not self.battle_manager or not self.battle_manager.is_in_battle():
            self._set_open_for_battle(False, from_toggle=True, persist=False)
        elif self._pixels_mode_snapshot is not None:
            # If battle started while blinking, restore previous mode on exit.
            try:
                self.pixels._restore_mode(self._pixels_mode_snapshot)
            except Exception:
                self.pixels.stop_blink()
            self._pixels_mode_snapshot = None
        
        # Ensure any pending overlays are cleared when leaving
        self.hide_spinner()
    
    def update(self):
        """Periodically check for scan completion while visible."""
        if not self.visible:
            return

        # If accepting an incoming challenge stalls (peer disconnected/timed out),
        # fail cleanly so the UI doesn't spin forever.
        if self._accept_inflight and self._accept_started_ms:
            now = time.ticks_ms()
            elapsed = time.ticks_diff(now, self._accept_started_ms)
            if self.battle_manager and self.battle_manager.is_in_battle():
                # Battle panel transition will take over UI flow.
                self._accept_inflight = False
                self._accept_started_ms = 0
            elif (
                elapsed > 1500
                and not self._has_active_prebattle_session()
            ):
                self.logger.warning("Accepted challenge lost before handshake")
                self._accept_inflight = False
                self._accept_started_ms = 0
                self.hide_spinner()
                self._update_status("Challenge no longer available")
                self._restore_open_for_battle_after_challenge("accept_lost")
            elif elapsed > self._accept_timeout_ms:
                self.logger.warning("Accept challenge timed out")
                self._accept_inflight = False
                self._accept_started_ms = 0
                self.hide_spinner()
                self._update_status("Accept timed out")
                if self.battle_manager and hasattr(self.battle_manager, "cleanup_stale_session"):
                    try:
                        self.battle_manager.cleanup_stale_session("accept_timeout")
                    except Exception:
                        pass
                self._restore_open_for_battle_after_challenge("accept_timeout")

        # Defensive recovery: if challenge latch is set but comms no longer has a
        # pre-battle session, clear the latch so matchmaking taps don't get stuck.
        if self._challenge_inflight and self._last_challenge_ms:
            now = time.ticks_ms()
            if (
                time.ticks_diff(now, self._last_challenge_ms) > 2000
                and not self._has_active_prebattle_session()
            ):
                self.logger.warning("Clearing stale challenge latch (no active session)")
                self._clear_challenge_inflight()
        
        now = time.ticks_ms()
        if (
            self.scanning
            and self.battle_manager
            and time.ticks_diff(now, self.last_scan_time) >= self.scan_duration_ms
        ):
            # Stop scan and refresh results, then return to server mode
            self.battle_manager.stop_opponent_scan()
            self._refresh_opponent_list()

    def _start_scan(self):
        """Start scanning for opponents."""
        if not self.battle_manager:
            self.logger.error("No battle manager available")
            self._update_status("Error: No battle manager")
            return
        
        self.logger.info("Starting opponent scan...")
        self._update_status("Scanning...")
        self.show_spinner("Scanning for opponents...")
        
        # Update scan button text
        if 'scan_label' in self.ui_elements:
            self.ui_elements['scan_label'].set_text("...")
        
        self.scanning = True
        self.battle_manager.start_opponent_scan(duration_ms=self.scan_duration_ms)
        self.last_scan_time = time.ticks_ms()

    def _refresh_opponent_list(self):
        """Refresh the list of available opponents."""
        if not self.battle_manager:
            return

        # Scan completion is a new interaction cycle; clear stale challenge latch.
        self._challenge_inflight = False

        # Get opponents from battle manager
        self.opponents = self.battle_manager.get_opponents(min_rssi=-70, limit=10)
        self._prune_chat_devices()
        
        # Debug: log each opponent found
        for i, opp in enumerate(self.opponents):
            self.logger.debug(f"  Opponent[{i}]: {opp.name} addr={opp.addr_str()} RSSI={opp.rssi}")
        
        self.logger.info(f"Found {len(self.opponents)} unique opponents")
        
        # Update UI list
        self._populate_opponent_list()
        
        # Update status
        if len(self.opponents) == 0:
            self._update_status("No opponents found")
        else:
            self._update_status(f"Found {len(self.opponents)} opponent(s)")
        
        # Reset scan button text
        if 'scan_label' in self.ui_elements:
            self.ui_elements['scan_label'].set_text("Scan")
        
        self.scanning = False
        self.hide_spinner()
        # Auto-restore advertising/server if toggle is on
        if self.open_for_battle:
            self._set_open_for_battle(True, from_toggle=True)

    def _has_active_prebattle_session(self):
        """
        Return True while comms reports a live pre-battle challenge session.
        """
        if not self.battle_manager or not getattr(self.battle_manager, "game_bt", None):
            return False
        session = self.battle_manager.game_bt.session
        if not session:
            return False
        return session.state in (
            SESSION_CHALLENGING,
            SESSION_CHALLENGED,
            SESSION_HANDSHAKING,
            SESSION_EXCHANGING_DATA,
        )
    
    def _populate_opponent_list(self):
        """Populate the opponent list with discovered badges."""
        if 'list_container' not in self.ui_elements:
            return
        
        list_container = self.ui_elements['list_container']
        
        # Clear existing opponent buttons
        for btn in self.opponent_buttons:
            try:
                btn.delete()
            except Exception:
                pass
        self.opponent_buttons = []
        self.button_to_opponent = {}  # Clear mapping
        
        # Add each opponent as a button
        for i, opponent in enumerate(self.opponents):
            btn = lv.button(list_container)
            btn.set_size(280, 35)
            btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
            btn.set_style_bg_color(lv.color_hex(0x2a2a2a), lv.STATE.PRESSED)
            btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
            btn.set_style_border_width(1, 0)
            
            name_label = lv.label(btn)
            name_label.set_width(210)
            name_label.set_long_mode(0)  # LV_LABEL_LONG_SCROLL_CIRCULAR
            display_name = opponent.name or "Unknown"
            if isinstance(display_name, (bytes, bytearray, memoryview)):
                try:
                    display_name = bytes(display_name).decode("utf-8")
                except Exception:
                    display_name = "Unknown"
            if isinstance(display_name, str) and display_name.startswith(CHAT_ADV_PREFIX):
                try:
                    addr_tail = opponent.addr_str()[-5:]
                    display_name = f"Badge {addr_tail}"
                except Exception:
                    display_name = "Badge"
            if isinstance(display_name, str) and display_name.startswith(CHAT_ADV_PREFIX):
                # Skip chat-only peers entirely in battle list.
                continue
            name_label.set_text(display_name)
            name_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
            name_label.align(lv.ALIGN.LEFT_MID, 12, 0)

            rssi_label = lv.label(btn)
            rssi_label.set_text(f"RSSI:{opponent.rssi}")
            rssi_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
            rssi_label.align(lv.ALIGN.RIGHT_MID, -12, 0)
            
            # Map button to opponent index using object id
            self.button_to_opponent[id(btn)] = i
            self.logger.debug(f"Mapped button id={id(btn)} to opponent[{i}]={opponent.name}")
            btn.add_event_cb(self._on_opponent_clicked, lv.EVENT.CLICKED, None)
            
            self.opponent_buttons.append(btn)

    def _prune_chat_devices(self):
        """
        Remove chat-only devices from BluetoothManager cache to avoid evicting battle peers.
        """
        if not self.battle_manager or not getattr(self.battle_manager, "game_bt", None):
            return
        bt = getattr(self.battle_manager.game_bt, "bt", None)
        if not bt or not hasattr(bt, "devices"):
            return
        try:
            to_remove = []
            for addr, dev in bt.devices.items():
                name = getattr(dev, "name", "")
                if isinstance(name, (bytes, bytearray, memoryview)):
                    try:
                        name = bytes(name).decode("utf-8")
                    except Exception:
                        name = ""
                if isinstance(name, str) and name.startswith(CHAT_ADV_PREFIX):
                    to_remove.append(addr)
            for addr in to_remove:
                bt.devices.pop(addr, None)
        except Exception:
            pass
    
    def _update_status(self, message):
        """Update status label text."""
        if 'status' in self.ui_elements:
            self.ui_elements['status'].set_text(message)

    def _set_open_for_battle(self, enabled, from_toggle=False, persist=True):
        """Enable/disable advertising as an open battle server."""
        self.open_for_battle = bool(enabled)
        if persist:
            self.open_for_battle_pref = bool(enabled)
            global _OPEN_FOR_BATTLE_PREF
            _OPEN_FOR_BATTLE_PREF = self.open_for_battle_pref
        # Sync toggle UI if this was programmatic
        if 'toggle_open' in self.ui_elements and not from_toggle:
            sw = self.ui_elements['toggle_open']
            if enabled:
                sw.add_state(lv.STATE.CHECKED)
            else:
                if hasattr(sw, "clear_state"):
                    sw.clear_state(lv.STATE.CHECKED)
                elif hasattr(sw, "remove_state"):
                    sw.remove_state(lv.STATE.CHECKED)
        if not self.battle_manager:
            return
        if enabled:
            if self._pixels_mode_snapshot is None:
                try:
                    self._pixels_mode_snapshot = self.pixels._snapshot_mode()
                except Exception:
                    self._pixels_mode_snapshot = None
            self.pixels.start_blink((255, 0, 0))
            self.battle_manager.enter_matchmaking()
        else:
            self.battle_manager.exit_matchmaking()
            if self._pixels_mode_snapshot is not None:
                try:
                    self.pixels._restore_mode(self._pixels_mode_snapshot)
                except Exception:
                    self.pixels.stop_blink()
                self._pixels_mode_snapshot = None
            else:
                self.pixels.stop_blink()

    def _restore_open_for_battle_after_challenge(self, action):
        """
        Re-enable advertising after accepting/declining a challenge if the user
        intended to stay open for battle.
        """
        if not self.battle_manager or not self.open_for_battle_pref:
            return
        # Avoid toggling during active battle; enter_matchmaking would be rejected.
        if self.battle_manager.is_in_battle():
            self.logger.info(
                f"Skipping open-for-battle restore after {action}: already in battle"
            )
            return
        self.logger.info(f"Restoring open-for-battle after {action}")
        self._set_open_for_battle(True, from_toggle=True)

    def _on_toggle_open(self, event):
        """Handle Open for Battle toggle changes."""
        target = event.get_target_obj()
        enabled = target.has_state(lv.STATE.CHECKED)
        self.logger.info(f"Open for Battle toggled: {enabled}")
        self._set_open_for_battle(enabled, from_toggle=True, persist=True)
    
    # Event handlers
    
    def _on_scan_clicked(self, event):
        """Handle scan button click."""
        self.logger.info("Scan button clicked")
        if not self.scanning:
            self._start_scan()
    
    def _on_opponent_clicked(self, event):
        """Handle opponent selection - challenge them."""
        target = event.get_target_obj()
        
        # The target might be the label inside the button - get the actual button
        # Check if target is in our mapping, otherwise try parent
        opponent_idx = self.button_to_opponent.get(id(target))
        if opponent_idx is None:
            # Try parent (target was probably the label inside the button)
            parent = target.get_parent()
            if parent:
                opponent_idx = self.button_to_opponent.get(id(parent))
                self.logger.debug(f"Click on child, trying parent id={id(parent)}")
        
        self.logger.info(f"Opponent button clicked, target_id={id(target)}, idx={opponent_idx}, opponents={len(self.opponents)}")
        
        if opponent_idx is None or opponent_idx < 0 or opponent_idx >= len(self.opponents):
            self.logger.error(f"Invalid opponent index: {opponent_idx}")
            self.hide_spinner()
            return
        
        opponent = self.opponents[opponent_idx]
        now = time.ticks_ms()
        if self._challenge_inflight:
            if self._has_active_prebattle_session():
                self.logger.info("Challenge already in progress; ignoring tap")
                return
            self.logger.warning("Stale challenge latch detected; auto-clearing")
            self._clear_challenge_inflight()
        if self._last_challenge_ms and time.ticks_diff(now, self._last_challenge_ms) < self._challenge_debounce_ms:
            self.logger.debug("Challenge tap debounced")
            return
        self._last_challenge_ms = now

        self.logger.info(f"Challenging opponent: {opponent.name} addr={opponent.addr_str()}")
        self._challenge_inflight = True
        # Disable all opponent buttons to avoid duplicate taps
        for btn in self.opponent_buttons:
            try:
                btn.add_state(lv.STATE.DISABLED)
            except Exception:
                pass
        
        # Initiate challenge via battle manager
        if self.battle_manager:
            self._update_status(f"Challenging {opponent.name}...")
            self.show_spinner(f"Challenging {opponent.name}...")
            success = self.battle_manager.challenge_opponent(opponent)
            
            if success:
                self.logger.info("Challenge initiated successfully")
            else:
                self._update_status("Failed to challenge")
                self.logger.error("Failed to initiate challenge")
                self.hide_spinner()
                self._clear_challenge_inflight()

    def cancel_pending_action(self):
        """Called by comms on error/timeout to reset UI state."""
        self._accept_inflight = False
        self._accept_started_ms = 0
        self.hide_challenge_dialog()
        self.hide_spinner()
        self._clear_challenge_inflight()

    def _clear_challenge_inflight(self):
        self._challenge_inflight = False
        for btn in self.opponent_buttons:
            try:
                if hasattr(btn, "clear_state"):
                    btn.clear_state(lv.STATE.DISABLED)
                elif hasattr(btn, "remove_state"):
                    btn.remove_state(lv.STATE.DISABLED)
            except Exception:
                pass
        self._update_status("Tap Scan to find opponents")
        # Restore toggle to on if user had it enabled (keeps advertising)
        if self.open_for_battle:
            self._set_open_for_battle(True, from_toggle=True)
        self.scanning = False
