"""CactusCon info and schedule panels (pagination-based)."""

import gc
import uos
import time
import lvgl as lv

from cactuscon.ui.panels.base_panel import BasePanel
from cactuscon.ui.image_utils import create_image_descriptor, load_rgb565_file_into
from cactuscon.utils import mem_info

# Shared selection state
_SELECTED_DAY = None
_SELECTED_MODE = None  # "track" or "timeslot"
_SELECTED_TRACK = None
_SELECTED_TIMESLOT_IDX = 0
_SELECTED_ENTRY = None
_SELECTED_DETAIL_RETURN = None  # panel name to return to


TRACKS_FIXED = ("Track 1", "Track 2", "Track 3", "Workshops")

# Map panel debug toggles (opt-in)
DEBUG_MAP = False
DEBUG_MAP_MEM = False

# Map variants: (name, path, width, height, expected_bytes, scroll_enabled)
MAP_VARIANTS = [
    ("map", "/assets/images/map.rgb565", 320, 414, 264960, True),
    ("map_Z1", "/assets/images/map_Z1.rgb565", 320, 207, 132480, False),
    ("map_Z2", "/assets/images/map_Z2.rgb565", 320, 207, 132480, False),
    ("map_Z3", "/assets/images/map_Z3.rgb565", 320, 207, 132480, False),
]

MAP_BYTES = 320 * 414 * 2

_MAP_BUFFER = None
_MAP_BUFFER_SIZE = 0


def ensure_map_buffer_pinned():
    global _MAP_BUFFER, _MAP_BUFFER_SIZE
    if _MAP_BUFFER is None:
        gc.collect()
        try:
            _MAP_BUFFER = bytearray(MAP_BYTES)
            _MAP_BUFFER_SIZE = MAP_BYTES
            print(f"INFO: [MAP] pinned buffer {MAP_BYTES} bytes")
            if DEBUG_MAP_MEM:
                mem_info("[MAP][MEM] pinned")
        except MemoryError:
            _MAP_BUFFER = None
            _MAP_BUFFER_SIZE = 0
            print(f"ERROR: [MAP] pin buffer failed ({MAP_BYTES} bytes)")
    return _MAP_BUFFER



def _set_selected_day(day):
    global _SELECTED_DAY
    _SELECTED_DAY = day


def _get_selected_day():
    return _SELECTED_DAY


def _set_selected_mode(mode):
    global _SELECTED_MODE
    _SELECTED_MODE = mode


def _get_selected_mode():
    return _SELECTED_MODE


def _set_selected_track(track):
    global _SELECTED_TRACK
    _SELECTED_TRACK = track


def _get_selected_track():
    return _SELECTED_TRACK


def _set_selected_timeslot_idx(idx):
    global _SELECTED_TIMESLOT_IDX
    _SELECTED_TIMESLOT_IDX = idx


def _get_selected_timeslot_idx():
    return _SELECTED_TIMESLOT_IDX


def _set_selected_entry(entry, return_panel=None):
    global _SELECTED_ENTRY, _SELECTED_DETAIL_RETURN
    _SELECTED_ENTRY = entry
    _SELECTED_DETAIL_RETURN = return_panel


def _get_selected_entry():
    return _SELECTED_ENTRY


def _get_detail_return_panel():
    return _SELECTED_DETAIL_RETURN


def _add_back_button(panel, handler):
    btn_back = lv.button(panel.screen)
    btn_back.set_size(60, 30)
    btn_back.align(lv.ALIGN.TOP_RIGHT, -10, 8)
    btn_back.add_event_cb(handler, lv.EVENT.CLICKED, None)
    btn_back.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
    btn_back.set_style_border_color(lv.color_hex(0x00ff00), 0)
    btn_back.set_style_border_width(1, 0)

    label = lv.label(btn_back)
    label.set_text("Back")
    label.set_style_text_color(lv.color_hex(0x00ff00), 0)
    label.center()

    panel.ui_elements['btn_back'] = btn_back
    return btn_back


def _set_button_label(label, text):
    label.set_text(text)

