"""WiFi flow LVGL view builders (no WiFi logic)."""

import lvgl as lv

PAGE_SIZE = 2

FLEX_START = getattr(lv.FLEX_ALIGN, "START", 0)
FLEX_CENTER = getattr(lv.FLEX_ALIGN, "CENTER", FLEX_START)
FLEX_SPACE_BETWEEN = getattr(lv.FLEX_ALIGN, "SPACE_BETWEEN", FLEX_START)


def _apply_transparent(obj):
    try:
        if hasattr(lv, "OPA") and hasattr(lv.OPA, "TRANSP"):
            obj.set_style_bg_opa(lv.OPA.TRANSP, 0)
        else:
            obj.set_style_bg_opa(0, 0)
    except Exception:
        pass
    obj.set_style_border_width(0, 0)

def _set_bg_opa(obj, opa_value, fallback_value=None):
    try:
        obj.set_style_bg_opa(opa_value, 0)
    except Exception:
        if fallback_value is not None:
            try:
                obj.set_style_bg_opa(fallback_value, 0)
            except Exception:
                pass

def _flex_align(obj, main, cross, track):
    try:
        obj.set_flex_align(main, cross, track)
    except Exception:
        pass


def _pick_font(sizes):
    for size in sizes:
        font = getattr(lv, "font_montserrat_{}".format(size), None)
        if font:
            return font
    return None


def _apply_font(label, sizes):
    font = _pick_font(sizes)
    if not font:
        return
    try:
        label.set_style_text_font(font, 0)
    except Exception:
        pass


def _clear_clickable(obj):
    if not obj:
        return
    try:
        if hasattr(obj, "remove_flag") and hasattr(lv.obj.FLAG, "CLICKABLE"):
            obj.remove_flag(lv.obj.FLAG.CLICKABLE)
        elif hasattr(obj, "clear_flag") and hasattr(lv.obj.FLAG, "CLICKABLE"):
            obj.clear_flag(lv.obj.FLAG.CLICKABLE)
        elif hasattr(obj, "set_flag") and hasattr(lv.obj.FLAG, "CLICKABLE"):
            obj.set_flag(lv.obj.FLAG.CLICKABLE, False)
    except Exception:
        pass
    try:
        if hasattr(obj, "remove_flag") and hasattr(lv.obj.FLAG, "CLICK_FOCUSABLE"):
            obj.remove_flag(lv.obj.FLAG.CLICK_FOCUSABLE)
        elif hasattr(obj, "clear_flag") and hasattr(lv.obj.FLAG, "CLICK_FOCUSABLE"):
            obj.clear_flag(lv.obj.FLAG.CLICK_FOCUSABLE)
        elif hasattr(obj, "set_flag") and hasattr(lv.obj.FLAG, "CLICK_FOCUSABLE"):
            obj.set_flag(lv.obj.FLAG.CLICK_FOCUSABLE, False)
    except Exception:
        pass


def _scaffold(parent, title_text, footer_height):
    root = lv.obj(parent)
    root.set_size(lv.pct(100), lv.pct(100))
    root.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _apply_transparent(root)

    root.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    _flex_align(root, FLEX_START, FLEX_START, FLEX_START)
    root.set_style_pad_all(6, 0)
    root.set_style_pad_row(6, 0)

    header = lv.obj(root)
    header.set_width(lv.pct(100))
    header.set_height(28)
    header.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _apply_transparent(header)
    header.set_flex_flow(lv.FLEX_FLOW.ROW)
    _flex_align(header, FLEX_SPACE_BETWEEN, FLEX_CENTER, FLEX_CENTER)

    title = lv.label(header)
    title.set_text(title_text)
    title.set_style_text_color(lv.color_hex(0xFFFF00), 0)

    body = lv.obj(root)
    body.set_width(lv.pct(100))
    body.set_flex_grow(1)
    body.set_style_bg_color(lv.color_hex(0x0a0a0a), 0)
    body.set_style_border_color(lv.color_hex(0x333333), 0)
    body.set_style_border_width(1, 0)
    body.set_style_pad_all(6, 0)
    body.set_style_pad_row(4, 0)
    body.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    _flex_align(body, FLEX_START, FLEX_START, FLEX_START)
    body.remove_flag(lv.obj.FLAG.SCROLLABLE)

    footer = lv.obj(root)
    footer.set_width(lv.pct(100))
    footer.set_height(footer_height)
    footer.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _apply_transparent(footer)
    footer.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    footer.set_style_pad_row(4, 0)

    return {
        "root": root,
        "header": header,
        "body": body,
        "footer": footer,
        "title": title,
    }


