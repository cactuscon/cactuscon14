import lvgl as lv
import time
import gc
import sys

from cactuscon import config
from cactuscon.prefs import prefs
from cactuscon.hw.wifi import WiFiManager
from cactiotpad.client import CactIOTPadClient
from cactuscon.game.engine.character.care import tick_care_timers
from cactuscon.utils import Logger
from cactuscon.ui.sprites import _SPRITE_CACHE, evict_sprite_cache


logger = Logger(config.LOG_LEVEL)


# Panel registry: name -> (module_path, class_name)
# Panels are imported on-demand when first shown
PANEL_REGISTRY = {
    'loading': ('cactuscon.ui.panels.loading', 'LoadingPanel'),
    'main_menu': ('cactuscon.ui.panels.main_menu', 'MainMenuPanel'),
    'extras': ('cactuscon.ui.panels.extras', 'ExtrasPanel'),
    'character': ('cactuscon.ui.panels.character', 'CharacterPanel'),
    'character_evo': ('cactuscon.ui.panels.character_evo', 'CharacterEvoPanel'),
    'evolution_anim': ('cactuscon.ui.panels.evolution_anim', 'EvolutionAnimPanel'),
    'character_care': ('cactuscon.ui.panels.character_care', 'CharacterCarePanel'),
    'character_pack': ('cactuscon.ui.panels.character_pack', 'CharacterPackPanel'),
    'settings': ('cactuscon.ui.panels.settings', 'SettingsPanel'),
    'handle_edit': ('cactuscon.ui.panels.handle_edit', 'HandleEditPanel'),
    'wifi_connect': ('cactuscon.ui.panels.wifi_flow_panel', 'WifiConnectFlowPanel'),
    'registration': ('cactuscon.ui.panels.registration', 'RegistrationPanel'),
    'battle_matchmaking': ('cactuscon.ui.panels.battle_matchmaking', 'BattleMatchmakingPanel'),
    'battle_screen': ('cactuscon.ui.panels.battle_screen', 'BattlePanel'),
    'battle_result': ('cactuscon.ui.panels.battle_result', 'BattleResultPanel'),
    'cactuscon_info': ('cactuscon.ui.panels.cactuscon_info', 'CactusConInfoPanel'),
    'schedule_day': ('cactuscon.ui.panels.cactuscon_info', 'ScheduleDayPanel'),
    'schedule_mode': ('cactuscon.ui.panels.cactuscon_info', 'ScheduleModePanel'),
    'track_select': ('cactuscon.ui.panels.cactuscon_info', 'TrackSelectPanel'),
    'track_talk_list': ('cactuscon.ui.panels.cactuscon_info', 'TrackTalkListPanel'),
    'timeslot_view': ('cactuscon.ui.panels.cactuscon_info', 'TimeslotViewPanel'),
    'talk_detail': ('cactuscon.ui.panels.cactuscon_info', 'TalkDetailPanel'),
    'map': ('cactuscon.ui.panels.cactuscon_info', 'MapPanel'),
    'chat': ('cactuscon.ui.panels.chat', 'ChatPanel'),
}

# Panels to preload when memory_efficient=False
PRELOAD_PANELS = list(
    p for p in PANEL_REGISTRY.keys() 
    if p not in [
        "evolution_anim", 
        "talk_detail", 
        "handle_edit", 
        "wifi_connect",
        "settings",
        "loading",
        "extras"
        ]  
        # These are less frequently used and/or more memory intensive, so we skip preloading them even in non-memory-efficient mode.
    )

WIFI_API_PANELS = {"registration", "chat"}