def _create_labeled_button(parent, text, width, height):
    btn = lv.button(parent)
    btn.set_width(width)
    btn.set_height(height)
    btn.set_style_bg_color(lv.color_hex(0x2a2a2a), 0)
    btn.set_style_bg_color(lv.color_hex(0x3a3a3a), lv.STATE.PRESSED)
    btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
    btn.set_style_border_width(1, 0)
    btn.set_style_radius(4, 0)

    label = lv.label(btn)
    label.set_text(text)
    label.center()
    label.set_style_text_color(lv.color_hex(0x00ff00), 0)
    return btn, label


def _set_row_label(label, text, active=True):
    label.set_text(text)
    if active:
        label.set_style_text_color(lv.color_hex(0x00ff00), 0)
    else:
        label.set_style_text_color(lv.color_hex(0x666666), 0)


class CactusConInfoPanel(BasePanel):
    """Info hub panel with Schedule and Map buttons."""

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("CactusCon Info")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        btn_schedule = self.create_button(self.screen, "Schedule", width=200, height=60)
        btn_schedule.align(lv.ALIGN.CENTER, 0, -20)
        btn_schedule.add_event_cb(self._on_schedule_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_schedule'] = btn_schedule

        btn_map = self.create_button(self.screen, "Map", width=200, height=60)
        btn_map.align(lv.ALIGN.CENTER, 0, 55)
        btn_map.add_event_cb(self._on_map_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_map'] = btn_map

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading info...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] cactuscon_info entry")
        mem_info("[MEM] cactuscon_info after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('main_menu')
            return True
        return False

    def _on_schedule_clicked(self, event):
        if self.game_ui:
            self.game_ui.show_panel('schedule_day')

    def _on_map_clicked(self, event):
        if self.game_ui:
            self.game_ui.show_panel('map')


class ScheduleDayPanel(BasePanel):
    """Day selection panel (Friday/Saturday)."""

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Select Day")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        self._day_buttons = []
        self._day_labels = []
        self._day_by_btn = {}

        btn_day_1, label_1 = _create_labeled_button(self.screen, "Friday", width=200, height=60)
        btn_day_1.align(lv.ALIGN.CENTER, 0, -20)
        btn_day_1.add_event_cb(self._on_day_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_day_1'] = btn_day_1
        self._day_buttons.append(btn_day_1)
        self._day_labels.append(label_1)
        self._day_by_btn[id(btn_day_1)] = "Friday"

        btn_day_2, label_2 = _create_labeled_button(self.screen, "Saturday", width=200, height=60)
        btn_day_2.align(lv.ALIGN.CENTER, 0, 55)
        btn_day_2.add_event_cb(self._on_day_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_day_2'] = btn_day_2
        self._day_buttons.append(btn_day_2)
        self._day_labels.append(label_2)
        self._day_by_btn[id(btn_day_2)] = "Saturday"

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading schedule...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] schedule_day entry")

        from cactuscon import schedule_entries

        days = schedule_entries.get_days()
        if len(days) >= 1:
            btn = self.ui_elements['btn_day_1']
            _set_button_label(self._day_labels[0], days[0])
            self._day_by_btn[id(btn)] = days[0]
        if len(days) >= 2:
            btn = self.ui_elements['btn_day_2']
            _set_button_label(self._day_labels[1], days[1])
            self._day_by_btn[id(btn)] = days[1]

        mem_info("[MEM] schedule_day after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('cactuscon_info')
            return True
        return False

    def _on_day_clicked(self, event):
        target = event.get_target_obj()
        day = self._day_by_btn.get(id(target))
        if day is None:
            parent = target.get_parent()
            if parent:
                day = self._day_by_btn.get(id(parent))
        if day is None:
            return
        _set_selected_day(day)
        if self.game_ui:
            self.game_ui.show_panel('schedule_mode')


class ScheduleModePanel(BasePanel):
    """Choose browsing mode (track or timeslot)."""

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Browse Schedule")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        btn_track = self.create_button(self.screen, "By Track", width=200, height=60)
        btn_track.align(lv.ALIGN.CENTER, 0, -20)
        btn_track.add_event_cb(self._on_track_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_track'] = btn_track

        btn_timeslot = self.create_button(self.screen, "By Timeslot", width=200, height=60)
        btn_timeslot.align(lv.ALIGN.CENTER, 0, 55)
        btn_timeslot.add_event_cb(self._on_timeslot_clicked, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_timeslot'] = btn_timeslot

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading options...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] schedule_mode entry")
        mem_info("[MEM] schedule_mode after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('schedule_day')
            return True
        return False

    def _on_track_clicked(self, event):
        _set_selected_mode("track")
        if self.game_ui:
            self.game_ui.show_panel('track_select')

    def _on_timeslot_clicked(self, event):
        _set_selected_mode("timeslot")
        _set_selected_timeslot_idx(0)
        if self.game_ui:
            self.game_ui.show_panel('timeslot_view')


class TrackSelectPanel(BasePanel):
    """Track selection (fixed 4 tracks)."""

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Select Track")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        self.track_buttons = []
        # 2x2 grid buttons
        btn_w = 140
        btn_h = 60
        x_offset = 75
        y_top = 60
        y_bottom = 135

        positions = [(-x_offset, y_top), (x_offset, y_top), (-x_offset, y_bottom), (x_offset, y_bottom)]
        self._track_by_btn = {}
        for i, track in enumerate(TRACKS_FIXED):
            btn, label = _create_labeled_button(self.screen, track, width=btn_w, height=btn_h)
            btn.align(lv.ALIGN.TOP_MID, positions[i][0], positions[i][1])
            btn.add_event_cb(self._on_track_clicked, lv.EVENT.CLICKED, None)
            self._track_by_btn[id(btn)] = track
            self.track_buttons.append(btn)

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading tracks...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] track_select entry")
        mem_info("[MEM] track_select after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('schedule_mode')
            return True
        return False

    def _on_track_clicked(self, event):
        target = event.get_target_obj()
        track = self._track_by_btn.get(id(target))
        if track is None:
            parent = target.get_parent()
            if parent:
                track = self._track_by_btn.get(id(parent))
        if track is None:
            return
        _set_selected_track(track)
        if self.game_ui:
            self.game_ui.show_panel('track_talk_list')


class TrackTalkListPanel(BasePanel):
    """Paginated list of talks for a selected track/day."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page_index = 0
        self.rows = []
        self.row_labels = []
        self.row_entries = [None, None, None, None]

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Track Talks")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        # Rows (4)
        self.rows = []
        self.row_labels = []
        y_start = 50
        row_h = 36
        row_gap = 6

        for i in range(4):
            btn = lv.button(self.screen)
            btn.set_size(300, row_h)
            btn.align(lv.ALIGN.TOP_MID, 0, y_start + i * (row_h + row_gap))
            btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
            btn.set_style_bg_color(lv.color_hex(0x2a2a2a), lv.STATE.PRESSED)
            btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
            btn.set_style_border_width(1, 0)
            btn.add_event_cb(self._on_row_clicked, lv.EVENT.CLICKED, None)

            label = lv.label(btn)
            label.set_width(280)
            label.align(lv.ALIGN.LEFT_MID, 10, 0)
            label.set_style_text_color(lv.color_hex(0x00ff00), 0)

            self.rows.append(btn)
            self.row_labels.append(label)

        # Prev/Next
        btn_prev = self.create_button(self.screen, "Prev", width=90, height=30)
        btn_prev.align(lv.ALIGN.BOTTOM_LEFT, 10, -10)
        btn_prev.add_event_cb(self._on_prev, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_prev'] = btn_prev

        btn_next = self.create_button(self.screen, "Next", width=90, height=30)
        btn_next.align(lv.ALIGN.BOTTOM_RIGHT, -10, -10)
        btn_next.add_event_cb(self._on_next, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_next'] = btn_next

        page_label = lv.label(self.screen)
        page_label.set_text("Page 1/1")
        page_label.set_style_text_color(lv.color_hex(0x888888), 0)
        page_label.align(lv.ALIGN.BOTTOM_MID, 0, -14)
        self.ui_elements['page_label'] = page_label

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading talks...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] track_talk_list entry")

        self.page_index = 0
        self._render_page()
        mem_info("[MEM] track_talk_list after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('track_select')
            return True
        return False

    def _format_row_text(self, entry):
        day, start, end, title, speaker, location = entry
        if len(title) > 24:
            title = title[:21] + "..."
        return f"{start}-{end} {title}"

    def _render_page(self):
        from cactuscon import schedule_entries

        day = _get_selected_day()
        track = _get_selected_track()
        entries = schedule_entries.get_entries_by_day_track(day, track)

        total_pages = max(1, (len(entries) + 3) // 4)
        if self.page_index >= total_pages:
            self.page_index = total_pages - 1
        if self.page_index < 0:
            self.page_index = 0

        start_idx = self.page_index * 4
        page_entries = entries[start_idx:start_idx + 4]

        for i in range(4):
            if i < len(page_entries):
                entry = page_entries[i]
                self.row_entries[i] = entry
                _set_row_label(self.row_labels[i], self._format_row_text(entry), active=True)
            else:
                self.row_entries[i] = None
                _set_row_label(self.row_labels[i], "—", active=False)

        if 'page_label' in self.ui_elements:
            self.ui_elements['page_label'].set_text(f"Page {self.page_index + 1}/{total_pages}")

    def _on_prev(self, event):
        self.page_index -= 1
        self._render_page()
        mem_info("[MEM] track_talk_list after UI build")

    def _on_next(self, event):
        self.page_index += 1
        self._render_page()
        mem_info("[MEM] track_talk_list after UI build")

    def _on_row_clicked(self, event):
        target = event.get_target_obj()
        idx = None
        for i, btn in enumerate(self.rows):
            if btn == target:
                idx = i
                break
        if idx is None:
            parent = target.get_parent()
            for i, btn in enumerate(self.rows):
                if btn == parent:
                    idx = i
                    break
        if idx is None:
            return
        entry = self.row_entries[idx]
        if entry is None:
            return
        _set_selected_entry(entry, return_panel='track_talk_list')
        if self.game_ui:
            self.game_ui.show_panel('talk_detail')


class TimeslotViewPanel(BasePanel):
    """Timeslot view (4 tracks, no scrolling)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []
        self.row_labels = []
        self.row_entries = [None, None, None, None]

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Timeslot")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        subtitle = lv.label(self.screen)
        subtitle.set_text("--")
        subtitle.set_style_text_color(lv.color_hex(0x888888), 0)
        subtitle.align(lv.ALIGN.TOP_LEFT, 15, 30)
        self.ui_elements['subtitle'] = subtitle

        # Rows
        y_start = 60
        row_h = 30
        row_gap = 6

        for i in range(4):
            btn = lv.button(self.screen)
            btn.set_size(300, row_h)
            btn.align(lv.ALIGN.TOP_MID, 0, y_start + i * (row_h + row_gap))
            btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
            btn.set_style_bg_color(lv.color_hex(0x2a2a2a), lv.STATE.PRESSED)
            btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
            btn.set_style_border_width(1, 0)
            btn.add_event_cb(self._on_row_clicked, lv.EVENT.CLICKED, None)

            label = lv.label(btn)
            label.set_width(280)
            label.align(lv.ALIGN.LEFT_MID, 10, 0)
            label.set_style_text_color(lv.color_hex(0x00ff00), 0)

            self.rows.append(btn)
            self.row_labels.append(label)

        btn_prev = self.create_button(self.screen, "Prev", width=90, height=30)
        btn_prev.align(lv.ALIGN.BOTTOM_LEFT, 10, -10)
        btn_prev.add_event_cb(self._on_prev, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_prev'] = btn_prev

        btn_next = self.create_button(self.screen, "Next", width=90, height=30)
        btn_next.align(lv.ALIGN.BOTTOM_RIGHT, -10, -10)
        btn_next.add_event_cb(self._on_next, lv.EVENT.CLICKED, None)
        self.ui_elements['btn_next'] = btn_next

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading timeslots...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] timeslot_view entry")
        self._render_timeslot()
        mem_info("[MEM] timeslot_view after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('schedule_mode')
            return True
        return False

    def _find_active_entry(self, entries, t_min):
        from cactuscon import schedule_entries
        for entry in entries:
            start_min = schedule_entries.parse_hhmm(entry[1])
            end_min = schedule_entries.parse_hhmm(entry[2])
            if start_min <= t_min < end_min:
                return entry
        return None

    def _render_timeslot(self):
        from cactuscon import schedule_entries

        day = _get_selected_day()
        timeslots = schedule_entries.get_timeslots_by_day(day)
        if not timeslots:
            timeslots = [0]

        idx = _get_selected_timeslot_idx()
        if idx >= len(timeslots):
            idx = len(timeslots) - 1
        if idx < 0:
            idx = 0
        _set_selected_timeslot_idx(idx)

        t_min = timeslots[idx]
        t_str = schedule_entries.format_hhmm(t_min)
        if 'subtitle' in self.ui_elements:
            self.ui_elements['subtitle'].set_text(f"{day} {t_str}")

        for i, track in enumerate(TRACKS_FIXED):
            entries = schedule_entries.get_entries_by_day_track(day, track)
            entry = self._find_active_entry(entries, t_min)
            if entry is None:
                self.row_entries[i] = None
                _set_row_label(self.row_labels[i], f"{track}: —", active=False)
            else:
                self.row_entries[i] = entry
                title = entry[3]
                if len(title) > 20:
                    title = title[:17] + "..."
                _set_row_label(self.row_labels[i], f"{track}: {title}", active=True)

    def _on_prev(self, event):
        _set_selected_timeslot_idx(_get_selected_timeslot_idx() - 1)
        self._render_timeslot()
        mem_info("[MEM] timeslot_view after UI build")

    def _on_next(self, event):
        _set_selected_timeslot_idx(_get_selected_timeslot_idx() + 1)
        self._render_timeslot()
        mem_info("[MEM] timeslot_view after UI build")

    def _on_row_clicked(self, event):
        target = event.get_target_obj()
        idx = None
        for i, btn in enumerate(self.rows):
            if btn == target:
                idx = i
                break
        if idx is None:
            parent = target.get_parent()
            for i, btn in enumerate(self.rows):
                if btn == parent:
                    idx = i
                    break
        if idx is None:
            return
        entry = self.row_entries[idx]
        if entry is None:
            return
        _set_selected_entry(entry, return_panel='timeslot_view')
        if self.game_ui:
            self.game_ui.show_panel('talk_detail')


class TalkDetailPanel(BasePanel):
    """Talk detail view (no description)."""

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Talk Details")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        day_label = lv.label(self.screen)
        day_label.set_text("Day:")
        day_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        day_label.align(lv.ALIGN.TOP_LEFT, 15, 50)
        self.ui_elements['day_label'] = day_label

        time_label = lv.label(self.screen)
        time_label.set_text("Time:")
        time_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        time_label.align(lv.ALIGN.TOP_LEFT, 15, 75)
        self.ui_elements['time_label'] = time_label

        location_label = lv.label(self.screen)
        location_label.set_text("Location:")
        location_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        location_label.align(lv.ALIGN.TOP_LEFT, 15, 100)
        location_label.set_width(300)
        self.ui_elements['location_label'] = location_label

        speaker_label = lv.label(self.screen)
        speaker_label.set_text("Speaker:")
        speaker_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        speaker_label.align(lv.ALIGN.TOP_LEFT, 15, 125)
        speaker_label.set_width(300)
        self.ui_elements['speaker_label'] = speaker_label

        title_label = lv.label(self.screen)
        title_label.set_text("Title:")
        title_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        title_label.align(lv.ALIGN.TOP_LEFT, 15, 170)
        title_label.set_width(300)
        self.ui_elements['title_label'] = title_label

    def on_show(self):
        # Take ownership of spinner with custom message
        self.show_spinner("Loading details...", pause_ms=60)
        gc.collect()
        mem_info("[MEM] talk_detail entry")

        entry = _get_selected_entry()
        if entry is None:
            entry = ("--", "--:--", "--:--", "Unknown", "Unknown", "Unknown")

        day, start, end, title, speaker, location = entry
        self.ui_elements['day_label'].set_text(f"Day: {day}")
        self.ui_elements['time_label'].set_text(f"Time: {start}-{end}")
        self.ui_elements['title_label'].set_text(f"Title: {title}")
        self.ui_elements['speaker_label'].set_text(f"Speaker: {speaker or 'TBA'}")
        self.ui_elements['location_label'].set_text(f"Location: {location}")

        mem_info("[MEM] talk_detail after UI build")
        self.hide_spinner()

    def on_back_pressed(self, event=None):
        return_panel = _get_detail_return_panel()
        if self.game_ui and return_panel:
            self.game_ui.show_panel(return_panel)
            return True
        return False


class MapPanel(BasePanel):
    """Placeholder map panel."""

    def create_ui(self):
        self.screen.set_style_bg_color(lv.color_black(), 0)
        self.screen.remove_flag(lv.obj.FLAG.SCROLLABLE)

        title = lv.label(self.screen)
        title.set_text("Map")
        title.set_style_text_color(lv.color_hex(0xFFFF00), 0)
        title.align(lv.ALIGN.TOP_LEFT, 15, 10)
        self.ui_elements['title'] = title

        _add_back_button(self, self.on_back_pressed)

        HEADER_H = 40
        self._map_header_h = HEADER_H
        # map container sizing uses active LVGL screen size
        self._map_idx = 0

        nav_btn_w = 50
        nav_btn_h = 24
        nav_y = 8
        nav_gap = 50

        btn_prev = lv.button(self.screen)
        btn_prev.set_size(nav_btn_w, nav_btn_h)
        btn_prev.align(lv.ALIGN.TOP_MID, -nav_gap, nav_y)
        btn_prev.add_event_cb(self._on_prev_clicked, lv.EVENT.CLICKED, None)
        btn_prev.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        btn_prev.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn_prev.set_style_border_width(1, 0)
        lbl_prev = lv.label(btn_prev)
        lbl_prev.set_text("Prev")
        lbl_prev.set_style_text_color(lv.color_hex(0x00ff00), 0)
        lbl_prev.center()
        self.ui_elements["btn_prev"] = btn_prev

        btn_next = lv.button(self.screen)
        btn_next.set_size(nav_btn_w, nav_btn_h)
        btn_next.align(lv.ALIGN.TOP_MID, nav_gap, nav_y)
        btn_next.add_event_cb(self._on_next_clicked, lv.EVENT.CLICKED, None)
        btn_next.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        btn_next.set_style_border_color(lv.color_hex(0x00ff00), 0)
        btn_next.set_style_border_width(1, 0)
        lbl_next = lv.label(btn_next)
        lbl_next.set_text("Next")
        lbl_next.set_style_text_color(lv.color_hex(0x00ff00), 0)
        lbl_next.center()
        self.ui_elements["btn_next"] = btn_next

        idx_label = lv.label(self.screen)
        idx_label.set_text("1/4")
        idx_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        idx_label.align(lv.ALIGN.TOP_MID, 0, 10)
        self.ui_elements["idx_label"] = idx_label

        map_container = lv.obj(self.screen)
        self._update_layout(self.screen)
        screen_w = self.screen.get_width()
        screen_h = self.screen.get_height()
        if not screen_w or not screen_h:
            screen_w = 320
            screen_h = 240

        map_container.set_pos(0, HEADER_H)
        map_container.set_size(screen_w, screen_h - HEADER_H)

        map_container.set_scroll_dir(lv.DIR.VER)
        map_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self._set_flag(map_container, "SCROLLABLE", True)
        map_container.set_style_pad_all(0, 0)
        map_container.set_style_border_width(0, 0)
        map_container.set_style_bg_opa(lv.OPA.TRANSP, 0)

        # Optional but often helpful for “don’t fight me” scrolling
        self._set_flag(map_container, "SCROLL_ELASTIC", False)
        self._set_flag(map_container, "SCROLL_MOMENTUM", False)
        self._set_flag(map_container, "SCROLL_CHAIN_HOR", False)
        self._set_flag(map_container, "SCROLL_CHAIN_VER", False)

        try:
            if hasattr(map_container, "set_scroll_snap_y") and hasattr(lv, "SCROLL_SNAP"):
                map_container.set_scroll_snap_y(lv.SCROLL_SNAP.NONE)
        except Exception:
            pass

        try:
            map_container.move_background()
        except Exception:
            pass
        title = self.ui_elements.get("title")
        if title:
            try:
                title.move_foreground()
            except Exception:
                pass
        btn_back = self.ui_elements.get("btn_back")
        if btn_back:
            try:
                btn_back.move_foreground()
            except Exception:
                pass
        for key in ("btn_prev", "btn_next", "idx_label"):
            obj = self.ui_elements.get(key)
            if obj:
                try:
                    obj.move_foreground()
                except Exception:
                    pass

        self.ui_elements["map_container"] = map_container

        self._map_img_obj = None
        self._map_img_dsc = None
        self._map_img_data = None
        self._map_buffer = None
        self._map_height = 0
        self._map_width = 0

    def on_show(self):
        gc.collect()
        mem_info("[MEM] map entry")
        if DEBUG_MAP_MEM:
            mem_info("[MAP][MEM] show")
        # Take ownership of spinner with custom message for map loading
        self.show_spinner("Loading map...", pause_ms=60)
        self._load_map_variant(self._map_idx)
        mem_info("[MEM] map after UI build")
        self.hide_spinner()

    def on_hide(self):
        self._clear_map_image()
        gc.collect()

    def on_back_pressed(self, event=None):
        if self.game_ui:
            self.game_ui.show_panel('cactuscon_info')
            return True
        return False

    def _on_prev_clicked(self, event=None):
        self.show_spinner("Loading map...", pause_ms=60)
        try:
            lv.task_handler()
            time.sleep_ms(30)
        except Exception:
            pass
        self._set_map_idx(self._map_idx - 1)
        self.hide_spinner()

    def _on_next_clicked(self, event=None):
        self.show_spinner("Loading map...", pause_ms=60)
        try:
            lv.task_handler()
            time.sleep_ms(30)
        except Exception:
            pass
        self._set_map_idx(self._map_idx + 1)
        self.hide_spinner()

    def _set_map_idx(self, idx):
        count = len(MAP_VARIANTS)
        if count <= 0:
            return
        self._map_idx = idx % count
        self._load_map_variant(self._map_idx)

    def _acquire_map_buffer(self, size):
        buf = ensure_map_buffer_pinned()
        if buf is None:
            self.logger.error(f"[MAP] buffer not pinned: need {size} bytes")
            return None
        if _MAP_BUFFER_SIZE < size:
            self.logger.error(
                f"[MAP] pinned buffer too small: need {size} have {_MAP_BUFFER_SIZE}"
            )
            return None
        return buf

    def _load_map_variant(self, idx):
        map_container = self.ui_elements.get("map_container")
        if not map_container:
            self.logger.warning("[MAP] map_container missing")
            return

        self._clear_map_image()
        error_message = "Map load failed"
        retryable = False

        for attempt in (1, 2):
            ok, retryable, error_message = self._try_load_map_variant(map_container, idx)
            if ok:
                return
            if attempt == 1 and retryable:
                self.logger.warning("[MAP] transient load failure; retrying once after gc")
                gc.collect()
                continue
            break

        self._show_map_error(map_container, error_message)

    def _try_load_map_variant(self, map_container, idx):
        try:
            name, map_path, map_src_w, map_src_h, expected_bytes, scroll_enabled = MAP_VARIANTS[idx]
            try:
                stat = uos.stat(map_path)
                file_size = stat[6]
                if file_size != expected_bytes:
                    self.logger.error(
                        f"[MAP] size mismatch for {name}: expected={expected_bytes} got={file_size}"
                    )
                    return False, False, f"{name} size mismatch"
            except Exception as e:
                self.logger.error(f"[MAP] stat failed for {name}: {e}")
                return False, False, f"{name} missing"

            self._update_layout(map_container)
            if scroll_enabled:
                map_container.set_scroll_dir(lv.DIR.VER)
                self._set_flag(map_container, "SCROLLABLE", True)
                self._set_flag(map_container, "SCROLL_ELASTIC", False)
                self._set_flag(map_container, "SCROLL_MOMENTUM", False)
                self._set_flag(map_container, "SCROLL_CHAIN_HOR", False)
                self._set_flag(map_container, "SCROLL_CHAIN_VER", False)
            else:
                self._set_flag(map_container, "SCROLLABLE", False)

            buf = self._acquire_map_buffer(expected_bytes)
            if buf is None:
                return False, True, "Map load failed"

            img_data = load_rgb565_file_into(map_path, buf, do_swap=True, size=expected_bytes)
            img_dsc = create_image_descriptor(img_data, map_src_w, map_src_h)

            img = lv.image(map_container)
            img.set_src(img_dsc)
            img.set_pos(0, 0)
            try:
                img.set_size(map_src_w, map_src_h)
            except Exception:
                pass

            self._set_flag(img, "SCROLLABLE", False)
            self._set_flag(img, "SCROLL_ELASTIC", False)
            self._set_flag(img, "SCROLL_MOMENTUM", False)
            self._set_flag(img, "SCROLL_CHAIN_HOR", False)
            self._set_flag(img, "SCROLL_CHAIN_VER", False)

            self._update_layout(map_container)
            self._map_img_obj = img
            self._map_img_dsc = img_dsc
            self._map_img_data = img_data
            self._map_buffer = buf
            self._map_width = map_src_w
            self._map_height = map_src_h

            self._update_idx_label()
            self.logger.info(f"[MAP] loaded {name} ({map_src_w}x{map_src_h})")
            if DEBUG_MAP:
                self._log_map_debug(map_container, img)
            return True, False, None
        except Exception as e:
            self.logger.error(f"[MAP] load failed: {e}")
            return False, True, "Map load failed"


    def _update_idx_label(self):
        label = self.ui_elements.get("idx_label")
        if label:
            label.set_text(f"{self._map_idx + 1}/{len(MAP_VARIANTS)}")

    def _show_map_error(self, container, message):
        label = lv.label(container)
        label.set_text(message)
        label.center()
        self._map_img_obj = label

    def _clear_map_image(self):
        if self._map_img_obj:
            try:
                self._map_img_obj.delete()
            except Exception:
                pass
        self._map_img_obj = None
        self._map_img_dsc = None
        self._map_img_data = None
        self._map_buffer = None
        self._map_height = 0
        self._map_width = 0

    # --- diagnostics/helpers ---
    def _update_layout(self, obj):
        try:
            obj.update_layout()
            return
        except Exception:
            pass
        try:
            lv.obj_update_layout(obj)
        except Exception:
            pass

    def _set_flag(self, obj, flag_name, enabled):
        try:
            flag = getattr(lv.obj.FLAG, flag_name)
        except Exception as e:
            self.logger.warning(f"[MAP] flag {flag_name} lookup failed: {e}")
            return
        try:
            if enabled:
                if hasattr(obj, "add_flag"):
                    obj.add_flag(flag)
            else:
                if hasattr(obj, "remove_flag"):
                    obj.remove_flag(flag)
                elif hasattr(obj, "clear_flag"):
                    obj.clear_flag(flag)
        except Exception as e:
            self.logger.warning(f"[MAP] set_flag {flag_name} failed: {e}")

    def _log_map_debug(self, map_container, img_obj):
        try:
            screen_w = self.screen.get_width()
            screen_h = self.screen.get_height()
        except Exception:
            screen_w = screen_h = None
        self.logger.info(f"[MAP] screen=({screen_w},{screen_h})")
        self.logger.info(
            f"[MAP] container=({map_container.get_width()},{map_container.get_height()}) flags={self._get_flags(map_container)}"
        )
        self.logger.info(
            f"[MAP] img=({self._map_width},{self._map_height}) flags={self._get_flags(img_obj)}"
        )

    def _get_flags(self, obj):
        flags = {}
        for key in (
            "SCROLLABLE",
            "SCROLL_ELASTIC",
            "SCROLL_MOMENTUM",
            "SCROLL_CHAIN_HOR",
            "SCROLL_CHAIN_VER",
            "SCROLL_ONE",
            "CLICKABLE",
        ):
            try:
                flag = getattr(lv.obj.FLAG, key)
                flags[key] = obj.has_flag(flag)
            except Exception:
                pass
        return flags
