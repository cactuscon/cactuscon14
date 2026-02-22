"""Main menu panel - Navigation menu accessed from character home screen."""

import lvgl as lv
from cactuscon.ui.panels.base_panel import BasePanel


class MainMenuPanel(BasePanel):
    """
    Main menu screen with navigation buttons.
    
    Accessed via menu button on character home screen.
    Close button in top-left returns to character view.
    Simple flat layout - buttons placed directly on screen.
    """
    
    def create_ui(self):
        """Create main menu UI with flat button layout."""
        # Set screen background - screen itself is the container
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.set_style_pad_all(0, 0)
        
        # Disable scrolling on screen (we want fixed layout)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)
        
        # Close button in top-left corner (returns to character home)
        btn_close = lv.button(self.screen)
        btn_close.set_size(50, 30)
        btn_close.align(lv.ALIGN.TOP_LEFT, 5, 5)
        btn_close.set_style_bg_color(lv.color_hex(0x333333), 0)
        btn_close.set_style_bg_color(lv.color_hex(0x555555), lv.STATE.PRESSED)
        btn_close.set_style_border_color(lv.color_hex(0x888888), 0)
        btn_close.set_style_border_width(1, 0)
        btn_close.set_style_radius(4, 0)
        btn_close.set_style_pad_all(0, 0)
        close_label = lv.label(btn_close)
        close_label.set_text("X")
        close_label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
        close_label.center()
        btn_close.add_event_cb(self._on_close_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_close'] = btn_close
        
        # Title at top (centered between close and keyboard buttons)
        title = lv.label(self.screen)
        title.set_text("CactusCon 14")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_MID, 0, 12)
        self.ui_elements['title'] = title
        
        # Subtitle
        subtitle = lv.label(self.screen)
        subtitle.set_text("Select an option")
        subtitle.set_style_text_color(lv.color_hex(0x888888), 0)
        subtitle.align(lv.ALIGN.TOP_MID, 0, 38)
        self.ui_elements['subtitle'] = subtitle
        
        # Button styling constants - 2x2 grid layout
        BTN_TOP_Y = 65
        BTN_BOTTOM_Y = 115
        BTN_COL_OFFSET = 75  # Distance from center to button center
        
        # Top row: Battle (left), Settings (right)
        btn_battle = self._create_menu_button("Battle", -BTN_COL_OFFSET, BTN_TOP_Y)
        btn_battle.add_event_cb(self._on_battle_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_battle'] = btn_battle
        
        btn_settings = self._create_menu_button("Settings", BTN_COL_OFFSET, BTN_TOP_Y)
        btn_settings.add_event_cb(self._on_settings_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_settings'] = btn_settings
        
        # Bottom row: Chat (left), CactusCon Info (right)
        btn_chat = self._create_menu_button("Chat", -BTN_COL_OFFSET, BTN_BOTTOM_Y)
        btn_chat.add_event_cb(self._on_chat_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_chat'] = btn_chat
        
        btn_info = self._create_menu_button("CactusCon Info", BTN_COL_OFFSET, BTN_BOTTOM_Y)
        btn_info.add_event_cb(self._on_info_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_info'] = btn_info

        # Extras button row (centered below)
        btn_extras = self._create_menu_button("Extras", 0, BTN_BOTTOM_Y + 50)
        btn_extras.add_event_cb(self._on_extras_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_extras'] = btn_extras
    
    def _create_menu_button(self, text, x_offset, y_pos):
        """
        Create a styled menu button at specified position.
        
        Args:
            text: Button label text
            x_offset: X offset from center (negative = left, positive = right)
            y_pos: Y position from top
            
        Returns:
            lv.button object
        """
        btn = lv.button(self.screen)
        btn.set_size(140, 35)
        btn.align(lv.ALIGN.TOP_MID, x_offset, y_pos)
        
        # Style the button
        btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        btn.set_style_bg_color(lv.color_hex(0x2a2a2a), lv.STATE.PRESSED)
        btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn.set_style_border_width(2, 0)
        btn.set_style_radius(8, 0)
        
        # Label
        label = lv.label(btn)
        label.set_text(text)
        label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        label.center()
        
        return btn
    
    def on_show(self):
        """Called when main menu is displayed."""
        self.logger.info("Main menu displayed")
        self._update_chat_badge()
    
    def on_hide(self):
        """Called when main menu is hidden."""
        self.logger.debug("Main menu hidden")

    # Button click handlers
    
    def _on_close_clicked(self, event):
        """Close menu and return to character home screen."""
        self.logger.info("Close button - returning to character")
        if self.game_ui:
            self.game_ui.show_panel('character')
    
    def _on_battle_clicked(self, event):
        """Navigate to battle matchmaking."""
        self.logger.info("Battle mode selected")
        if self.game_ui:
            self.game_ui.show_panel('battle_matchmaking')
    
    def _on_settings_clicked(self, event):
        """Navigate to settings."""
        self.logger.info("Settings selected")
        if self.game_ui:
            self.game_ui.show_panel('settings')
    
    def _on_extras_clicked(self, event):
        """Navigate to extras (maps, etc.)."""
        self.logger.info("Extras selected")
        if self.game_ui:
            self.game_ui.show_panel('extras')

    def _on_info_clicked(self, event):
        """Navigate to CactusCon info."""
        self.logger.info("CactusCon Info selected")
        if self.game_ui:
            self.game_ui.show_panel('cactuscon_info')

    def _on_chat_clicked(self, event):
        """Navigate to chat panel."""
        self.logger.info("Chat selected")
        if self.game_ui:
            self.game_ui.chat_has_unread = False
            self.game_ui.show_panel('chat')

    def _update_chat_badge(self):
        btn = self.ui_elements.get("btn_chat")
        if not btn:
            return
        unread = bool(getattr(self.game_ui, "chat_has_unread", False))
        border = lv.color_hex(0xFFFF00) if unread else lv.color_hex(0x00ff00)
        text = lv.color_hex(0xFFFF00) if unread else lv.color_hex(0x00ff00)
        try:
            btn.set_style_border_color(border, 0)
        except Exception:
            pass
        try:
            label = btn.get_child(0)
            if label:
                label.set_style_text_color(text, 0)
        except Exception:
            pass
