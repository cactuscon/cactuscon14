"""WiFi flow debug helpers."""

WIFI_FLOW_DEBUG = False


def snapshot(
    logger,
    label,
    viewport_coords,
    viewport_size,
    footer_coords,
    footer_in_bounds,
    kb_parent,
    kb_coords,
    shift,
):
    if not WIFI_FLOW_DEBUG:
        return
    if logger:
        logger.info(
            "[WIFI-FLOW] {} viewport={} size={} footer={} in_bounds={} kb_parent={} kb_coords={} shift={}".format(
                label,
                viewport_coords,
                viewport_size,
                footer_coords,
                footer_in_bounds,
                kb_parent,
                kb_coords,
                shift,
            )
        )
