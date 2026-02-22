"""Battle result panel - Show battle outcome and stats."""

import lvgl as lv
from cactuscon.ui.panels.base_panel import BasePanel


class BattleResultPanel(BasePanel):
    """
    Battle result screen shown after battle completion.
    
    Layout:
        ┌─────────────────────────┐
        │     Victory!            │
        │        * * *            │
        │                         │
        │  Experience: +50        │
        │  Wins: 5   Losses: 2    │
        │                         │
        │  ┌──────────────────┐  │
        │  │   Continue       │  │
        │  └──────────────────┘  │
        └─────────────────────────┘
    """
    
    def __init__(self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs):
        """
        Initialize battle result panel.
        
        Args:
            screen: TFT screen object
            game_ui: Parent GameUI manager
            battle_manager: BattleManager instance (optional)
            logger_level: Logging level
        """
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        
        # Battle result data (set via set_result() before showing)
        self.winner = 0  # 0=draw, 1=player, 2=opponent
        self.exp_gained = 0
        self.wins = 0
        self.losses = 0
        self.voided = False
        self.error = None
        self.can_evolve_now = False
        self.creature_name = ""
    
    def create_ui(self):
        """Create battle result UI."""
        # Result title
        result_text = "Draw!" if self.winner == 0 else ("Victory!" if self.winner == 1 else "Defeat!")
        title = self.create_label(self.screen, result_text)
        title.set_align(lv.ALIGN.TOP_MID)
        title.set_y(30)
        self.ui_elements['title'] = title
        
        # Stars/rating (for wins)
        stars = self.create_label(self.screen, "* * *" if self.winner == 1 else "")
        stars.set_align(lv.ALIGN.TOP_MID)
        stars.set_y(60)
        self.ui_elements['stars'] = stars
        
        # Experience gained
        exp_label = self.create_label(self.screen, f"Experience: +{self.exp_gained}")
        exp_label.set_align(lv.ALIGN.CENTER)
        exp_label.set_y(-28)
        self.ui_elements['exp'] = exp_label
        
        # Stats summary
        stats_label = self.create_label(self.screen, f"Wins: {self.wins}   Losses: {self.losses}")
        stats_label.set_align(lv.ALIGN.CENTER)
        stats_label.set_y(2)
        self.ui_elements['stats'] = stats_label

        # Evolution message (shown when the victorious creature can evolve)
        evolve_label = self.create_label(self.screen, "")
        evolve_label.set_align(lv.ALIGN.CENTER)
        evolve_label.set_y(32)
        # set color to yellow
        evolve_label.set_style_text_color(lv.color_hex(0xffff00), 0)
        self.ui_elements['evolve'] = evolve_label
        
        # Continue button
        btn_continue = self.create_button(
            self.screen,
            "Continue",
            callback=self.on_back_pressed,
            width=200,
            height=50
        )
        btn_continue.set_align(lv.ALIGN.BOTTOM_MID)
        btn_continue.set_y(-30)
        self.ui_elements['btn_continue'] = btn_continue
    
    def set_result(self, winner, exp_gained=0, wins=0, losses=0):
        """
        Set battle result data before showing panel.
        
        Args:
            winner: 0=draw, 1=player won, 2=opponent won
            exp_gained: Experience points gained
            wins: Total wins
            losses: Total losses
        """
        self.winner = winner
        self.exp_gained = exp_gained
        self.wins = wins
        self.losses = losses
        
        self.logger.info(f"Battle result set: winner={winner}, exp={exp_gained}")
        
        # If panel is already loaded, update UI
        if self.loaded:
            self._update_ui()
    
    def _update_ui(self):
        """Update UI elements with current result data."""
        # Update title - show void if battle was voided
        if self.voided:
            result_text = "Battle Void"
        else:
            result_text = "Draw!" if self.winner == 0 else ("Victory!" if self.winner == 1 else "Defeat!")
        if 'title' in self.ui_elements:
            self.ui_elements['title'].set_text(result_text)
        
        # Update stars - show error message if voided, otherwise stars
        if 'stars' in self.ui_elements:
            if self.voided and self.error:
                self.ui_elements['stars'].set_text(self.error[:30])  # Truncate long errors
            else:
                self.ui_elements['stars'].set_text("* * *" if self.winner == 1 else "")
        
        # Update experience
        if 'exp' in self.ui_elements:
            self.ui_elements['exp'].set_text(f"Experience: +{self.exp_gained}")
        
        # Update stats
        if 'stats' in self.ui_elements:
            self.ui_elements['stats'].set_text(f"Wins: {self.wins}   Losses: {self.losses}")
        
        # Evolution prompt
        if 'evolve' in self.ui_elements:
            if self.can_evolve_now and self.creature_name:
                self.ui_elements['evolve'].set_text(f"{self.creature_name} can evolve!")
            else:
                self.ui_elements['evolve'].set_text("")
    
    def on_show(self):
        """Update UI when shown - reads result from battle_manager."""
        self.logger.info("Battle result panel shown")
        
        # Read result data from battle_manager
        if self.battle_manager and self.battle_manager.last_battle_result:
            result = self.battle_manager.last_battle_result
            self.winner = result.get('winner', 0)
            self.exp_gained = result.get('exp_gained', 0)
            self.wins = result.get('wins', 0)
            self.losses = result.get('losses', 0)
            self.voided = result.get('voided', False)
            self.error = result.get('error', None)
            self.can_evolve_now = result.get('can_evolve_now', False)
            self.creature_name = result.get('creature_name', "")
            self.logger.info(f"Loaded result: winner={self.winner}, exp={self.exp_gained}, voided={self.voided}")
        else:
            self.logger.warning("No battle result data available")
            self.voided = False
            self.error = None
            self.can_evolve_now = False
            self.creature_name = ""
        
        self._update_ui()