def _footer_row(parent):
    row = lv.obj(parent)
    row.set_width(lv.pct(100))
    row.set_height(24)
    row.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _apply_transparent(row)
    row.set_flex_flow(lv.FLEX_FLOW.ROW)
    _flex_align(row, FLEX_SPACE_BETWEEN, FLEX_CENTER, FLEX_CENTER)
    row.set_style_pad_column(4, 0)
    return row


def _button_label(btn):
    if not btn:
        return None
    try:
        if hasattr(btn, "get_child"):
            return btn.get_child(0)
    except Exception:
        pass
    return None


def build_list_view(parent, button_factory):
    view = _scaffold(parent, "WiFi Networks", footer_height=66)

    page_label = lv.label(view["header"])
    page_label.set_text("Page 1/1")
    page_label.set_style_text_color(lv.color_hex(0x888888), 0)

    list_container = lv.obj(view["body"])
    list_container.set_width(lv.pct(100))
    list_container.set_flex_grow(1)
    list_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
    _flex_align(list_container, FLEX_START, FLEX_START, FLEX_START)
    list_container.set_style_pad_row(4, 0)
    list_container.remove_flag(lv.obj.FLAG.SCROLLABLE)
    _apply_transparent(list_container)

    rows = []
    for _ in range(PAGE_SIZE):
        row_btn = lv.button(list_container)
        row_btn.set_width(lv.pct(100))
        row_btn.set_height(28)
        row_btn.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
        row_btn.set_style_bg_color(lv.color_hex(0x2a2a2a), lv.STATE.PRESSED)
        row_btn.set_style_border_color(lv.color_hex(0x00ff00), 0)
        row_btn.set_style_border_width(1, 0)
        row_btn.set_style_radius(4, 0)
        row_btn.set_style_pad_all(4, 0)
        row_btn.set_flex_flow(lv.FLEX_FLOW.ROW)
        _flex_align(row_btn, FLEX_SPACE_BETWEEN, FLEX_CENTER, FLEX_CENTER)
        row_btn.remove_flag(lv.obj.FLAG.SCROLLABLE)

        ssid_label = lv.label(row_btn)
        ssid_label.set_text("---")
        ssid_label.set_style_text_color(lv.color_hex(0x00ff00), 0)
        try:
            ssid_label.set_long_mode(lv.label.LONG.DOT)
            ssid_label.set_width(lv.pct(70))
        except Exception:
            pass

        rssi_label = lv.label(row_btn)
        rssi_label.set_text("")
        rssi_label.set_style_text_color(lv.color_hex(0x888888), 0)

        rows.append({
            "btn": row_btn,
            "ssid": ssid_label,
            "rssi": rssi_label,
        })

    footer_row1 = _footer_row(view["footer"])
    footer_row2 = _footer_row(view["footer"])

    btn_back = button_factory(footer_row1, "Back", width=lv.pct(31), height=24)
    btn_reconnect = button_factory(footer_row1, "Reconnect", width=lv.pct(31), height=24)
    btn_refresh = button_factory(footer_row1, "Refresh", width=lv.pct(31), height=24)
    _apply_font(_button_label(btn_back), [12, 10])
    _apply_font(_button_label(btn_reconnect), [12, 10])
    _apply_font(_button_label(btn_refresh), [12, 10])
    btn_prev = button_factory(footer_row2, "Previous", width=lv.pct(48), height=24)
    btn_next = button_factory(footer_row2, "Next", width=lv.pct(48), height=24)

    view.update({
        "page_label": page_label,
        "list_container": list_container,
        "rows": rows,
        "btn_back": btn_back,
        "btn_reconnect": btn_reconnect,
        "btn_refresh": btn_refresh,
        "btn_prev": btn_prev,
        "btn_next": btn_next,
    })
    return view


