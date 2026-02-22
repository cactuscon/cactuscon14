"""Base panel class for all LVGL UI screens.

Exception Handling Pattern:
    This module and derived panels use defensive `except Exception: pass` patterns
    for LVGL widget operations. This is intentional for embedded UI resilience:
    
    - LVGL objects may be deleted/invalid during UI transitions
    - Widget state can be inconsistent during rapid user interaction  
    - Memory pressure on ESP32 can cause unpredictable widget failures
    
    Silent failures in non-critical UI updates are preferred over crashes.
    Critical operations (data persistence, network) should log errors.
"""

import lvgl as lv
import gc
import time
from cactuscon.utils import Logger
from cactuscon import config
from cactuscon.ui.graphics import GameUI
from cactuscon.ui.sprites import get_cached_sprite, put_cached_sprite
from cactuscon.ui.image_utils import load_rgb565_file, create_image_descriptor


class ListContainer:
    """
    Wrapper for LVGL list-like container.
    
    LVGL 9.x doesn't have lv.list(), so we simulate it with a flex container.
    This class wraps an lv.obj and provides list-like methods.
    """
    
    def __init__(self, parent, width=None, height=None):
        """Create a scrollable list container."""
        self.obj = lv.obj(parent)
        if width:
            self.obj.set_width(width)
        if height:
            self.obj.set_height(height)
        
        # Configure as scrollable list
        self.obj.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.obj.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.obj.set_style_pad_row(5, 0)
        self.obj.set_style_pad_all(5, 0)
        
        # Track items in Python list (not on LVGL object)
        self._items = []
    
    def add_btn(self, icon, text):
        """Add a button item to the list."""
        btn = lv.button(self.obj)
        btn.set_width(lv.pct(100))
        btn.set_height(40)
        label = lv.label(btn)
        label.set_text(text)
        label.center()
        self._items.append(btn)
        return btn
    
    def clean(self):
        """Remove all items from the list."""
        for item in self._items:
            try:
                item.delete()
            except Exception:
                pass
        self._items = []
    
    # Forward common LVGL methods to underlying object
    def set_align(self, *args):
        return self.obj.set_align(*args)
    
    def set_x(self, *args):
        return self.obj.set_x(*args)
    
    def set_y(self, *args):
        return self.obj.set_y(*args)
    
    def set_size(self, *args):
        return self.obj.set_size(*args)
    
    def set_style_bg_color(self, *args):
        return self.obj.set_style_bg_color(*args)


