"""Evolution animation panel - shows evolution animation and applies evolution changes."""

import lvgl as lv
import time
import gc

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.ui.sprites import LVGLImage, evict_sprite_cache
from cactuscon.utils import Logger
from cactuscon import config
from cactuscon.game.engine.characters import (
    get_character,
    get_player_pack,
    get_creature_stats,
    can_evolve,
    evolve_creature,
    EVOLVE_REQUIRED_LEVEL,
)
from cactuscon.prefs import prefs

# Initialize logger for timing logs
logger = Logger(config.LOG_LEVEL)


class EvolutionAnimPanel(BasePanel):
    """Animated evolution sequence panel."""

    # Loading states for deferred asset loading
    LOAD_STATE_INIT = 0
    LOAD_STATE_CONTEXT = 1
    LOAD_STATE_OLD_SPRITE = 2
    LOAD_STATE_EVOLVE = 3
    LOAD_STATE_NEW_SPRITE = 4
    LOAD_STATE_READY = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_id = None
        self._new_id = None
        self._old_name = ""
        self._new_name = ""
        self._old_sprite = None
        self._new_sprite = None
        self._old_lvgl_image = None  # LVGLImage reference (keep alive)
        self._new_lvgl_image = None  # LVGLImage reference (keep alive)
        self._sprite_img = None
        self._status_label = None
        self._back_btn = None
        self._base_sprite_y = 0
        self._phase = "idle"
        self._phase_start_ms = 0
        self._recolor_start_ms = 0
        self._swap_ms = 0
        self._fade_done_ms = 0
        self._recolor_anim = None
        self._jump_anim = None
        self._white = lv.color_hex(0xFFFFFF)
        # Deferred loading state
        self._load_state = self.LOAD_STATE_INIT
        self._load_error = None

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        sprite = lv.image(self.screen)
        sprite.set_style_bg_opa(lv.OPA.TRANSP, 0)
        sprite.align(lv.ALIGN.CENTER, 0, -50)
        sprite.add_flag(lv.obj.FLAG.HIDDEN)  # Hidden until sprite loads
        self.ui_elements["sprite"] = sprite
        self._sprite_img = sprite

        status = lv.label(self.screen)
        status.set_text("Loading...")
        status.set_style_text_color(lv.color_hex(0xDDDDDD), 0)
        status.align(lv.ALIGN.BOTTOM_MID, 0, -40)
        self.ui_elements["status"] = status
        self._status_label = status

        back_btn = self.create_button(self.screen, "Back", width=70, height=28)
        back_btn.align(lv.ALIGN.BOTTOM_MID, 0, -4)
        back_btn.add_event_cb(self._on_back, lv.EVENT.CLICKED, None)
        back_btn.add_flag(lv.obj.FLAG.HIDDEN)
        self.ui_elements["back_btn"] = back_btn
        self._back_btn = back_btn

    def on_show(self):
        """Show panel immediately with spinner, defer loading to update()."""
        logger.debug("[EVOANIM] on_show() - showing panel with spinner")
        self._reset_state()
        # Start deferred loading - will proceed in update() one step at a time
        self._load_state = self.LOAD_STATE_INIT
        self._load_error = None
        # Show base panel spinner
        self.show_spinner("Loading evolution...")
        if self._sprite_img:
            self._sprite_img.add_flag(lv.obj.FLAG.HIDDEN)
        if self._status_label:
            self._status_label.set_text("Loading...")
        logger.debug("[EVOANIM] on_show() complete - spinner visible, loading deferred")

    def update(self):
        """Handle deferred loading one step at a time, then animation phases."""
        # Deferred loading state machine
        if self._load_state < self.LOAD_STATE_READY:
            self._process_load_step()
            return

        # Check for load error
        if self._load_error:
            return

        # Start animation on first update after loading complete
        if getattr(self, '_animation_ready', False) and not getattr(self, '_animation_started', False):
            self._animation_started = True
            self._start_animation_sequence()
            logger.info(f"[EVOANIM] Animation started, phase={self._phase}")
            return
        
        if self._phase == "idle" or self._phase == "done":
            return

        now = time.ticks_ms()
        
        # Phase transitions based on elapsed time with proper delays
        if self._phase == "jump":
            elapsed = time.ticks_diff(now, self._phase_start_ms)
            # Jump for 2.5 seconds to let the bouncing be visible
            if elapsed >= 2500:
                logger.info(f"[EVOANIM] phase transition: jump -> swap (elapsed={elapsed}ms)")
                # Skip the white effect - just swap the sprite directly
                self._swap_to_new_sprite()
                self._phase = "hold"
                self._phase_start_ms = now
            return

        if self._phase == "hold":
            # Hold the new sprite for a moment before finishing
            elapsed = time.ticks_diff(now, self._phase_start_ms)
            if elapsed >= 800:
                logger.info(f"[EVOANIM] phase transition: hold -> done (elapsed={elapsed}ms)")
                self._finish_sequence()

    def _process_load_step(self):
        """Process one loading step per update() call to keep UI responsive."""
        
        
        if self._load_state == self.LOAD_STATE_INIT:
            logger.info("[EVOANIM] Load step: INIT -> CONTEXT")
            self._load_state = self.LOAD_STATE_CONTEXT
            return
            
        if self._load_state == self.LOAD_STATE_CONTEXT:
            _t0 = time.ticks_ms()
            self._load_evolution_context()
            logger.info(f"[EVOANIM] Load step: CONTEXT complete in {time.ticks_diff(time.ticks_ms(), _t0)}ms")
            logger.info(f"[EVOANIM] old_id={self._old_id}, old_name={self._old_name}")
            self._load_state = self.LOAD_STATE_OLD_SPRITE
            return
            
        if self._load_state == self.LOAD_STATE_OLD_SPRITE:
            _t0 = time.ticks_ms()
            self._load_old_sprite()
            logger.info(f"[EVOANIM] Load step: OLD_SPRITE complete in {time.ticks_diff(time.ticks_ms(), _t0)}ms")
            self._load_state = self.LOAD_STATE_EVOLVE
            return
            
        if self._load_state == self.LOAD_STATE_EVOLVE:
            _t0 = time.ticks_ms()
            self._apply_evolution_changes()
            logger.info(f"[EVOANIM] Load step: EVOLVE complete in {time.ticks_diff(time.ticks_ms(), _t0)}ms")
            logger.info(f"[EVOANIM] new_id={self._new_id}, new_name={self._new_name}")
            if self._load_error:
                return  # Error already shown
            self._load_state = self.LOAD_STATE_NEW_SPRITE
            return
            
        if self._load_state == self.LOAD_STATE_NEW_SPRITE:
            _t0 = time.ticks_ms()
            self._load_new_sprite()
            logger.info(f"[EVOANIM] Load step: NEW_SPRITE complete in {time.ticks_diff(time.ticks_ms(), _t0)}ms")
            # Loading complete - transition to ready state
            self._finalize_loading()
            self._load_state = self.LOAD_STATE_READY

    def _finalize_loading(self):
        """Hide spinner, show sprite, prepare for animation."""
        logger.info("[EVOANIM] _finalize_loading - hiding spinner, showing sprite")
        # Hide base panel spinner
        self.hide_spinner()
        # Show sprite
        if self._sprite_img:
            self._sprite_img.remove_flag(lv.obj.FLAG.HIDDEN)
            # Re-capture base Y now that sprite is visible (positioning may have changed)
            self._base_sprite_y = self._sprite_img.get_y()
            logger.debug(f"[EVOANIM] Sprite visible, base_y recaptured as {self._base_sprite_y}")
        # Update status
        if self._status_label:
            self._status_label.set_text("Evolving...")
        # Ready for animation
        self._animation_ready = True
        self._animation_started = False

    # --- internal helpers ---

    def _reset_state(self):
        self._phase = "idle"
        self._phase_start_ms = 0
        self._recolor_start_ms = 0
        self._swap_ms = 0
        self._fade_done_ms = 0
        self._old_id = None
        self._new_id = None
        self._old_name = ""
        self._new_name = ""
        self._old_sprite = None
        self._new_sprite = None
        self._old_lvgl_image = None  # Release LVGLImage reference
        self._new_lvgl_image = None  # Release LVGLImage reference
        self._load_state = self.LOAD_STATE_INIT
        self._load_error = None
        self._animation_ready = False
        self._animation_started = False
        if self._status_label:
            self._status_label.set_text("Loading...")
        if self._back_btn:
            self._back_btn.add_flag(lv.obj.FLAG.HIDDEN)

    def _load_evolution_context(self):
        ctx = None
        if self.game_ui:
            ctx = getattr(self.game_ui, "pending_evolution", None)
        if isinstance(ctx, dict):
            self._old_id = ctx.get("old_id")
        if self.game_ui and hasattr(self.game_ui, "pending_evolution"):
            self.game_ui.pending_evolution = None

        if not self._old_id:
            # Fallback to active creature if no context
            pack = get_player_pack(prefs)
            self._old_id = pack.get("active_character", "")

        if not self._old_id:
            self._old_id = ""

        old_char = get_character(self._old_id)
        self._old_name = old_char.name if old_char else "Unknown"
    
    def _prepare_sprite_memory(self, keep_paths, phase):
        """
        Reduce sprite-memory pressure before loading evolution images.

        Keeps required sprite paths pinned while evicting stale/non-critical cache
        entries, then runs GC to reduce fragmentation before LVGL image creation.
        """
        keep = [p for p in (keep_paths or []) if p]
        try:
            evict_sprite_cache(
                keep_paths=keep,
                max_age_ms=None,
                min_free_percent=25,
                preserve_preloaded=True,
            )
        except Exception as e:
            logger.debug(f"[EVOANIM] Cache eviction skipped ({phase}): {e}")
        try:
            gc.collect()
        except Exception:
            pass

    def _load_old_sprite(self):
        """Load old sprite using LVGLImage (fast, uses cache)."""
        if not self._sprite_img:
            return
        old_char = get_character(self._old_id)
        if not old_char:
            return
        
        try:
            self._prepare_sprite_memory([old_char.sprite_path], "old_sprite")
            meta = old_char.extra.get("sprite_meta", {})
            self._old_lvgl_image = LVGLImage(
                old_char.sprite_path,
                frame_width=meta.get("frame_width"),
                frame_height=meta.get("frame_height"),
                frames_per_row=meta.get("frames_per_row", meta.get("frames_per_line", 1)),
                num_frames=meta.get("num_frames", meta.get("frames", 1)),
            )
            # Get the LVGL descriptor for frame 0
            dsc = self._old_lvgl_image.get_lvgl_src(0)
            if dsc:
                self._old_sprite = dsc
                self._sprite_img.set_src(dsc)
                try:
                    self._sprite_img.align(lv.ALIGN.CENTER, 0, -50)
                except Exception:
                    pass
                self._base_sprite_y = self._sprite_img.get_y()
        except Exception as e:
            logger.error(f"[EVOANIM] Failed to load old sprite: {e}")

    def _apply_evolution_changes(self):
        if not self._old_id:
            self._show_error("No creature selected")
            return

        stats = get_creature_stats(prefs, self._old_id)
        level = stats.get("level", 1)
        logger.info(f"[EVOANIM] _apply_evolution_changes: old_id={self._old_id}, level={level}")
        evo_check = can_evolve(prefs, self._old_id)
        can_evo = evo_check.get('can_evolve', False)
        reason = evo_check.get('reason', '')
        logger.info(f"[EVOANIM] can_evolve result: can_evo={can_evo}, reason={reason}")
        if not can_evo:
            self._show_error(reason or f"Need Lv.{EVOLVE_REQUIRED_LEVEL} to evolve")
            return

        logger.info(f"[EVOANIM] Calling evolve_creature with battle_manager={self.battle_manager is not None}")
        result = evolve_creature(prefs, self._old_id, battle_manager=self.battle_manager)
        logger.info(f"[EVOANIM] evolve_creature result: {result}")
        if not result or not result.get("success"):
            self._show_error(result.get("reason", "Evolution failed") if result else "Evolution failed")
            return

        self._new_id = result.get("new_form")
        new_char = get_character(self._new_id)
        self._new_name = new_char.name if new_char else "Unknown"

    def _load_new_sprite(self):
        """Load new sprite using LVGLImage (fast, uses cache)."""
        if not self._new_id or not self._sprite_img:
            return
        new_char = get_character(self._new_id)
        if not new_char:
            return
        
        try:
            old_char = get_character(self._old_id) if self._old_id else None
            keep_paths = [new_char.sprite_path]
            if old_char and getattr(old_char, "sprite_path", None):
                keep_paths.append(old_char.sprite_path)
            self._prepare_sprite_memory(keep_paths, "new_sprite")
            meta = new_char.extra.get("sprite_meta", {})
            self._new_lvgl_image = LVGLImage(
                new_char.sprite_path,
                frame_width=meta.get("frame_width"),
                frame_height=meta.get("frame_height"),
                frames_per_row=meta.get("frames_per_row", meta.get("frames_per_line", 1)),
                num_frames=meta.get("num_frames", meta.get("frames", 1)),
            )
            # Get the LVGL descriptor for frame 0
            dsc = self._new_lvgl_image.get_lvgl_src(0)
            if dsc:
                self._new_sprite = dsc
        except Exception as e:
            logger.error(f"[EVOANIM] Failed to load new sprite: {e}")

    def _start_animation_sequence(self):
        if not self._sprite_img:
            self._show_error("Missing sprite")
            return

        # Start jump animation
        self._start_jump_animation()

        now = time.ticks_ms()
        self._phase = "jump"
        self._phase_start_ms = now
        # Phase transitions are now handled in update() based on elapsed time

    def _start_jump_animation(self):
        if not self._sprite_img:
            return
        try:
            anim = lv.anim_t()
            anim.init()
            # Much larger jump (40px instead of 18px) to be clearly visible
            anim.set_values(self._base_sprite_y, self._base_sprite_y - 40)
            # Slower timing (400ms per bounce) so user can see it
            anim.set_duration(400)
            anim.set_repeat_count(5)  # 5 full bounces (each 400ms)
            anim.set_path_cb(lv.anim_t.path_ease_in_out)
            # Use custom exec cb for lambda
            anim.set_custom_exec_cb(lambda a, val: self._sprite_img.set_y(val))
            anim.start()
            self._jump_anim = anim
            logger.debug(f"[EVOANIM] Jump animation started: base_y={self._base_sprite_y}, jump to {self._base_sprite_y - 40}")
        except Exception as e:
            self.logger.debug(f"Jump anim failed: {e}")
            logger.error(f"[EVOANIM] Jump animation FAILED: {e}")

    def _start_recolor_to_white(self):
        self._set_image_tint(self._sprite_img, self._white, lv.OPA.TRANSP)
        self._animate_recolor(0, 255, 500)

    def _start_recolor_to_color(self):
        self._animate_recolor(255, 0, 500)

    def _animate_recolor(self, start, end, duration):
        if not self._sprite_img:
            return
        try:
            anim = lv.anim_t()
            anim.init()
            anim.set_values(start, end)
            anim.set_duration(duration)
            anim.set_path_cb(lv.anim_t.path_linear)
            # Use custom exec cb for lambda
            anim.set_custom_exec_cb(lambda a, val: self._set_image_tint(self._sprite_img, self._white, val))
            anim.start()
            self._recolor_anim = anim
        except Exception as e:
            self.logger.debug(f"Recolor anim failed: {e}")
            self._set_image_tint(self._sprite_img, self._white, end)

    def _swap_to_new_sprite(self):
        if not self._sprite_img or not self._new_sprite:
            return
        try:
            self._sprite_img.set_src(self._new_sprite)
            # Align new sprite and restore to base Y position (same as old form)
            try:
                self._sprite_img.align(lv.ALIGN.CENTER, 0, -50)
                # Restore Y position to match old form baseline
                self._sprite_img.set_y(self._base_sprite_y)
            except Exception:
                pass
        except Exception as e:
            self.logger.debug(f"Swap sprite failed: {e}")

    def _finish_sequence(self):

        if self._status_label:
            self._status_label.set_text(
                f"{self._old_name} evolved into {self._new_name}!"
            )
        if self._back_btn:
            self._back_btn.remove_flag(lv.obj.FLAG.HIDDEN)
        self._phase = "done"

    def _set_image_tint(self, img, color, opa):
        if not img:
            return
        try:
            if color is not None:
                if hasattr(img, "set_style_img_recolor"):
                    img.set_style_img_recolor(color, 0)
                elif hasattr(img, "set_style_image_recolor"):
                    img.set_style_image_recolor(color, 0)
            if opa is not None:
                if hasattr(img, "set_style_img_recolor_opa"):
                    img.set_style_img_recolor_opa(opa, 0)
                elif hasattr(img, "set_style_image_recolor_opa"):
                    img.set_style_image_recolor_opa(opa, 0)
        except Exception as e:
            self.logger.debug(f"Image tint failed: {e}")

    def _show_error(self, message):
        logger.debug(f"[EVOANIM] _show_error: {message}")
        self._load_error = message
        # Hide spinner on error
        self.hide_spinner()
        if self._status_label:
            self._status_label.set_text(message)
        if self._back_btn:
            self._back_btn.remove_flag(lv.obj.FLAG.HIDDEN)
        self._phase = "done"

    def _on_back(self, event=None):
        logger.debug("[EVOANIM] _on_back() called")
        if self.game_ui:
            self.game_ui.show_panel("character")