def build_password_view(parent, button_factory):
    view = _scaffold(parent, "WiFi Password", footer_height=52)

    ssid_label = lv.label(view["body"])
    ssid_label.set_text("Network: ---")
    ssid_label.set_style_text_color(lv.color_hex(0x00ff00), 0)

    password_ta = lv.textarea(view["body"])
    password_ta.set_width(lv.pct(100))
    password_ta.set_height(30)
    password_ta.set_one_line(True)
    password_ta.set_max_length(64)
    password_ta.set_placeholder_text("Password...")
    password_ta.set_style_bg_color(lv.color_hex(0x1a1a1a), 0)
    password_ta.set_style_border_color(lv.color_hex(0x00ff00), 0)
    password_ta.set_style_border_width(1, 0)
    password_ta.set_style_radius(4, 0)
    password_ta.set_style_pad_left(8, 0)
    # try:
    #     password_ta.set_password_mode(True)
    # except Exception:
    #     pass

    remember_cb = lv.checkbox(view["body"])
    remember_cb.set_text("Remember this Wi-Fi")
    remember_cb.set_style_text_color(lv.color_hex(0x888888), 0)
    try:
        remember_cb.set_width(lv.pct(100))
    except Exception:
        pass
    try:
        if hasattr(remember_cb, "clear_state"):
            remember_cb.clear_state(lv.STATE.CHECKED)
    except Exception:
        pass

    status_label = lv.label(view["body"])
    status_label.set_text("")
    status_label.set_style_text_color(lv.color_hex(0x888888), 0)
    _apply_font(status_label, [16, 14, 12])

    footer_row = _footer_row(view["footer"])
    btn_back = button_factory(footer_row, "Back", width=lv.pct(48), height=24)
    btn_connect = button_factory(footer_row, "Connect", width=lv.pct(48), height=24)

    view.update({
        "ssid_label": ssid_label,
        "password_ta": password_ta,
        "remember_cb": remember_cb,
        "status_label": status_label,
        "btn_back": btn_back,
        "btn_connect": btn_connect,
    })
    return view


def build_status_overlay(parent):
    overlay = lv.obj(parent)
    overlay.set_size(lv.pct(100), lv.pct(100))
    overlay.set_pos(0, 0)
    overlay.set_style_bg_color(lv.color_hex(0x000000), 0)
    if hasattr(lv, "OPA") and hasattr(lv.OPA, "_60"):
        _set_bg_opa(overlay, lv.OPA._60, 160)
    else:
        _set_bg_opa(overlay, 160, 160)
    overlay.set_style_border_width(0, 0)
    overlay.remove_flag(lv.obj.FLAG.SCROLLABLE)
    overlay.add_flag(lv.obj.FLAG.HIDDEN)
    if hasattr(lv.obj.FLAG, "FLOATING"):
        overlay.add_flag(lv.obj.FLAG.FLOATING)
    elif hasattr(lv.obj.FLAG, "IGNORE_LAYOUT"):
        overlay.add_flag(lv.obj.FLAG.IGNORE_LAYOUT)
    _clear_clickable(overlay)

    spinner_box = lv.obj(overlay)
    spinner_box.set_size(48, 48)
    spinner_box.set_pos(0, 0)
    _apply_transparent(spinner_box)
    spinner_box.set_style_border_width(0, 0)
    _clear_clickable(spinner_box)

    spinner = lv.spinner(spinner_box)
    try:
        spinner.set_spin_time(900)
        spinner.set_arc_length(70)
    except Exception:
        try:
            spinner.set_anim_time(900)
        except Exception:
            pass
    try:
        spinner.set_size(48, 48)
    except Exception:
        pass

    spinner_box.align(lv.ALIGN.CENTER, 0, -18)
    spinner.align(lv.ALIGN.CENTER, 0, 0)
    spinner.set_style_arc_width(2, 0)
    spinner.set_style_arc_color(lv.color_hex(0xCCCCCC), 0)
    _clear_clickable(spinner)

    label_primary = lv.label(overlay)
    label_primary.set_text("Connecting...")
    label_primary.set_style_text_color(lv.color_hex(0xDDDDDD), 0)
    _apply_font(label_primary, [22, 20, 18, 16])
    try:
        label_primary.set_width(lv.pct(90))
        label_primary.set_long_mode(lv.label.LONG.DOT)
    except Exception:
        pass
    label_primary.align(lv.ALIGN.CENTER, 0, 18)
    _clear_clickable(label_primary)

    label_secondary = lv.label(overlay)
    label_secondary.set_text("")
    label_secondary.set_style_text_color(lv.color_hex(0x888888), 0)
    _apply_font(label_secondary, [16, 14, 12])
    try:
        label_secondary.set_width(lv.pct(90))
        label_secondary.set_long_mode(lv.label.LONG.DOT)
    except Exception:
        pass
    label_secondary.align(lv.ALIGN.CENTER, 0, 40)
    _clear_clickable(label_secondary)

    return {
        "overlay": overlay,
        "spinner": spinner,
        "label": label_primary,
        "label_primary": label_primary,
        "label_secondary": label_secondary,
    }