class BasePanel:
    """
    Abstract base class for all UI panels.
    
    Each panel represents one screen or view in the badge UI.
    Panels are lazy-loaded (created on demand) and can be unloaded
    to free memory when not in use.
    
    Lifecycle:
        1. Panel class registered with GameUI (not instantiated yet)
        2. GameUI.show_panel() instantiates panel and calls load()
        3. Panel creates LVGL objects and shows them
        4. When switching panels, unload() is called to free memory
        5. Panel instance is optionally destroyed (or kept for reuse)
    
    Subclasses must implement:
        - create_ui(): Build LVGL UI elements
        - on_show(): Called when panel becomes visible
        - on_hide(): Called when panel becomes hidden
        
    Optional overrides:
        - on_back_pressed(): Handle back/cancel button
        - on_cleanup(): Additional cleanup beyond LVGL deletion
    """
    
    def __init__(self, screen=None, game_ui: GameUI|None=None, battle_manager=None, logger_level=config.LOG_LEVEL, memory_efficient=True, **kwargs):
        """
        Initialize panel base.
        
        Args:
            screen: TFT screen object (has display, keyboard, touch, etc.)
            game_ui: Parent GameUI manager (for navigation)
            battle_manager: BattleManager instance (for game logic access)
            logger_level: Logging level
            memory_efficient: If False, keep panel objects resident (skip unload)
        """
        self.logger = Logger(logger_level)
        self.tft = screen  # TFT object with keyboard, display, touch
        self.display = screen.display if screen else None  # ILI9341 for legacy compatibility
        self.game_ui = game_ui
        self.battle_manager = battle_manager
        self.memory_efficient = memory_efficient
        
        # LVGL objects
        self.screen = None  # LVGL screen object (lv.obj) - created in load()
        self.ui_elements = {}  # name -> lv.obj for tracking
        
        # State
        self.loaded = False
        self.visible = False
        self._spinner_visible = False
        self._spinner_last_message = None
        self._auto_spinner_active = False
        # Shared icon state to keep descriptors/data alive
        self._icon_images = {}
        self._icon_img_dsc = {}
        self._icon_img_data = {}
        
        self.logger.debug(f"{self.__class__.__name__} initialized")
    
    def load(self):
        """
        Load panel and create UI.
        
        Creates LVGL screen object and all UI elements.
        Only called once (or after unload).
        
        Returns:
            True if loaded successfully
        """
        if self.loaded:
            self.logger.warning(f"{self.__class__.__name__} already loaded")
            return True
        
        try:
            self.logger.info(f"Loading {self.__class__.__name__}...")
            
            # Create root screen
            self.logger.debug(f"  Creating lv.obj() screen...")
            self.screen = lv.obj()
            self.logger.debug(f"  Screen created: {self.screen}")
            
            
            # Subclass creates UI
            self.logger.debug(f"  Calling create_ui()...")
            self.create_ui()
            self.logger.debug(f"  create_ui() complete")

            self.loaded = True
            gc.collect()  # Clean up after UI creation
            
            self.logger.debug(f"{self.__class__.__name__} loaded (free mem: {gc.mem_free()} bytes)")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load panel {self.__class__.__name__}: {e}")
            self.loaded = False
            return False
    
    def unload(self):
        """
        Unload panel and free memory.
        
        Destroys all LVGL objects and releases memory.
        Panel can be loaded again later if needed.
        """
        if not self.memory_efficient:
            # In preloaded mode we keep panels resident; only hide if needed.
            if self.visible:
                self.hide()
            self.logger.debug(f"{self.__class__.__name__} unload skipped (memory_efficient=False)")
            return
        if not self.loaded:
            return
        
        try:
            self.logger.info(f"Unloading {self.__class__.__name__}...")
            
            # Hide first
            if self.visible:
                self.logger.debug(f"  Hiding panel...")
                self.hide()
            
            # Subclass cleanup
            self.logger.debug(f"  Calling on_cleanup()...")
            self.on_cleanup()
            self.logger.debug(f"  on_cleanup() done")
            
            # Clear tracked UI elements (don't delete individually - screen delete handles children)
            self.logger.debug(f"  Clearing ui_elements...")
            self.ui_elements.clear()
            self._spinner_visible = False
            
            # Clear icon references to allow GC
            self._icon_images.clear()
            self._icon_img_dsc.clear()
            self._icon_img_data.clear()
            
            # Delete screen (this deletes all children automatically)
            if self.screen is not None:
                self.logger.debug(f"  Deleting screen object...")
                try:
                    self.screen.delete()
                    self.logger.debug(f"  Screen deleted")
                except Exception as del_e:
                    self.logger.warning(f"  Screen delete exception: {del_e}")
                self.screen = None
            
            # Note: Sprite cache eviction is NOT done here automatically.
            # Panels that load large temporary assets (like LoadingPanel's banner)
            # should explicitly evict them in on_hide() or on_cleanup().
            # Memory-pressure eviction happens in GameUI.show_panel() when needed.
            
            self.loaded = False
            self.logger.debug(f"  Running gc.collect()...")
            gc.collect()
            
            self.logger.debug(f"{self.__class__.__name__} unloaded (free mem: {gc.mem_free()} bytes)")
            
        except Exception as e:
            self.logger.error(f"Error unloading {self.__class__.__name__}: {e}")
    
    def show(self):
        """
        Show this panel (make it the active screen).
        
        Returns:
            True if shown successfully
        """
        if not self.loaded:
            if not self.load():
                return False
        
        try:
            # Load the screen (LVGL 9.x API)
            lv.screen_load(self.screen)
            self.visible = True

            # Show auto-spinner before on_show() does its work
            auto_msg = "Loading..."
            auto_spinner = False
            if not self.is_spinner_visible():
                self.show_spinner(auto_msg)
                auto_spinner = True

            # Subclass notification
            self.on_show()
            
            # If panel modified the spinner message, it takes ownership (GameUI won't auto-hide)
            if auto_spinner and self._spinner_last_message != auto_msg:
                auto_spinner = False
            self._auto_spinner_active = auto_spinner

            self.logger.debug(f"{self.__class__.__name__} shown")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to show {self.__class__.__name__}: {e}")
            return False
    
    def hide(self):
        """Hide this panel (called when switching to another panel)."""
        if not self.visible:
            return
        
        self.visible = False
        self.on_hide()
        try:
            gc.collect()
        except Exception:
            pass
        
        self.logger.debug(f"{self.__class__.__name__} hidden")
    
    def update(self):
        """
        Update panel state (called periodically in main loop).
        
        Override in subclass for animations, timers, etc.
        """
        pass
    
    # Abstract methods - must be implemented by subclasses
    
    def create_ui(self):
        """
        Create all LVGL UI elements for this panel.
        
        Called during load(). Build UI here.
        Use self.ui_elements to track objects for cleanup.
        """
        raise NotImplementedError("Subclass must implement create_ui()")
    
    def on_show(self):
        """
        Called when panel becomes visible.
        
        Override for initialization that should happen each time
        the panel is shown (e.g., refresh data, reset state).
        """
        pass
    
    def on_hide(self):
        """
        Called when panel is hidden (switching to another panel).
        
        Override for cleanup that should happen when leaving
        (e.g., stop animations, cancel tasks).
        """
        pass
    
    def on_cleanup(self):
        """
        Called during unload() before deleting LVGL objects.
        
        Override for additional cleanup beyond LVGL deletion
        (e.g., cancel async tasks, close files).
        """
        pass
    
    def on_back_pressed(self, event=None):
        """
        Handle back/cancel button press.
        
        Override to implement back navigation.
        Default: go to main menu.
        
        Returns:
            True if back press handled, False to use default behavior
        """
        if self.game_ui:
            self.game_ui.show_panel('character')  # Return to home screen
            return True
        return False
    
    # Helper methods for common UI patterns

    def _ensure_spinner_overlay(self):
        """Create (or return) a full-screen spinner overlay for busy states."""
        if not self.screen:
            return None

        overlay = self.ui_elements.get('spinner_overlay')
        if overlay:
            return overlay

        overlay = lv.obj(self.screen)
        overlay.set_size(lv.pct(100), lv.pct(100))
        overlay.set_pos(0, 0)
        overlay.set_style_bg_color(lv.color_hex(0x000000), 0)
        # Some LVGL bindings expose opacity constants differently; fall back to 50%.
        try:
            overlay.set_style_bg_opa(lv.OPA._50, 0)
        except Exception:
            try:
                overlay.set_style_bg_opa(128, 0)
            except Exception:
                pass
        overlay.set_style_border_width(0, 0)
        overlay.remove_flag(lv.obj.FLAG.SCROLLABLE)
        overlay.add_flag(lv.obj.FLAG.HIDDEN)

        # spinner ctor signatures differ between LVGL bindings; safest is parent-only
        spinner_size = 48

        # Container to control spinner position/size independently of overlay
        spinner_box = lv.obj(overlay)
        spinner_box.set_size(spinner_size, spinner_size)
        spinner_box.align(lv.ALIGN.CENTER, 0, -24)
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

        # Explicit sizing inside box
        if hasattr(spinner, "set_size"):
            spinner.set_size(spinner_size, spinner_size)
        else:
            if hasattr(spinner, "set_width"):
                spinner.set_width(spinner_size)
            if hasattr(spinner, "set_height"):
                spinner.set_height(spinner_size)

        # lv.spinner is an lv.arc under the hood; on LVGL 9 the visible "spinner"
        # segment is typically PART.INDICATOR. If we only style PART.MAIN (0),
        # the indicator can remain transparent, making the spinner effectively invisible.
        spinner.set_style_arc_width(2, 0)
        spinner.align(lv.ALIGN.CENTER, 0, 0)
        spinner.set_style_arc_color(lv.color_hex(0x333333), 0)
        try:
            spinner.set_style_arc_width(3, lv.PART.INDICATOR)
            spinner.set_style_arc_color(lv.color_hex(0xCCCCCC), lv.PART.INDICATOR)
        except Exception:
            # Older/stripped bindings may not expose PART.INDICATOR; best effort.
            try:
                spinner.set_style_arc_color(lv.color_hex(0xCCCCCC), 0)
            except Exception:
                pass
        self.ui_elements['spinner'] = spinner

        label = lv.label(overlay)
        label.set_text("Loading...")
        label.set_style_text_color(lv.color_hex(0xDDDDDD), 0)
        label.align(lv.ALIGN.CENTER, 0, 24)
        self.ui_elements['spinner_label'] = label

        self.ui_elements['spinner_overlay'] = overlay
        return overlay

    def show_spinner(self, message="Loading...", pause_ms=0):
        """Show the busy spinner overlay with an optional message."""
        overlay = self._ensure_spinner_overlay()
        if not overlay:
            return

        label = self.ui_elements.get('spinner_label')
        if label and message is not None:
            label.set_text(message)
        self._spinner_last_message = message

        overlay.remove_flag(lv.obj.FLAG.HIDDEN)
        try:
            if hasattr(overlay, "move_foreground"):
                overlay.move_foreground()
        except Exception:
            pass
        spinner = self.ui_elements.get('spinner')
        if spinner:
            spinner.remove_flag(lv.obj.FLAG.HIDDEN)

        if self._spinner_visible:
            return

        self._spinner_visible = True
        # Flush LVGL to actually render the spinner.
        try:
            lv.task_handler()
            time.sleep_ms(5)
            if pause_ms:
                time.sleep_ms(int(pause_ms))
                lv.task_handler()
        except Exception:
            pass

    def hide_spinner(self):
        """Hide the busy spinner overlay if it is visible."""
        if not self._spinner_visible:
            return

        overlay = self.ui_elements.get('spinner_overlay')
        if overlay:
            overlay.add_flag(lv.obj.FLAG.HIDDEN)
        self._spinner_visible = False
        self._spinner_last_message = None

    def is_spinner_visible(self):
        """Return True if spinner overlay is currently visible."""
        return bool(self._spinner_visible)

    def spinner_pause(self, ms=60):
        """
        Yield to LVGL task handler and pause briefly.
        
        Useful for ensuring LVGL renders UI updates (like spinners) before
        continuing with blocking operations. Safe to call even if LVGL
        objects are invalid.
        
        Args:
            ms (int): Milliseconds to pause after task_handler call.
        """
        try:
            lv.task_handler()
            time.sleep_ms(ms)
        except Exception:
            # Silently ignore - LVGL state may be invalid during transitions
            pass

    # Modal dialog helpers (shared patterns for popup overlays)
    
    def create_modal(self, width_pct=100, height_pct=100):
        """
        Create a full-screen modal overlay.
        
        Creates a dark overlay that covers the screen for modal dialogs.
        Use show_modal() and hide_modal() to control visibility.
        
        Args:
            width_pct (int): Width as percentage of screen (default 100).
            height_pct (int): Height as percentage of screen (default 100).
            
        Returns:
            lv.obj: Modal container object, or None if no screen.
        """
        if not self.screen:
            return None
            
        modal = lv.obj(self.screen)
        modal.set_size(lv.pct(width_pct), lv.pct(height_pct))
        modal.set_style_bg_color(lv.color_hex(0x000000), 0)
        try:
            modal.set_style_bg_opa(lv.OPA.COVER, 0)
        except Exception:
            try:
                modal.set_style_bg_opa(255, 0)
            except Exception:
                pass
        modal.remove_flag(lv.obj.FLAG.SCROLLABLE)
        modal.add_flag(lv.obj.FLAG.HIDDEN)  # Start hidden
        return modal

    def show_modal(self, modal):
        """
        Show a modal overlay.
        
        Args:
            modal: The modal object returned by create_modal().
        """
        if modal:
            try:
                modal.remove_flag(lv.obj.FLAG.HIDDEN)
                if hasattr(modal, "move_foreground"):
                    modal.move_foreground()
            except Exception:
                pass

    def hide_modal(self, modal):
        """
        Hide a modal overlay.
        
        Args:
            modal: The modal object returned by create_modal().
        """
        if modal:
            try:
                modal.add_flag(lv.obj.FLAG.HIDDEN)
            except Exception:
                pass
    
    def create_button(self, parent, text, callback=None, width=None, height=None):
        """
        Create a styled button with text.
        
        Uses CactusCon theme: dark background with green border and text.
        
        Args:
            parent: Parent LVGL object
            text: Button text
            callback: Click event callback
            width: Optional button width
            height: Optional button height
            
        Returns:
            lv.button object (LVGL 9.x)
        """
        btn = lv.button(parent)
        if width:
            btn.set_width(width)
        if height:
            btn.set_height(height)
        
        # Theme styling: dark bg, green border, green text
        btn.set_style_bg_color(lv.color_hex(0x2a2a2a), 0)
        btn.set_style_bg_color(lv.color_hex(0x3a3a3a), lv.STATE.PRESSED)
        btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn.set_style_border_width(1, 0)
        btn.set_style_radius(4, 0)
        
        label = lv.label(btn)
        label.set_text(text)
        label.center()
        label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        
        if callback:
            btn.add_event_cb(callback, lv.EVENT.CLICKED, None)
        
        return btn
    
    def create_label(self, parent, text, align=lv.ALIGN.CENTER):
        """
        Create a text label.
        
        Args:
            parent: Parent LVGL object
            text: Label text
            align: Alignment (lv.ALIGN.*)
            
        Returns:
            lv.label object
        """
        label = lv.label(parent)
        label.set_text(text)
        label.set_align(align)
        return label

    def style_textarea(self, ta, bg_color=0x1a1a1a, border_color=0x00ff00, border_width=1, radius=4, pad_left=6):
        """
        Apply consistent styling to a textarea widget.
        
        Args:
            ta: LVGL textarea object
            bg_color: Background color (hex, default dark grey)
            border_color: Border color (hex, default green)
            border_width: Border width in pixels (default 1)
            radius: Corner radius (default 4)
            pad_left: Left padding (default 6)
        """
        ta.set_style_bg_color(lv.color_hex(bg_color), 0)
        ta.set_style_border_color(lv.color_hex(border_color), 0)
        ta.set_style_border_width(border_width, 0)
        ta.set_style_radius(radius, 0)
        ta.set_style_pad_left(pad_left, 0)
    
    def create_list(self, parent, width=None, height=None):
        """
        Create a scrollable list container.
        
        LVGL 9.x note: lv.list() doesn't exist, use lv.obj with flex layout.
        Returns a ListContainer wrapper that has add_btn() and clean() methods.
        
        Args:
            parent: Parent LVGL object
            width: Optional list width
            height: Optional list height
            
        Returns:
            ListContainer wrapper with .obj for the LVGL object
        """
        return ListContainer(parent, width, height)
    
    # Icon helpers (shared across panels)
    def _load_icon_descriptor(self, sprite_path, sprite_meta=None, target_size=32, do_swap=None):
        """
        Load a sprite and return descriptor for use with LVGL's native scaling.
        
        This method loads the FULL-SIZE sprite and returns it. The actual scaling
        is done by LVGL's hardware-accelerated renderer using set_scale() or
        LV_IMAGE_ALIGN_STRETCH, which is orders of magnitude faster than 
        CPU-based pixel manipulation.
        
        Returns:
            tuple: (lv.image_dsc_t, bytes, scale_factor) where scale_factor is 
                   256-based (256=100%, 128=50%, etc.) for use with set_scale()
                   Returns (None, None, None) on failure.
        """
        if not sprite_path:
            return None, None, None

        meta = sprite_meta or {}
        frame_width = meta.get("frame_width")
        frame_height = meta.get("frame_height")

        try:
            # Check raw sprite cache first
            cached = get_cached_sprite(sprite_path)
            if not cached:
                # Cache miss - load from disk
                self.logger.debug(f"[CACHE MISS] {sprite_path} - loading from disk")
                cached = load_rgb565_file(sprite_path, do_swap=do_swap if do_swap is not None else False)
                if cached:
                    put_cached_sprite(sprite_path, cached)
                else:
                    self.logger.warning(f"Failed to load sprite from {sprite_path}")
                    return None, None, None

            # Infer dimensions for icons without metadata (assume square)
            if not frame_width or not frame_height:
                pixels = len(cached) // 2
                side = int(pixels ** 0.5)
                if side * side == pixels and side > 0:
                    frame_width = frame_height = side
                else:
                    frame_width = frame_height = 32  # safe default

            # Create descriptor for full-size image
            img_dsc = create_image_descriptor(cached, frame_width, frame_height)
            
            # Calculate scale factor for LVGL (256 = 100%)
            # Scale down from frame_width to target_size
            scale_factor = (target_size * 256) // frame_width
            
            return img_dsc, cached, scale_factor
            
        except Exception as e:
            self.logger.warning(f"Icon descriptor load failed for {sprite_path}: {e}")
            return None, None, None

    def _set_icon_on_container(
        self,
        container,
        sprite_path,
        sprite_meta=None,
        target_size=None,
        cache_key=None,
        img_store=None,
        dsc_store=None,
        data_store=None,
        do_swap=None,
        clip_overflow=False,
    ):
        """
        Attach an icon image to a container and keep references alive.
        """
        if not container or not sprite_path:
            self.logger.warning("Invalid container or sprite path for icon")
            return None

        # Target defaults to container size; tolerate zero/uninitialized sizes
        try:
            width = container.get_width() or 0
            height = container.get_height() or 0
            max_target = min(width, height) if width > 0 and height > 0 else 0
        except Exception:
            max_target = 0

        if clip_overflow:
            try:
                if hasattr(lv, "STYLE_OVERFLOW"):
                    container.set_style_overflow(lv.STYLE_OVERFLOW.HIDDEN, 0)
            except Exception:
                try:
                    container.add_flag(lv.obj.FLAG.HIDDEN)
                    container.remove_flag(lv.obj.FLAG.HIDDEN)
                except Exception:
                    pass

        if target_size is None:
            target = max_target if max_target > 0 else 32
        else:
            target = target_size if max_target <= 0 else min(target_size, max_target)

        if target <= 0:
            target = 1

        result = self._load_icon_descriptor(
            sprite_path, sprite_meta=sprite_meta, target_size=target, do_swap=do_swap
        )
        if not result or not result[0]:
            self.logger.warning(
                f"Icon descriptor creation failed for {sprite_path} (target={target}, meta={sprite_meta})"
            )
            return None
        
        img_dsc, img_data, scale_factor = result

        key = cache_key if cache_key is not None else id(container)
        if img_store is not None:
            old_img = img_store.get(key)
            if old_img:
                try:
                    old_img.delete()
                except Exception:
                    pass
        else:
            old_img = None

        img = lv.image(container)
        img.set_src(img_dsc)
        
        # Use LVGL's native scaling (hardware-accelerated, much faster than CPU resize)
        try:
            img.set_scale(scale_factor)
        except Exception:
            self.logger.debug("set_scale() not available, trying set_zoom()")
            try:
                img.set_zoom(scale_factor)
            except Exception:
                self.logger.debug("set_zoom() not available, falling back to size")
                pass
        
        try:
            img.center()
        except Exception:
            self.logger.info("Icon image center() failed, skipping alignment")
            pass

        # Match icon background to container to simulate transparency for RGB565 icons
        try:
            bg_color = container.get_style_bg_color(0)
            img.set_style_bg_color(bg_color, 0)
            img.set_style_bg_opa(lv.OPA.COVER, 0)
        except Exception:
            pass

        if img_store is not None:
            img_store[key] = img
        if dsc_store is not None:
            dsc_store[key] = img_dsc
        if data_store is not None and img_data:
            data_store[key] = img_data

        self.logger.debug(f"Icon set for {sprite_path} (target={target}, scale={scale_factor}, key={key})")
        return img
    
    def show_error(self, message, duration_ms=3000):
        """
        Show temporary error message overlay.
        
        Args:
            message: Error message text
            duration_ms: How long to show (0 = until dismissed)
        """
        # Simple error label in center of screen
        error_label = lv.label(self.screen)
        error_label.set_text(f"Error: {message}")
        error_label.center()
        
        # Auto-hide after duration
        if duration_ms > 0:
            # Note: In real implementation, use lv.timer or similar
            # For now, just log it
            self.logger.error(f"Error displayed: {message}")
