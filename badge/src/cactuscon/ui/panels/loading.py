"""Loading panel - Minimal loading state with text only (or banner if available)."""

import lvgl as lv
import uos
from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.ui.sprites import LVGLImage


class LoadingPanel(BasePanel):
    """
    Minimal loading screen with text only.

    Memory optimized: No image loading - just LVGL labels.
    The full hacktarmon sprite was 320x240x2 = 153KB!

    Layout:
        ┌──────────────────────────────┐
        │                              │
        │        CactusCon 14          │
        │                              │
        │           ████               │
        │       (progress bar)         │
        │                              │
        │         Loading...           │
        │                              │
        └──────────────────────────────┘
    """

    def __init__(
        self, screen=None, game_ui=None, battle_manager=None, logger_level=20, **kwargs
    ):
        """Initialize loading panel."""
        super().__init__(screen, game_ui, battle_manager, logger_level, **kwargs)
        self.status_text = "Loading..."
        self.progress = 0  # 0-100

    def create_ui(self):
        """Create minimal loading panel UI."""
        # Set screen background to black
        self.screen.set_style_bg_color(lv.color_black(), 0)

        # Try to load banner image; fall back to text if missing/failed
        banner_loaded = False
        try:
            if uos.stat("/assets/images/banner.rgb565"):
                banner = LVGLImage(
                    "/assets/images/banner.rgb565", frame_height=50, frame_width=300
                )
                container = lv.obj(self.screen)
                container.set_size(300, 50)
                container.set_align(lv.ALIGN.TOP_MID)
                container.set_y(30)
                container.set_style_bg_opa(lv.OPA.TRANSP, 0)
                container.set_style_border_width(0, 0)
                container.remove_flag(lv.obj.FLAG.SCROLLABLE)

                img = lv.image(container)
                img.set_src(banner.get_lvgl_src())
                try:
                    img.set_size(300, 50)
                except Exception:
                    pass
                img.center()

                self.ui_elements["banner_container"] = container
                self.ui_elements["banner_img"] = img
                banner_loaded = True
        except Exception as e:
            self.logger.warning(f"Failed to load banner image: {e}")
            banner_loaded = False

        if not banner_loaded:
            # Title at top - larger text
            title_label = lv.label(self.screen)
            title_label.set_text("CactusCon 14")
            title_label.set_style_text_color(lv.color_hex(0xFFFF00), 0)
            title_label.set_align(lv.ALIGN.TOP_MID)
            title_label.set_y(40)
            self.ui_elements["title_label"] = title_label

            # Subtitle
            subtitle = lv.label(self.screen)
            subtitle.set_text("Hacktarmon Badge")
            subtitle.set_style_text_color(lv.color_hex(0x00FF00), 0)
            subtitle.set_align(lv.ALIGN.TOP_MID)
            subtitle.set_y(60)
            self.ui_elements["subtitle"] = subtitle

        # Simple progress bar (optional visual feedback)
        bar = lv.bar(self.screen)
        bar.set_size(200, 10)
        bar.set_align(lv.ALIGN.CENTER)
        bar.set_value(0, False)  # Start at 0, no animation
        bar.set_style_bg_color(lv.color_hex(0x333333), 0)
        bar.set_style_bg_color(lv.color_hex(0x00FF00), lv.PART.INDICATOR)
        self.ui_elements["progress_bar"] = bar

        # Status label at bottom
        status_label = lv.label(self.screen)
        status_label.set_text(self.status_text)
        status_label.set_style_text_color(lv.color_hex(0x888888), 0)
        status_label.set_align(lv.ALIGN.BOTTOM_MID)
        status_label.set_y(-40)
        self.ui_elements["status_label"] = status_label

    def set_status(self, text, progress=None):
        """
        Update loading status text and optional progress.

        Args:
            text: Status message to display
            progress: Optional progress value 0-100
        """
        self.status_text = text
        if "status_label" in self.ui_elements:
            self.ui_elements["status_label"].set_text(text)

        if progress is not None and "progress_bar" in self.ui_elements:
            self.progress = max(0, min(100, progress))
            self.ui_elements["progress_bar"].set_value(self.progress, False)

    def on_show(self):
        """Called when loading panel is displayed."""
        self.logger.info("Loading panel displayed")

    def on_hide(self):
        """Called when loading panel is hidden."""
        self.logger.debug("Loading panel hidden")
        # Avoid deleting LVGL children during panel transition. On some firmware
        # builds this can stall while another screen/spinner is being shown.
        # Cleanup is deferred to on_cleanup() when the panel is actually unloaded.

    def on_cleanup(self):
        """Free loading-only UI/image resources when panel is unloaded."""
        # Explicitly delete banner image/container to free memory before next panel
        for key in ("banner_img", "banner_container"):
            obj = self.ui_elements.get(key)
            if obj:
                try:
                    obj.delete()
                except Exception:
                    pass
                self.ui_elements.pop(key, None)
        # Drop references to any labels/bars to help GC
        for key in ("title_label", "subtitle", "progress_bar", "status_label"):
            if key in self.ui_elements:
                try:
                    self.ui_elements[key].delete()
                except Exception:
                    pass
                self.ui_elements.pop(key, None)
        
        # Forcefully evict the banner sprite from cache - it's only used during loading
        # and we want to free ~30KB before loading the next panel
        try:
            from cactuscon.ui.sprites import _SPRITE_CACHE
            banner_path = "/assets/images/banner.rgb565"
            if banner_path in _SPRITE_CACHE:
                del _SPRITE_CACHE[banner_path]
                self.logger.debug("Evicted banner sprite from cache")
        except Exception as e:
            self.logger.debug(f"Banner eviction failed: {e}")
        # Let BasePanel cleanup proceed

    def on_back_pressed(self):
        """Back button does nothing during loading."""
        return True  # Handled - don't navigate
