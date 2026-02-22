"""Settings Panel - Badge configuration and system settings."""

import lvgl as lv
from .base_panel import BasePanel
from cactuscon.prefs import prefs, HANDLE_KEY, LEGACY_HANDLE_KEY
from cactuscon.handle_utils import HANDLE_MAX_LEN, normalize_handle
from cactuscon.hw.power_meter import fuel_gauge


class SettingsPanel(BasePanel):
    """Settings and configuration panel."""
    
    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        """Initialize settings panel with WiFi manager reference."""
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self._wifi_mgr = None
        self._brightness = 100
        self._handle_edit_btn = None
        self._status_timer = None
    
    def create_ui(self):
        """Create settings panel UI."""
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Title
        title = lv.label(self.screen)
        title.set_text("Settings")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 5)
        self.ui_elements['title'] = title

        status_label = lv.label(self.screen)
        status_label.set_text("")
        status_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        try:
            status_label.set_width(lv.pct(90))
            status_label.set_long_mode(lv.label.LONG.DOT)
        except Exception:
            pass
        status_label.align(lv.ALIGN.TOP_MID, 0, 20)
        self.ui_elements['status_label'] = status_label
        
        # Compact row layout
        ROW_Y = 40
        ROW_H = 30
        
        # === Handle ===
        y = ROW_Y
        self._create_label_row("Handle:", y)
        handle_value = lv.label(self.screen)
        handle_value.set_text("---")
        handle_value.set_style_text_color(lv.color_hex(0x00ff00), 0)
        handle_value.align(lv.ALIGN.TOP_RIGHT, -60, y)
        self.ui_elements['handle_value'] = handle_value

        handle_edit_btn = lv.button(self.screen)
        handle_edit_btn.set_size(48, 22)
        handle_edit_btn.align(lv.ALIGN.TOP_RIGHT, -8, y - 1)
        handle_edit_btn.add_event_cb(self._on_handle_edit_clicked, lv.EVENT.CLICKED, None)
        handle_edit_btn.set_style_bg_color(lv.color_hex(0x2a2a2a), 0)
        handle_edit_btn.set_style_bg_color(lv.color_hex(0x3a3a3a), lv.STATE.PRESSED)
        handle_edit_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        handle_edit_btn.set_style_border_width(1, 0)
        handle_edit_btn.set_style_radius(4, 0)
        handle_edit_btn.set_style_pad_all(2, 0)

        handle_edit_label = lv.label(handle_edit_btn)
        handle_edit_label.set_text("Edit")
        handle_edit_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        handle_edit_label.center()
        self.ui_elements['handle_edit_btn'] = handle_edit_btn
        self._handle_edit_btn = handle_edit_btn
        
        # === WiFi + Network (same row: label, ssid, button) ===
        y += ROW_H
        self._create_label_row("WiFi:", y)
        
        # SSID value (between label and button)
        ssid_value = lv.label(self.screen)
        ssid_value.set_text("---")
        ssid_value.set_style_text_color(lv.color_hex(0x888888), 0)
        ssid_value.align(lv.ALIGN.TOP_LEFT, 55, y)
        self.ui_elements['ssid_value'] = ssid_value
        
        # WiFi toggle button (right side)
        wifi_btn = lv.button(self.screen)
        wifi_btn.set_size(78, 24)
        wifi_btn.align(lv.ALIGN.TOP_RIGHT, -8, y - 2)
        wifi_btn.add_event_cb(self._on_wifi_toggle, lv.EVENT.CLICKED, None)
        wifi_btn.set_style_bg_color(lv.color_hex(0x2a2a2a), 0)
        wifi_btn.set_style_bg_color(lv.color_hex(0x3a3a3a), lv.STATE.PRESSED)
        wifi_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        wifi_btn.set_style_border_width(1, 0)
        wifi_btn.set_style_radius(4, 0)
        wifi_btn.set_style_pad_all(2, 0)
        
        wifi_label = lv.label(wifi_btn)
        wifi_label.set_text("---")
        wifi_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        wifi_label.center()
        self.ui_elements['wifi_btn'] = wifi_btn
        self.ui_elements['wifi_label'] = wifi_label

        # Explicit forget button (does not toggle radio by itself)
        wifi_forget_btn = lv.button(self.screen)
        wifi_forget_btn.set_size(60, 24)
        wifi_forget_btn.align(lv.ALIGN.TOP_RIGHT, -88, y - 2)
        wifi_forget_btn.add_event_cb(self._on_wifi_forget, lv.EVENT.CLICKED, None)
        wifi_forget_btn.set_style_bg_color(lv.color_hex(0x2a2a2a), 0)
        wifi_forget_btn.set_style_bg_color(lv.color_hex(0x3a3a3a), lv.STATE.PRESSED)
        wifi_forget_btn.set_style_border_color(lv.color_hex(0xFF6600), 0)
        wifi_forget_btn.set_style_border_width(1, 0)
        wifi_forget_btn.set_style_radius(4, 0)
        wifi_forget_btn.set_style_pad_all(2, 0)

        wifi_forget_label = lv.label(wifi_forget_btn)
        wifi_forget_label.set_text("Forget")
        wifi_forget_label.set_style_text_color(lv.color_hex(0xFF6600), 0)
        wifi_forget_label.center()
        self.ui_elements['wifi_forget_btn'] = wifi_forget_btn
        self.ui_elements['wifi_forget_label'] = wifi_forget_label
        
        # === Brightness ===
        y += ROW_H
        self._create_label_row("Bright:", y)
        
        # Slider first (positioned with right padding)
        brightness_slider = lv.slider(self.screen)
        brightness_slider.set_size(110, 18)
        brightness_slider.align(lv.ALIGN.TOP_RIGHT, -15, y)
        
        # Percentage label between "Bright:" and slider
        brightness_value = lv.label(self.screen)
        brightness_value.set_text("100%")
        brightness_value.set_style_text_color(lv.color_hex(0xcccccc), 0)
        brightness_value.align(lv.ALIGN.TOP_LEFT, 70, y)
        self.ui_elements['brightness_value'] = brightness_value
        brightness_slider.set_range(10, 100)
        brightness_slider.set_value(100, False)  # LVGL 9.x: bool for anim
        brightness_slider.add_event_cb(self._on_brightness_changed, lv.EVENT.VALUE_CHANGED, None)
        brightness_slider.set_style_bg_color(lv.color_hex(0x333333), 0)
        brightness_slider.set_style_bg_color(lv.color_hex(0x00ff00), lv.PART.INDICATOR)
        brightness_slider.set_style_bg_color(lv.color_hex(0x00ff00), lv.PART.KNOB)
        self.ui_elements['brightness_slider'] = brightness_slider
        
        # === Device ID ===
        y += ROW_H
        self._create_label_row("Device:", y)
        device_id_value = lv.label(self.screen)
        device_id_value.set_text("---")
        device_id_value.set_style_text_color(lv.color_hex(0x666666), 0)
        device_id_value.align(lv.ALIGN.TOP_RIGHT, -10, y)
        self.ui_elements['device_id_value'] = device_id_value

        # === Battery ===
        y += ROW_H
        self._create_label_row("Battery:", y)
        battery_value = lv.label(self.screen)
        battery_value.set_text("---")
        battery_value.set_style_text_color(lv.color_hex(0x666666), 0)
        battery_value.align(lv.ALIGN.TOP_RIGHT, -10, y)
        self.ui_elements['battery_value'] = battery_value
        
        # === Back Button ===
        back_button = lv.button(self.screen)
        back_button.set_size(180, 36)
        back_button.align(lv.ALIGN.BOTTOM_MID, 0, -8)
        back_button.add_event_cb(self.on_back_pressed, lv.EVENT.CLICKED, None)
        back_button.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        back_button.set_style_bg_color(lv.color_hex(0x2a2a2a), lv.STATE.PRESSED)
        back_button.set_style_border_color(lv.color_hex(0x00ff00), 0)
        back_button.set_style_border_width(2, 0)
        back_button.set_style_radius(8, 0)
        
        back_label = lv.label(back_button)
        back_label.set_text("Back")
        back_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        back_label.center()
        self.ui_elements['back_button'] = back_button
    
    def _create_label_row(self, text, y_pos):
        """Create a label on the left side of a row."""
        label = lv.label(self.screen)
        label.set_text(text)
        label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        label.align(lv.ALIGN.TOP_LEFT, 15, y_pos)
        return label
    
    def on_show(self):
        """Called when settings panel is displayed."""
        self.logger.info("Settings panel displayed")
        self._load_settings()
        self._update_display()
        if self.game_ui and hasattr(self.game_ui, "wifi_status_message"):
            message = getattr(self.game_ui, "wifi_status_message", None)
            if message:
                self.show_status_message(message, duration_ms=2500)
                self.game_ui.wifi_status_message = None
        # Update only battery and WiFi status frequently
        self._update_timer = lv.timer_create(
            lambda timer: self._fast_update(), 5000, None
        )
    
    def on_hide(self):
        """Called when settings panel is hidden."""
        self.logger.debug("Settings panel hidden")
        self._save_settings()
        # Clean up timer
        if hasattr(self, '_update_timer') and self._update_timer:
            self._update_timer.delete()
            self._update_timer = None
        self._stop_status_timer()

    def _stop_status_timer(self):
        if self._status_timer:
            try:
                self._status_timer.delete()
            except Exception:
                pass
            self._status_timer = None

    def show_status_message(self, text, duration_ms=2500):
        label = self.ui_elements.get("status_label")
        if not label:
            return
        try:
            label.set_text(text or "")
            label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        except Exception:
            return
        self._stop_status_timer()
        if duration_ms:
            self._status_timer = lv.timer_create(lambda t: self._clear_status_message(), duration_ms, None)

    def _clear_status_message(self):
        label = self.ui_elements.get("status_label")
        if label:
            try:
                label.set_text("")
            except Exception:
                pass
        self._stop_status_timer()
    
    def _load_settings(self):
        """Load settings from NVS and current state."""
        try:
            # Load brightness from NVS
            prefs.begin("cactuscon")
            self._brightness = prefs.get_int32("brightness", 100)
            prefs.end()
            
            # Clamp to valid range
            self._brightness = max(10, min(100, self._brightness))
        except Exception as e:
            self.logger.debug(f"Could not load settings: {e}")
            self._brightness = 100
    
    def _save_settings(self):
        """Save settings to NVS."""
        try:
            prefs.begin("cactuscon", write=True, context="settings._save_settings")
            prefs.set_int32("brightness", self._brightness)
            prefs.end()
            self.logger.debug(f"Settings saved: brightness={self._brightness}")
        except Exception as e:
            self.logger.error(f"Failed to save settings: {e}")

    def _fast_update(self):
        """Quick update for frequently changing values."""
        try:
            self._update_battery_level()
            self._update_wifi_status()
        except Exception as e:
            self.logger.debug(f"Fast update error: {e}")
    
    def _update_display(self):
        """Update all settings display values."""
        # Get WiFi manager
        self._get_wifi_manager()
        
        # Update handle
        try:
            prefs.begin("cactuscon")
            handle = normalize_handle(
                prefs.get_string(HANDLE_KEY, prefs.get_string(LEGACY_HANDLE_KEY, ""))
            )
            prefs.end()
            if len(handle) > HANDLE_MAX_LEN:
                self.logger.warning(
                    "Stored handle exceeds max length (%d); trimming for display",
                    HANDLE_MAX_LEN,
                )
                handle = handle[:HANDLE_MAX_LEN]
            if not handle:
                handle = "Not Set"
            self.ui_elements['handle_value'].set_text(handle)
        except Exception as e:
            self.logger.debug(f"Could not load handle: {e}")
            self.ui_elements['handle_value'].set_text("N/A")
        
        # Update WiFi status
        self._update_wifi_status()
        
        # Update brightness slider and label
        if 'brightness_slider' in self.ui_elements:
            self.ui_elements['brightness_slider'].set_value(self._brightness, False)  # LVGL 9.x: bool for anim
        if 'brightness_value' in self.ui_elements:
            self.ui_elements['brightness_value'].set_text(f"{self._brightness}%")
        
        # Update Device ID (MAC Address)
        self._update_device_id()

        # Update Battery Level
        self._update_battery_level()
        
        # Update SSID
        self._update_ssid()
    
    def _get_wifi_manager(self):
        """Get WiFi manager from application context."""
        # Prefer the app-owned WiFi manager shared via GameUI
        if self._wifi_mgr:
            return self._wifi_mgr
        if self.game_ui and hasattr(self.game_ui, "wifi") and self.game_ui.wifi:
            self._wifi_mgr = self.game_ui.wifi
            return self._wifi_mgr
        self.logger.debug("WiFi manager not available from GameUI")
        return None
    
    def _update_wifi_status(self):
        """Update WiFi button with current status."""
        wifi = self._get_wifi_manager()
        saved_ssid = None
        try:
            if wifi:
                saved_ssid, _ = wifi.load_saved_credentials()
        except Exception:
            saved_ssid = None
        
        if wifi and wifi.is_connected():
            btn_text = "WiFi Off"
            color = lv.color_hex(0x00ff00)
        else:
            btn_text = "Connect"
            color = lv.color_hex(0xff6600)
        
        if 'wifi_label' in self.ui_elements:
            self.ui_elements['wifi_label'].set_text(btn_text)
            self.ui_elements['wifi_label'].set_style_text_color(color, 0)
        forget_label = self.ui_elements.get('wifi_forget_label')
        if forget_label:
            if saved_ssid:
                forget_label.set_style_text_color(lv.color_hex(0xFF6600), 0)
            else:
                forget_label.set_style_text_color(lv.color_hex(0x666666), 0)
    
    def _update_device_id(self):
        """Update Device ID with MAC address."""
        try:
            wifi = self._get_wifi_manager()
            if wifi:
                mac_str = wifi.get_mac_string(uppercase=True)
                self.ui_elements['device_id_value'].set_text(mac_str or "N/A")
            else:
                self.ui_elements['device_id_value'].set_text("N/A")
        except Exception as e:
            self.logger.debug(f"Could not get MAC: {e}")
            self.ui_elements['device_id_value'].set_text("N/A")

    def _update_battery_level(self):
        self.ui_elements["battery_value"].set_text(f"{fuel_gauge.getSoc()}%")

    def _on_handle_edit_clicked(self, event):
        """Navigate to handle editor panel."""
        if self.game_ui:
            self.game_ui.show_panel("handle_edit")
    
    def _update_ssid(self):
        """Update current network SSID."""
        try:
            wifi = self._get_wifi_manager()
            label = self.ui_elements.get('ssid_value')
            if wifi and wifi.is_connected():
                ssid = wifi.get_ssid()
                if label:
                    label.set_text(ssid if ssid else "Unknown")
                    label.set_style_text_color(lv.color_hex(0x00ff00), 0)
            else:
                saved_ssid, _ = ((None, None) if not wifi else wifi.load_saved_credentials())
                if label:
                    if saved_ssid:
                        label.set_text("Power Saving")
                        label.set_style_text_color(lv.color_hex(0xFFCC00), 0)
                    else:
                        label.set_text("Not Connected")
                        label.set_style_text_color(lv.color_hex(0x888888), 0)
        except Exception as e:
            self.logger.debug(f"Could not get SSID: {e}")
            label = self.ui_elements.get('ssid_value')
            if label:
                label.set_text("N/A")
                label.set_style_text_color(lv.color_hex(0x666666), 0)
    
    def _on_wifi_toggle(self, event):
        """Handle WiFi connect/disconnect button."""
        wifi = self._get_wifi_manager()
        if not wifi:
            self.logger.error("WiFi manager not available")
            return
        
        if wifi.is_connected():
            self.logger.info("Disconnecting WiFi...")
            wifi.disconnect()
            self.show_status_message("WiFi off (saved networks kept)", duration_ms=2200)
        else:
            self.logger.info("Opening WiFi connect panel...")
            if self.game_ui:
                self.game_ui.show_panel("wifi_connect")
                return
        
        # Update display after action
        self._update_wifi_status()
        self._update_ssid()
        try:
            self.logger.info(f"[WIFI] settings toggle: {wifi.get_status_snapshot()}")
        except Exception:
            pass

    def _on_wifi_forget(self, event):
        """Forget saved and last-successful WiFi credentials."""
        wifi = self._get_wifi_manager()
        if not wifi:
            self.show_status_message("WiFi manager unavailable", duration_ms=2200)
            return
        try:
            wifi.forget_saved_credentials()
        except Exception as e:
            self.logger.error(f"Failed to clear WiFi credentials: {e}")
            self.show_status_message("Failed to forget WiFi", duration_ms=2200)
            return
        if wifi:
            try:
                if wifi.is_connected() or wifi.get_status_snapshot().get("active"):
                    wifi.disconnect()
            except Exception:
                pass
        self.show_status_message("Forgot saved WiFi", duration_ms=2200)
        self._update_wifi_status()
        self._update_ssid()
    
    def _on_brightness_changed(self, event):
        """Handle brightness slider change."""
        slider = self._get_slider_from_event(event)
        if not slider:
            return
        new_brightness = slider.get_value()
        
        self._brightness = new_brightness
        
        # Update label
        if 'brightness_value' in self.ui_elements:
            self.ui_elements['brightness_value'].set_text(f"{new_brightness}%")
        
        # Apply brightness to display immediately
        self._apply_brightness(new_brightness)

    def _get_slider_from_event(self, event):
        """Get slider from LVGL event with compatibility fallbacks."""
        try:
            slider = self.ui_elements.get("brightness_slider")
            if slider:
                return slider
        except Exception:
            pass
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
    
    def _apply_brightness(self, brightness):
        """Apply brightness to the display."""
        try:
            # Access display via TFT object
            if self.tft and hasattr(self.tft, 'display'):
                self.tft.display.set_backlight(brightness)
                self.logger.debug(f"Brightness set to {brightness}%")
            else:
                self.logger.warning("No display available for brightness control")
        except Exception as e:
            self.logger.error(f"Failed to set brightness: {e}")
    
    def on_back_pressed(self, event):
        """Navigate back to main menu."""
        self.logger.info("Back to main menu from settings")
        if self.game_ui:
            self.game_ui.show_panel('main_menu')  # Back to menu (not home)
