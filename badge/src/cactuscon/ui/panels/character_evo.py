"""Evolution panel - shows evolution progression and allows evolving."""

import lvgl as lv
import time

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.utils import Logger
from cactuscon import config
from cactuscon.game.engine.characters import (
    XP_BASE_LEVEL,
    EVOLVE_REQUIRED_LEVEL,
    FORM_STAGE_NAMES,
    get_character,
    get_evolution_tree,
    get_current_form_index,
    set_current_form_index,
    get_player_pack,
    get_total_xp_for_level,
    get_xp_for_level,
    get_creature_stats,
    can_evolve,
)
from cactuscon.game.engine.moves import get_move
from cactuscon.prefs import prefs

logger = Logger(config.LOG_LEVEL)


class CharacterEvoPanel(BasePanel):
    """Standalone evolution details panel."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.character_id = getattr(config, "PLAYER_CHARACTER_ID", "deeno")
        self.character_name = "Unknown"
        self.level = 1
        self.xp_total = 0
        self.xp_into_level = 0
        self.xp_needed = XP_BASE_LEVEL
        self._evo_image_cache = {}
        self._default_tint = lv.color_hex(0x666666)
        # Deferred loading state for form images
        self._deferred_forms = []
        self._deferred_current_form_idx = 0
        self._forms_loaded = False

    def create_ui(self):
        self._load_character_data()
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        header = lv.label(self.screen)
        header.set_text("Evolution")
        header.set_style_text_color(lv.color_hex(0x00ff00), 0)
        header.align(lv.ALIGN.TOP_LEFT, 10, 8)
        self.ui_elements["header"] = header

        back_btn = self.create_button(self.screen, "Back", width=60, height=26)
        back_btn.align(lv.ALIGN.TOP_RIGHT, -10, 6)
        back_btn.add_event_cb(self.on_back_pressed, lv.EVENT.CLICKED, None)
        self.ui_elements["back_btn"] = back_btn

        stats_row = lv.obj(self.screen)
        stats_row.set_size(300, 40)
        stats_row.set_pos(10, 40)
        stats_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        stats_row.set_style_pad_column(10, 0)
        stats_row.set_style_bg_opa(lv.OPA.TRANSP, 0)
        stats_row.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["stats_row"] = stats_row

        lvl = lv.label(stats_row)
        lvl.set_text("Lv.1")
        lvl.set_style_text_color(lv.color_hex(0x00ff00), 0)
        self.ui_elements["level"] = lvl

        xp = lv.label(stats_row)
        xp.set_text("XP 0/1000")
        xp.set_style_text_color(lv.color_hex(0xAAAAAA), 0)
        self.ui_elements["xp"] = xp

        forms_row = lv.obj(self.screen)
        forms_row.set_size(300, 90)
        forms_row.set_pos(10, 90)
        if hasattr(lv.FLEX_FLOW, "ROW_WRAP"):
            forms_row.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)
        else:
            forms_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        # forms_row.set_style_pad_column(6, 0)
        forms_row.set_style_bg_opa(lv.OPA.TRANSP, 0)
        forms_row.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["forms_row"] = forms_row

        form_slots = []
        for i in range(3):
            slot = lv.button(forms_row)
            slot.set_size(84, 72)
            slot.set_style_radius(4, 0)
            slot.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
            slot.set_style_border_color(lv.color_hex(0x333333), 0)
            slot.set_style_border_width(1, 0)
            slot.set_style_pad_all(4, 0)
            slot.remove_flag(lv.obj.FLAG.SCROLLABLE)

            img = lv.image(slot)
            img.set_pos(10, 6)
            img.set_size(48, 48)
            img.set_style_bg_opa(lv.OPA.TRANSP, 0)

            label = lv.label(slot)
            label.set_text(FORM_STAGE_NAMES[i] if i < len(FORM_STAGE_NAMES) else f"Form {i+1}")
            label.set_style_text_color(lv.color_hex(0x777777), 0)
            label.align(lv.ALIGN.BOTTOM_MID, 0, 0)

            def _tap(evt, idx=i):
                self._on_form_tapped(idx)

            slot.add_event_cb(_tap, lv.EVENT.CLICKED, None)
            form_slots.append({"btn": slot, "img": img, "label": label})
        self.ui_elements["form_slots"] = form_slots

        bottom_row = lv.obj(self.screen)
        bottom_row.set_size(300, 40)
        bottom_row.set_pos(10, 190)
        bottom_row.set_flex_flow(lv.FLEX_FLOW.ROW)
        bottom_row.set_flex_align(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        bottom_row.set_style_bg_opa(lv.OPA.TRANSP, 0)
        bottom_row.remove_flag(lv.obj.FLAG.SCROLLABLE)
        self.ui_elements["bottom_row"] = bottom_row

        status = lv.label(bottom_row)
        status.set_text("Progress toward next form")
        status.set_style_text_color(lv.color_hex(0xAAAAAA), 0)
        self.ui_elements["status"] = status

        evo_btn = self.create_button(bottom_row, "Evolve", width=90, height=30)
        evo_btn.add_event_cb(self._on_evolve_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements["evo_btn"] = evo_btn

        self._refresh_panel()

    def on_show(self):
        """Show panel immediately with spinner, defer loading to update()."""
        logger.debug("[CHAREVO] on_show() - loading character data and showing spinner")
        self._load_character_data()
        # Show spinner while deferring form image loads
        self.show_spinner("Loading evolution data...")
        # Prepare deferred loading
        self._deferred_forms, self._deferred_current_form_idx = self._get_evo_state()
        self._forms_loaded = False

    def update(self):
        """Load form images one at a time to keep UI responsive."""
        if self._forms_loaded:
            return
        
        # Load one form image per update() call
        for idx, form in enumerate(self._deferred_forms):
            key = form.get("sprite_path") or form.get("id")
            if key in self._evo_image_cache:
                # Already loaded, skip
                continue
            
            # Load this form's image
            form_name = form.get('name', f'Form {idx+1}')
            logger.debug(f"[CHAREVO] Loading form image: {form_name}")
            self._get_form_image_descriptor(form)
            # Load one form per update, return to keep responsive
            return
        
        # All forms loaded
        self._forms_loaded = True
        logger.debug("[CHAREVO] All form images loaded, hiding spinner")
        self.hide_spinner()
        self._refresh_panel()

    # --- internal helpers ---

    def _load_character_data(self):
        """Load character prefs (id, level, xp) from NVS using per-creature tracking."""
        # Get active character from player pack
        pack = get_player_pack(prefs)
        character_id = pack.get("active_character", "")
        
        # Fallback to config if no active character
        if not character_id:
            character_id = getattr(config, "PLAYER_CHARACTER_ID", None) or ""
        
        # Get per-creature level/XP stats
        creature_stats = get_creature_stats(prefs, character_id)
        level = creature_stats['level']
        xp_total = creature_stats['xp']

        self.character_id = character_id
        self.level = level
        self.xp_total = xp_total
        self.xp_needed = get_xp_for_level(level)
        xp_start = get_total_xp_for_level(level)
        self.xp_into_level = max(0, xp_total - xp_start)
        self.character_name = get_character(character_id).name if get_character(character_id) else "Unknown"
        self._evo_image_cache = {}

    def _refresh_panel(self):
        forms, current_idx = self._get_evo_state()

        lvl = self.ui_elements.get("level")
        xp = self.ui_elements.get("xp")
        if lvl:
            lvl.set_text(f"Lv.{self.level}")
        if xp:
            if self.level >= EVOLVE_REQUIRED_LEVEL:
                xp.set_text("XP - / -")
            else:
                xp.set_text(f"XP {self.xp_into_level}/{self.xp_needed}")

        form_slots = self.ui_elements.get("form_slots", [])
        for idx, slot in enumerate(form_slots):
            btn = slot["btn"]
            img = slot["img"]
            label = slot["label"]
            form = forms[idx] if idx < len(forms) else None
            name = form.get("name", f"Form {idx+1}") if form else f"Form {idx+1}"
            label.set_text(name)

            dsc = self._get_form_image_descriptor(form) if form else None
            if dsc:
                try:
                    img.set_src(dsc)
                    # Apply LVGL scaling from cache
                    key = form.get("sprite_path") or form.get("id")
                    cache_entry = self._evo_image_cache.get(key)
                    if cache_entry and cache_entry.get("scale"):
                        try:
                            img.set_scale(cache_entry["scale"])
                        except Exception:
                            try:
                                img.set_zoom(cache_entry["scale"])
                            except Exception:
                                pass
                    img.center()
                    img.remove_flag(lv.obj.FLAG.HIDDEN)
                except Exception as e:
                    self.logger.debug(f"Set evo img src failed: {e}")
            else:
                img.add_flag(lv.obj.FLAG.HIDDEN)

            if idx == current_idx:
                btn.set_style_bg_color(lv.color_hex(0x1f4a1f), 0)
                btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
                label.set_style_text_color(lv.color_hex(0x00ff00), 0)
                self._set_image_tint(img, None, lv.OPA.TRANSP)
            else:
                btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
                btn.set_style_border_color(lv.color_hex(0x333333), 0)
                label.set_style_text_color(lv.color_hex(0x777777), 0)
                self._set_image_tint(img, self._default_tint, lv.OPA._70)

        status = self.ui_elements.get("status")
        evo_btn = self.ui_elements.get("evo_btn")
        if status and evo_btn:
            if current_idx >= 2:
                status.add_flag(lv.obj.FLAG.HIDDEN)
                evo_btn.add_flag(lv.obj.FLAG.HIDDEN)
            elif self.level >= EVOLVE_REQUIRED_LEVEL:
                status.remove_flag(lv.obj.FLAG.HIDDEN)
                evo_btn.remove_flag(lv.obj.FLAG.HIDDEN)
                status.set_text(f"Ready to evolve! (Lv.{EVOLVE_REQUIRED_LEVEL})")
                self._set_enabled(evo_btn, True)
            else:
                status.remove_flag(lv.obj.FLAG.HIDDEN)
                evo_btn.remove_flag(lv.obj.FLAG.HIDDEN)
                needed = max(0, EVOLVE_REQUIRED_LEVEL - self.level)
                status.set_text(f"Gain {needed} more level(s)")
                self._set_enabled(evo_btn, False)

    def _get_evo_state(self):
        forms = get_evolution_tree(self.character_id)
        current_idx = get_current_form_index(prefs, self.character_id)
        if current_idx >= len(forms):
            current_idx = max(0, len(forms) - 1)
        return forms, current_idx

    def _get_form_image_descriptor(self, form):
        if not form:
            return None
        key = form.get("sprite_path") or form.get("id")
        if key in self._evo_image_cache:
            entry = self._evo_image_cache.get(key)
            return entry.get("dsc") if entry else None
        path = form.get("sprite_path")
        if not path:
            self._evo_image_cache[key] = None
            return None
        meta = form.get("sprite_meta") or {}
        result = self._load_icon_descriptor(
            path, sprite_meta=meta, target_size=48
        )
        if not result or not result[0]:
            self._evo_image_cache[key] = None
            return None
        img_dsc, img_data, scale_factor = result
        self._evo_image_cache[key] = {"dsc": img_dsc, "data": img_data, "scale": scale_factor}
        return img_dsc

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

    def _fit_form_image(self, img, form, target_size):
        if not img:
            return
        try:
            img.center()
        except Exception:
            pass

    def _set_enabled(self, obj, enabled):
        if not obj:
            return
        try:
            if hasattr(lv.obj, "FLAG") and hasattr(lv.obj.FLAG, "DISABLED"):
                if enabled:
                    obj.remove_flag(lv.obj.FLAG.DISABLED)
                else:
                    obj.add_flag(lv.obj.FLAG.DISABLED)
                return
        except Exception as e:
            self.logger.debug(f"Flag disable fallback hit: {e}")
        try:
            if hasattr(lv, "STATE") and hasattr(lv.STATE, "DISABLED"):
                if enabled:
                    obj.remove_state(lv.STATE.DISABLED)
                else:
                    obj.add_state(lv.STATE.DISABLED)
        except Exception as e:
            self.logger.debug(f"State disable fallback hit: {e}")

    def _show_modal(self, title, lines):
        overlay = self.ui_elements.get("modal")
        if not overlay:
            overlay = lv.obj(self.screen)
            overlay.set_size(lv.pct(100), lv.pct(100))
            overlay.set_style_bg_color(lv.color_hex(0x000000), 0)
            overlay.set_style_bg_opa(lv.OPA._60, 0)
            overlay.remove_flag(lv.obj.FLAG.SCROLLABLE)
            overlay.add_flag(lv.obj.FLAG.HIDDEN)
            self.ui_elements["modal"] = overlay

            box = lv.obj(overlay)
            box.set_size(240, 160)
            box.align(lv.ALIGN.CENTER, 0, 0)
            box.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
            box.set_style_border_color(lv.color_hex(0x00ff00), 0)
            box.set_style_border_width(1, 0)
            box.set_style_radius(6, 0)
            box.set_style_pad_all(8, 0)
            box.remove_flag(lv.obj.FLAG.SCROLLABLE)
            self.ui_elements["modal_box"] = box

            title_lbl = lv.label(box)
            title_lbl.set_style_text_color(lv.color_hex(0x00ff00), 0)
            title_lbl.align(lv.ALIGN.TOP_LEFT, 0, 0)
            self.ui_elements["modal_title"] = title_lbl

            desc_container = lv.obj(box)
            desc_container.set_size(220, 100)
            desc_container.align(lv.ALIGN.TOP_LEFT, 0, 18)
            desc_container.set_scroll_dir(lv.DIR.VER)
            desc_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.AUTO)
            desc_container.set_style_bg_opa(lv.OPA.TRANSP, 0)
            desc_container.set_style_border_width(0, 0)
            desc_container.set_style_pad_all(0, 0)
            self.ui_elements["modal_desc_container"] = desc_container

            body = lv.label(desc_container)
            body.set_width(lv.pct(100))
            if hasattr(lv.label, "LONG"):
                body.set_long_mode(lv.label.LONG.WRAP)
            body.align(lv.ALIGN.TOP_LEFT, 0, 0)
            body.set_style_text_color(lv.color_hex(0xDDDDDD), 0)
            self.ui_elements["modal_body"] = body

            close = self.create_button(box, "Close", width=70, height=24)
            close.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
            close.add_event_cb(self._close_modal, lv.EVENT.CLICKED, None)
            self.ui_elements["modal_close"] = close

        overlay.remove_flag(lv.obj.FLAG.HIDDEN)
        self.ui_elements["modal_title"].set_text(title)
        self.ui_elements["modal_body"].set_text("\n".join(lines))
        desc_container = self.ui_elements.get("modal_desc_container")
        if desc_container:
            try:
                desc_container.scroll_to_y(0, lv.ANIM.OFF)
            except Exception:
                pass

    def _close_modal(self, event=None):
        overlay = self.ui_elements.get("modal")
        if overlay:
            overlay.add_flag(lv.obj.FLAG.HIDDEN)

    # --- events ---

    def _on_form_tapped(self, idx):
        forms, _ = self._get_evo_state()
        if idx >= len(forms):
            return
        form = forms[idx]
        move_names = []
        for mid in form.get("moves", []):
            mv = get_move(mid)
            move_names.append(mv.name if mv else f"Move {mid}")
        lines = [
            form.get("bio", ""),
            f"Moves: {', '.join(move_names) or 'Unknown'}",
            f"Strengths: {form.get('strengths', '')}",
            f"Weaknesses: {form.get('weaknesses', '')}",
        ]
        self._show_modal(form.get("name", "Form"), lines)

    def _on_evolve_clicked(self, event):
        """Handle evolution button click - use new per-creature tracking."""
        forms, current_idx = self._get_evo_state()
        if current_idx >= 2:
            self.show_error("Already final form")
            return
        if self.level < EVOLVE_REQUIRED_LEVEL:
            self.show_error(f"Need Lv.{EVOLVE_REQUIRED_LEVEL} to evolve")
            return
        next_idx = current_idx + 1
        next_form = forms[next_idx] if next_idx < len(forms) else None
        if not next_form:
            self.show_error("No next evolution form")
            return
        
        next_id = next_form.get("id")
        
        # Use can_evolve for a proper check (checks owned, level, etc.)
        evo_check = can_evolve(prefs, self.character_id)
        if not evo_check.get('can_evolve'):
            self.show_error(evo_check.get('reason') or "Cannot evolve")
            return
        
        # Show spinner while loading evolution animation panel
        self.show_spinner("Evolving...")
        
        # Hand off to evolution animation panel
        if self.game_ui:
            self.game_ui.pending_evolution = {"old_id": self.character_id}
            self.game_ui.show_panel("evolution_anim")