class GameUI:
    """
    Game UI Manager - Coordinates all UI panels and screens.
    
    Manages panel lifecycle with TRUE lazy loading for memory efficiency:
    - Panels are defined in PANEL_REGISTRY (module path + class name)
    - Panel modules are ONLY imported when first shown
    - Only one panel active at a time
    - Old panels are unloaded to free memory
    - Sprite actors overlay on top of panels
    
    Usage:
        game_ui = GameUI(display)
        
        # Show panel (imports module and loads on first access)
        game_ui.show_panel('character')  # Show home screen
        
        # In main loop
        game_ui.loop()
    """

    __slots__ = (
        "screen",
        "display",
        "battle_manager",
        "memory_efficient",
        "wifi",
        "api_client",
        "pixels",
        "panel_classes",
        "panel_instances",
        "current_panel",
        "current_panel_obj",
        "chat_has_unread",
        "actors",
        "active",
        "bg_color",
        "last_actor_update",
        "last_panel_update",
        "panel_update_interval_ms",
    )
    
    def __init__(self, screen, battle_manager=None, memory_efficient=True):
        self.screen = screen  # TFT object with keyboard, display, etc.
        self.display = screen.display  # LVGL display for backwards compatibility
        self.battle_manager = battle_manager
        self.memory_efficient = memory_efficient
        self.wifi: WiFiManager|None = None  # Assigned by BadgeApplication after init
        self.api_client: CactIOTPadClient|None = None  # Assigned by BadgeApplication after init
        self.pixels = None  # Optional shared NeoPixelController from application
        
        # Panel management (true lazy loading - no pre-imports)
        self.panel_classes = {}    # name -> Panel class (loaded on demand)
        self.panel_instances = {}  # name -> Panel instance (loaded)
        self.current_panel = None  # Current active panel name
        self.current_panel_obj = None  # Current active panel instance
        self.chat_has_unread = False  # Ephemeral unread indicator for menu badge
        
        # Sprite actors (overlay on top of panels)
        self.actors = []          # List of SpriteActor instances
        
        # State
        self.active = True        # Is LVGL UI active?
        self.bg_color = 0x0000    # RGB565 black
        self.last_actor_update = 0  # ms timestamp for actor updates
        self.last_panel_update = 0  # ms timestamp for panel updates
        self.panel_update_interval_ms = 100  # Update panels every 100ms
        
        logger.info("GameUI initialized")
    
    def get_current_panel(self):
        """
        Get the current active panel instance.
        
        Returns:
            Panel instance or None if no panel is active.
        """
        return self.current_panel_obj
    
    def _get_panel_class(self, name):
        """
        Get panel class by name, importing module on-demand if needed.
        
        Args:
            name: Panel name from PANEL_REGISTRY
            
        Returns:
            Panel class or None if not found
        """
        # Return cached class if already imported
        if name in self.panel_classes:
            logger.debug(f"Panel '{name}' already cached")
            return self.panel_classes[name]
        
        # Check if panel is in registry
        if name not in PANEL_REGISTRY:
            logger.error(f"Panel '{name}' not in PANEL_REGISTRY")
            return None
        
        module_path, class_name = PANEL_REGISTRY[name]
        
        try:
            logger.info(f"Importing: {module_path}.{class_name}")
            # Dynamic import - only loads module when needed
            module = __import__(module_path, None, None, [class_name], 0)
            panel_class = getattr(module, class_name)
            # Cache the class for future use
            self.panel_classes[name] = panel_class
            logger.info(f"Imported panel class: {name}")
            return panel_class
        except Exception as e:
            logger.error(f"Failed to import panel '{name}': {e}")
            sys.print_exception(e)
            return None
    
    def register_panel(self, name, panel_class):
        """
        Register a panel class directly (bypasses PANEL_REGISTRY).
        
        Use this for custom panels not in the registry.
        For standard panels, just call show_panel() - it auto-imports.

        Args:
            name (str): Panel identifier.
            panel_class: Panel class (subclass of BasePanel).
        """
        self.panel_classes[name] = panel_class
        logger.debug(f"Registered panel: {name}")
    
    def set_wifi_manager(self, wifi_manager):
        """
        Set the WiFi manager for the UI and propagate to loaded panels.

        Args:
            wifi_manager: WiFiManager instance.
        """
        self.wifi = wifi_manager
        for panel in self.panel_instances.values():
            try:
                panel.wifi = wifi_manager
            except Exception:
                pass

    def set_api_client(self, api_client):
        """
        Set the API client for the UI and propagate to loaded panels.

        Args:
            api_client: CactIOTPadClient instance.
        """
        self.api_client = api_client
        for panel in self.panel_instances.values():
            try:
                if hasattr(panel, "set_api_client"):
                    panel.set_api_client(api_client)
            except Exception:
                pass

    def set_battle_manager(self, battle_manager):
        """
        Set the battle manager for the UI and propagate to loaded panels.

        Args:
            battle_manager: BattleManager instance.
        """
        self.battle_manager = battle_manager
        for panel in self.panel_instances.values():
            try:
                panel.battle_manager = battle_manager
            except Exception:
                pass

    def set_pixels_controller(self, pixels_controller):
        """
        Set the shared NeoPixel controller and propagate to loaded panels.

        Args:
            pixels_controller: NeoPixelController singleton from application.
        """
        self.pixels = pixels_controller
        for panel in self.panel_instances.values():
            try:
                if hasattr(panel, "set_pixels"):
                    panel.set_pixels(pixels_controller)
                elif hasattr(panel, "pixels"):
                    panel.pixels = pixels_controller
            except Exception:
                pass
    
    def show_panel(self, name, unload_previous=None):
        """
        Show a panel (imports and loads on-demand if needed).
        
        Memory optimized:
        1. Panel module is imported ONLY when first shown
        2. Previous panel is UNLOADED before loading new panel
        This minimizes peak memory usage on ESP32-S3.

        Args:
            name (str): Panel identifier (must be in PANEL_REGISTRY or registered).
            unload_previous (bool): If True, unload previous panel to save memory.
                Defaults to self.memory_efficient if None.

        Returns:
            bool: True if panel shown successfully, False otherwise.
        """
        # Default unload behavior follows configured memory mode
        if unload_previous is None:
            unload_previous = self.memory_efficient

        is_in_panel_instances = name in self.panel_instances

        # Get panel class (imports module on-demand if needed)
        panel_class = None
        if not is_in_panel_instances:
            panel_class = self._get_panel_class(name)
            if panel_class is None:
                logger.error(f"Panel '{name}' not available")
                return False

        # Tick care timers on every panel transition to keep state fresh
        try:
            tick_care_timers(prefs)
        except Exception as e:
            logger.debug(f"tick_care_timers failed: {e}")
        
        # Store reference to previous panel for cleanup AFTER new panel is shown
        previous_panel = self.current_panel
        previous_panel_obj = self.current_panel_obj
        transition_screen = None

        if previous_panel_obj and previous_panel != name:
            # Avoid extra transition spinner during loading->character startup
            # (or in preloaded mode) where LVGL screen churn can stall on some
            # firmware builds.
            use_transition_spinner = self.memory_efficient
            if previous_panel == "loading" or name == "character":
                use_transition_spinner = False
            if use_transition_spinner:
                # Show transition spinner BEFORE hiding previous panel
                transition_screen = self._show_transition_spinner("Loading...")
            # Now hide previous to trigger on_hide and stop timers
            try:
                previous_panel_obj.hide()
            except Exception as hide_e:
                logger.debug(f"Hide previous panel failed: {hide_e}")
        
        try:
            # Load new panel if not already loaded
            if not is_in_panel_instances and panel_class is not None:
                # Memory-pressure eviction: if free memory is low, evict old sprites
                free_mem = gc.mem_free()
                if free_mem < 200_000:  # < 200KB free
                    try:
                        evicted = evict_sprite_cache(max_age_ms=None, min_free_percent=20)
                        if evicted:
                            logger.info(f"Memory pressure: evicted {evicted} sprites (free was {free_mem:,})")
                    except Exception:
                        pass
                
                logger.info(f"Instantiating panel: {name}")
                try:
                    panel_instance = panel_class(
                        screen=self.screen,
                        game_ui=self,
                        battle_manager=self.battle_manager,
                        logger_level=config.LOG_LEVEL,  # DEBUG level to trace panel loading issues
                        memory_efficient=self.memory_efficient,
                        pixels=self.pixels,
                    )
                    # Share app-owned WiFi manager with panels (e.g., ChatPanel).
                    if self.wifi is not None:
                        try:
                            panel_instance.wifi = self.wifi
                        except Exception:
                            pass
                    # Share app-owned API client if available.
                    if self.api_client is not None and hasattr(panel_instance, "set_api_client"):
                        try:
                            panel_instance.set_api_client(self.api_client)
                        except Exception:
                            pass
                    # Share app-owned pixel controller when supported.
                    if self.pixels is not None:
                        try:
                            if hasattr(panel_instance, "set_pixels"):
                                panel_instance.set_pixels(self.pixels)
                            elif hasattr(panel_instance, "pixels"):
                                panel_instance.pixels = self.pixels
                        except Exception:
                            pass
                    self.panel_instances[name] = panel_instance
                    is_in_panel_instances = True
                except Exception as e:
                    logger.error(f"Failed to instantiate panel '{name}': {e}")
                    return False
            else:
                logger.debug(f"Using preloaded panel: {name}")

            # Get loaded panel instance
            panel_instance = self.panel_instances[name]

            # Delete transition spinner BEFORE calling show() on the new panel
            # The new panel's show() will display immediately
            if transition_screen is not None:
                try:
                    transition_screen.delete()
                except Exception:
                    pass
                transition_screen = None
            
            # Show new panel (panel is responsible for its own spinner if needed)
            success = panel_instance.show()
        finally:
            # If anything failed before deleting, make sure spinner is gone so UI isn't stuck.
            if transition_screen is not None:
                try:
                    transition_screen.delete()
                except Exception:
                    pass
                transition_screen = None
        
        if previous_panel_obj and previous_panel != name and unload_previous:
            logger.debug(f"Unloading panel: {previous_panel}")
            previous_panel_obj.unload()
            if previous_panel in self.panel_instances:
                del self.panel_instances[previous_panel]
            gc.collect()
            # Log sprite cache state
            try:
                if _SPRITE_CACHE:
                    total_cached = sum(e.get("size", 0) for e in _SPRITE_CACHE.values())
                    logger.debug(f"[SPRITE-CACHE] {len(_SPRITE_CACHE)} entries, ~{total_cached:,} bytes")
            except Exception:
                pass

        if success:
            self.current_panel = name
            self.current_panel_obj = panel_instance
            logger.info(f"Showing panel: {name}")
            
            # Auto-hide spinner only if panel didn't modify it (didn't take ownership)
            if getattr(panel_instance, "_auto_spinner_active", False):
                try:
                    lv.task_handler()
                    time.sleep_ms(20)
                except Exception:
                    pass
                panel_instance.hide_spinner()
                panel_instance._auto_spinner_active = False

            # Power-save WiFi when leaving API-only panels.
            if (
                previous_panel in WIFI_API_PANELS
                and name not in WIFI_API_PANELS
                and self.wifi is not None
            ):
                try:
                    if self.wifi.is_connected() or self.wifi.get_status_snapshot().get("active"):
                        logger.info(f"Power save: disabling WiFi after leaving '{previous_panel}'")
                        self.wifi.disconnect()
                except Exception as e:
                    logger.debug(f"WiFi power-save disconnect skipped: {e}")
                gc.collect()
        
        return success

    def _show_transition_spinner(self, message="Loading..."):
        screen = lv.obj()
        screen.set_style_bg_color(lv.color_black(), 0)

        overlay = lv.obj(screen)
        overlay.set_size(lv.pct(100), lv.pct(100))
        overlay.set_style_bg_color(lv.color_hex(0x000000), 0)
        try:
            overlay.set_style_bg_opa(lv.OPA._50, 0)
        except Exception:
            try:
                overlay.set_style_bg_opa(128, 0)
            except Exception:
                pass
        overlay.set_style_border_width(0, 0)
        overlay.remove_flag(lv.obj.FLAG.SCROLLABLE)

        spinner_size = 48
        spinner_box = lv.obj(overlay)
        spinner_box.set_size(spinner_size, spinner_size)
        spinner_box.align(lv.ALIGN.CENTER, 0, -18)
        try:
            spinner_box.set_style_bg_opa(lv.OPA.TRANSP, 0)
        except Exception:
            try:
                spinner_box.set_style_bg_opa(0, 0)
            except Exception:
                pass
        spinner_box.set_style_border_width(0, 0)
        spinner_box.remove_flag(lv.obj.FLAG.SCROLLABLE)

        spinner = lv.spinner(spinner_box)
        try:
            spinner.set_spin_time(900)
            spinner.set_arc_length(70)
        except Exception:
            try:
                spinner.set_anim_time(900)
            except Exception:
                pass
        if hasattr(spinner, "set_size"):
            spinner.set_size(spinner_size, spinner_size)
        else:
            if hasattr(spinner, "set_width"):
                spinner.set_width(spinner_size)
        if hasattr(spinner, "set_height"):
            spinner.set_height(spinner_size)
        spinner.set_style_arc_width(2, 0)
        spinner.align(lv.ALIGN.CENTER, 0, 0)
        spinner.set_style_arc_color(lv.color_hex(0x333333), 0)
        try:
            spinner.set_style_arc_width(3, lv.PART.INDICATOR)
            spinner.set_style_arc_color(lv.color_hex(0xCCCCCC), lv.PART.INDICATOR)
        except Exception:
            try:
                spinner.set_style_arc_color(lv.color_hex(0xCCCCCC), 0)
            except Exception:
                pass

        label = lv.label(overlay)
        label.set_text(message or "Loading...")
        label.set_style_text_color(lv.color_hex(0xDDDDDD), 0)
        label.align(lv.ALIGN.CENTER, 0, 22)

        lv.screen_load(screen)
        try:
            lv.task_handler()
            time.sleep_ms(30)
        except Exception:
            try:
                time.sleep(0.03)
            except Exception:
                pass
        return screen
    
    def preload_panels(self, progress_callback=None):
        """
        Instantiate and load all panels up-front.

        Useful when memory pressure is acceptable and we want faster navigation.

        Args:
            progress_callback: Optional callable invoked between preload steps.
                Signature: callback(panel_name, stage) where stage is one of
                {"start", "loaded", "error"}.
        """
        for name in PRELOAD_PANELS:
            if progress_callback:
                try:
                    progress_callback(name, "start")
                except Exception:
                    pass
            if name not in self.panel_instances:
                panel_class = self._get_panel_class(name)
                if not panel_class:
                    continue
                try:
                    instance = panel_class(
                        screen=self.screen,
                        game_ui=self,
                        battle_manager=self.battle_manager,
                        logger_level=config.LOG_LEVEL,
                        memory_efficient=self.memory_efficient,
                    )
                    # Share app-owned WiFi manager with panels (e.g., ChatPanel).
                    if self.wifi is not None:
                        try:
                            instance.wifi = self.wifi
                        except Exception:
                            pass
                    if self.api_client is not None:
                        if hasattr(instance, "set_api_client"):
                            try:
                                instance.set_api_client(self.api_client)
                            except Exception:
                                pass
                        else:
                            try:
                                instance.api_client = self.api_client
                            except Exception:
                                pass
                    
                    # Load UI objects so they're ready before navigation
                    instance.load()
                    self.panel_instances[name] = instance
                    if progress_callback:
                        try:
                            progress_callback(name, "loaded")
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Preload failed for panel '{name}': {e}")
                    sys.print_exception(e)
                    if progress_callback:
                        try:
                            progress_callback(name, "error")
                        except Exception:
                            pass

    def add_actor(self, actor):
        """
        Add a sprite actor (overlay on top of panels).

        Args:
            actor: SpriteActor instance to add.
        """
        self.actors.append(actor)

    def show_ui(self):
        """
        Activate (show) the UI.
        """
        self.active = True

    def hide_ui(self):
        """
        Deactivate (hide) the UI.
        """
        self.active = False

    def draw(self):
        """
        Draw the current UI state (panels and actors).

        Draws all sprite actors overlaying on top of panels. LVGL panels handle their own drawing.
        """
        for actor in self.actors:
            if actor.visible:
                actor.draw()
        if self.active:
            lv.task_handler()

    def clear_screen(self):
        """
        Clear the screen (LVGL 9.4 manages rendering internally).

        Sets the active screen background to black.
        """
        scr = lv.screen_active()
        if scr:
            scr.set_style_bg_color(lv.color_black(), 0)

    def loop(self):
        """
        Main update loop for GameUI.

        Call this regularly (e.g., every 50-100ms) to:
            - Update the active panel
            - Update sprite actors
            - Handle LVGL tasks
        """
        if not self.active:
            return
        now = time.ticks_ms()
        # Update current panel (polls for state changes, animations, etc.)
        if self.current_panel_obj and time.ticks_diff(now, self.last_panel_update) >= self.panel_update_interval_ms:
            self.current_panel_obj.update()
            self.last_panel_update = now
        # NOT IMPLEMENTED: Update sprite actors (advance animation frames)
        # if time.ticks_diff(now, self.last_actor_update) >= 500:
        #     for actor in self.actors:
        #         if actor.visible:
        #             actor.update()
        #     self.last_actor_update = now
        self.draw()
