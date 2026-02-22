# micropython boot.py
"""
Badge boot sequence - handles OTA updates and display initialization.

Both normal and headless (AUTO_BATTLE_MODE) badges run OTA.
Headless mode skips display/LVGL initialization.
"""
import usys as sys
import time
import gc
import os
import network
from machine import Pin
import machine

# Load config and initialize logger early.
from cactuscon import config
from cactuscon.utils import Logger
from cactuscon.hw.wifi import (
    load_saved_credentials,
    load_saved_failure_count,
    increment_saved_failure,
    reset_saved_failure
)

logger = Logger(config.LOG_LEVEL)
from saguarota.saguarota import OTAUpdater, OTAState

# ============================================================================
# MODE DETECTION
# ============================================================================
_HEADLESS_MODE = getattr(config, 'AUTO_BATTLE_MODE', False)
display_bus = None
spi_bus = None

# LOADER DISPLAY (Normal mode only, no-op in headless)
_loader_label = None
_loader_version_label = None
_loader_initialized = False
_boot_version_text = None

# ============================================================================
# OTA CONFIGURATION (Both modes)
# ============================================================================
OTA_WIFI_SSID = config.OTA_WIFI_SSID
OTA_WIFI_PASSWORD = config.OTA_WIFI_PASSWORD
OTA_FORCED_UPDATE = config.OTA_FORCED_UPDATE
OTA_BASE_FILE_URL = config.get_ota_base_url()
OTA_MANIFEST_URL = config.get_ota_manifest_url()
OTA_MANIFEST_RECURSE_HTTP_FS = config.OTA_DEV_RECURSE_HTTP_FS
OTA_CONFIRM_PENDING_COUNT_FILE = "ota_confirm_pending_boots.txt"
OTA_CONFIRM_PENDING_MAX_BOOTS = int(
    getattr(config, "OTA_CONFIRM_PENDING_MAX_BOOTS", 1)
)

STAT_IDLE = getattr(network, "STAT_IDLE", 0)
STAT_CONNECTING = getattr(network, "STAT_CONNECTING", 1)
STAT_WRONG_PASSWORD = getattr(network, "STAT_WRONG_PASSWORD", -3)
STAT_NO_AP_FOUND = getattr(network, "STAT_NO_AP_FOUND", -2)
STAT_CONNECT_FAIL = getattr(network, "STAT_CONNECT_FAIL", -1)
STAT_GOT_IP = getattr(network, "STAT_GOT_IP", 3)

_BOOT_START_MS = None
if hasattr(time, "ticks_ms"):
    _BOOT_START_MS = time.ticks_ms()
else:
    _BOOT_START_MS = int(time.time() * 1000)


def _since_boot_ms():
    if hasattr(time, "ticks_ms") and hasattr(time, "ticks_diff"):
        return time.ticks_diff(time.ticks_ms(), _BOOT_START_MS)
    return int(time.time() * 1000) - _BOOT_START_MS


def _status_reason(status):
    if status == STAT_WRONG_PASSWORD:
        return "wrong_password"
    if status == STAT_NO_AP_FOUND:
        return "no_ap"
    if status == STAT_CONNECT_FAIL:
        return "connect_fail"
    if status == STAT_GOT_IP:
        return "got_ip"
    if status == STAT_CONNECTING:
        return "connecting"
    if status == STAT_IDLE:
        return "idle"
    return "status_{}".format(status)


def _safe_status(wifi):
    try:
        return wifi.status()
    except Exception:
        return None


def _safe_ifconfig(wifi):
    try:
        return wifi.ifconfig()
    except Exception:
        return None


def _log_wifi_state(label, wifi, status=None, attempt=None, ssid=None):
    ts = _since_boot_ms()
    try:
        active = wifi.active()
    except Exception:
        active = None
    try:
        connected = wifi.isconnected()
    except Exception:
        connected = None
    status_val = status if status is not None else _safe_status(wifi)
    status_reason = _status_reason(status_val) if status_val is not None else "unknown"
    ifconfig = _safe_ifconfig(wifi)
    ip = None
    if ifconfig:
        try:
            ip = ifconfig[0]
        except Exception:
            ip = None
    ifconfig_str = ""
    if ifconfig:
        try:
            ifconfig_str = str(ifconfig)
        except Exception:
            ifconfig_str = ""
    logger.info(
        "[OTA-WIFI] t={}ms state={} attempt={} ssid={} active={} connected={} status={} reason={} ip={} ifconfig={}".format(
            ts,
            label,
            attempt,
            ssid or "",
            active,
            connected,
            status_val,
            status_reason,
            ip or "",
            ifconfig_str,
        )
    )


def _scan_for_ssid(wifi, target_ssid):
    try:
        if hasattr(wifi, "active"):
            wifi.active(True)
        results = wifi.scan()
    except Exception as e:
        logger.warning(f"[OTA-WIFI] scan failed: {e}")
        return None
    for entry in results or []:
        try:
            ssid_raw = entry[0]
        except Exception:
            continue
        try:
            if isinstance(ssid_raw, bytes):
                ssid = ssid_raw.decode("utf-8")
            else:
                ssid = str(ssid_raw)
        except Exception:
            ssid = ""
        if ssid == target_ssid:
            return True
    return False


# Aggressively unload boot-only modules to minimize memory footprint.
def _purge_modules(prefixes, keep=()):
    removed = 0
    for name in list(sys.modules.keys()):
        if name in keep:
            continue
        for prefix in prefixes:
            if name == prefix or name.startswith(prefix + "."):
                try:
                    del sys.modules[name]
                    removed += 1
                except Exception:
                    pass
                break
    if removed:
        logger.info(f"[BOOT] Purged {removed} modules")


if _HEADLESS_MODE:
    logger.info("=" * 50)
    logger.info("AUTO_BATTLE_MODE - Headless Station/Gym Mode")
    logger.info("Display/LVGL disabled, OTA still active")
    logger.info("=" * 50)
    
else:
    import lvgl as lv
    lv.init()

    import lcd_bus
    import ili9341
    import task_handler

def show_loader(message="Loading..."):
    """Display a centered loading animation with text on full screen (LVGL 9.4).
    
    In headless mode, just prints to console.
    In normal mode, displays graphical loader on screen.
    
    Args:
        message: Status text to display below the hourglass icon
    """
    global _loader_label, _loader_initialized
    global _loader_version_label, _boot_version_text
    
    # Headless mode - just print to console
    if _HEADLESS_MODE:
        logger.info(f"[BOOT] {message}")
        return
    
    try:
        scr = lv.screen_active()
        
        # If already initialized, just update the label
        if _loader_initialized and _loader_label:
            _loader_label.set_text(message)
            _loader_label.refr_size()
            label_width = _loader_label.get_width()
            screen_width = scr.get_width()
            x = (screen_width - label_width) // 2
            _loader_label.set_x(x)
            return
        
        # First time initialization - create all graphics
        scr.set_style_bg_color(lv.color_black(), 0)

        # Resolve a human-readable build/version string from the local OTA manifest.
        # The manifest "version" is a unix timestamp (seconds) from the host's mtime.
        if _boot_version_text is None:
            _boot_version_text = _read_boot_version_text()
        
        # Create a container for the hourglass
        cont = lv.obj(scr)
        cont.set_size(100, 100)
        cont.set_pos(110, 70)
        cont.set_style_bg_color(lv.color_black(), 0)
        cont.set_style_border_color(lv.color_white(), 0)
        cont.set_style_border_width(2, 0)
        cont.set_style_radius(50, 0)
        
        # Draw hourglass outline using line widgets with yellow color
        p_top_left = [
            lv.point_precise_t({'x': 140, 'y': 90}),
            lv.point_precise_t({'x': 180, 'y': 90}),
        ]
        line_top1 = lv.line(scr)
        line_top1.set_points(p_top_left, len(p_top_left))
        line_top1.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_top1.set_style_line_width(2, 0)
        
        p_top_right = [
            lv.point_precise_t({'x': 180, 'y': 90}),
            lv.point_precise_t({'x': 160, 'y': 120}),
        ]
        line_top2 = lv.line(scr)
        line_top2.set_points(p_top_right, len(p_top_right))
        line_top2.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_top2.set_style_line_width(2, 0)
        
        p_top_close = [
            lv.point_precise_t({'x': 160, 'y': 120}),
            lv.point_precise_t({'x': 140, 'y': 90}),
        ]
        line_top3 = lv.line(scr)
        line_top3.set_points(p_top_close, len(p_top_close))
        line_top3.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_top3.set_style_line_width(2, 0)
        
        p_bot_left = [
            lv.point_precise_t({'x': 160, 'y': 120}),
            lv.point_precise_t({'x': 140, 'y': 150}),
        ]
        line_bot1 = lv.line(scr)
        line_bot1.set_points(p_bot_left, len(p_bot_left))
        line_bot1.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_bot1.set_style_line_width(2, 0)
        
        p_bot_right = [
            lv.point_precise_t({'x': 140, 'y': 150}),
            lv.point_precise_t({'x': 180, 'y': 150}),
        ]
        line_bot2 = lv.line(scr)
        line_bot2.set_points(p_bot_right, len(p_bot_right))
        line_bot2.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_bot2.set_style_line_width(2, 0)
        
        p_bot_close = [
            lv.point_precise_t({'x': 180, 'y': 150}),
            lv.point_precise_t({'x': 160, 'y': 120}),
        ]
        line_bot3 = lv.line(scr)
        line_bot3.set_points(p_bot_close, len(p_bot_close))
        line_bot3.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_bot3.set_style_line_width(2, 0)
        
        center_points = [
            lv.point_precise_t({'x': 160, 'y': 118}),
            lv.point_precise_t({'x': 160, 'y': 122}),
        ]
        line_center = lv.line(scr)
        line_center.set_points(center_points, len(center_points))
        line_center.set_style_line_color(lv.color_hex(0xFFFF00), 0)
        line_center.set_style_line_width(3, 0)

        # Version label - centered above the hourglass so it is visible on boot.
        if _boot_version_text:
            _loader_version_label = lv.label(scr)
            _loader_version_label.set_text(_boot_version_text)
            _loader_version_label.set_style_text_color(lv.color_hex(0xFFFF00), 0)
            try:
                _loader_version_label.set_style_text_font(lv.font_montserrat_18, 0)
            except Exception:
                pass
            _loader_version_label.refr_size()
            v_w = _loader_version_label.get_width()
            screen_width = scr.get_width()
            _loader_version_label.set_x((screen_width - v_w) // 2)
            _loader_version_label.set_y(40)
        
        # Status text - white text, centered
        _loader_label = lv.label(scr)
        _loader_label.set_text(message)
        _loader_label.set_style_text_color(lv.color_white(), 0)
        
        _loader_label.refr_size()
        _loader_label.refr_pos()
        
        label_width = _loader_label.get_width()
        screen_width = scr.get_width()
        x = (screen_width - label_width) // 2
        _loader_label.set_x(x)
        _loader_label.set_y(200)
        
        _loader_initialized = True
    
    except Exception as e:
        logger.error(f"Error in show_loader: {e}")


def _read_boot_version_text():
    """
    Read the local OTA manifest's "version" field and format it as:
        vYYMMDD.HH.MM
    """
    manifest_path = getattr(config, "OTA_MANIFEST_FILE", "versions.json") or "versions.json"
    ts = _read_manifest_version_ts(manifest_path)
    if ts is None:
        return ""
    return _format_manifest_ts(ts)


def _read_manifest_version_ts(path):
    """
    Fast-path parse for the top-level "version" field without loading full JSON.
    The manifest is generated with indent=2 so "version" appears at the top.
    """
    try:
        f = open(path, "r")
    except Exception:
        return None
    try:
        chunk = f.read(512)
    except Exception:
        try:
            f.close()
        except Exception:
            pass
        return None
    try:
        f.close()
    except Exception:
        pass

    key = '"version"'
    i = chunk.find(key)
    if i < 0:
        return None
    i = chunk.find(":", i + len(key))
    if i < 0:
        return None
    i += 1
    n = len(chunk)
    while i < n and chunk[i] in " \t":
        i += 1
    j = i
    while j < n and ("0" <= chunk[j] <= "9"):
        j += 1
    if j <= i:
        return None
    try:
        return int(chunk[i:j])
    except Exception:
        return None


def _format_manifest_ts(ts):
    try:
        ts_i = int(ts)
    except Exception:
        return ""
    # Convert manifest "version" -> UTC calendar fields.
    #
    # Our OTA manifest is generated on the host using filesystem mtimes, which
    # are unix timestamps (seconds since 1970-01-01).
    #
    # MicroPython's `time.gmtime()`/`time.localtime()` are typically based on
    # an epoch of 2000-01-01 (not 1970), so we translate unix seconds into the
    # device's epoch before calling gmtime(). Otherwise years will appear as
    # 2056 ("56") etc.
    try:
        base_year = 1970
        try:
            base_year = time.gmtime(0)[0]
        except Exception:
            base_year = 1970

        # MicroPython epoch (2000) vs unix epoch (1970)
        if base_year >= 1990:
            UNIX_TO_MP_EPOCH_S = 946684800  # 1970-01-01 -> 2000-01-01
            ts_i = ts_i - UNIX_TO_MP_EPOCH_S

        if hasattr(time, "gmtime"):
            tm = time.gmtime(ts_i)
        else:
            tm = time.localtime(ts_i)
        year, month, day, hour, minute = tm[0], tm[1], tm[2], tm[3], tm[4]
        yy = year % 100
        return "v{:02d}{:02d}{:02d}.{:02d}.{:02d}".format(yy, month, day, hour, minute)
    except Exception:
        return ""

# ============================================================================
# OTA SETUP (Both modes)
# ============================================================================
def setup(updater, wifi):
    """Connect to WiFi and check for OTA updates."""
    wifi.active(True)

    # Give the user a moment after reset to hold the BOOT button.
    # BOOT button on ESP32-S3 is typically active-low on GPIO0.
    show_loader("Hold BOOT for OTA...")
    time.sleep(0.75)

    def _boot_button_held():
        try:
            boot_pin = Pin(int(config.PIN_BOOT_BUTTON), Pin.IN, Pin.PULL_UP)
        except Exception:
            boot_pin = Pin(int(config.PIN_BOOT_BUTTON), Pin.IN)
        return boot_pin.value() == 0

    try:
        # Check if OTA was requested via boot button 
        ota_requested = _boot_button_held()
        logger.info(
            f"[OTA-WIFI] boot={_since_boot_ms()}ms ota_requested={ota_requested}"
        )
        
        if not ota_requested:
            # Skip server update checks unless BOOT is held,
            # but still allow the fallback below to revert an interrupted update (if any).
            raise RuntimeError("OTA not requested")

        connect_timeout_ms = int(getattr(config, "OTA_WIFI_TIMEOUT_S", 15) * 1000)
        max_attempts = int(getattr(config, "OTA_WIFI_MAX_ATTEMPTS", 2))
        scan_before = bool(getattr(config, "OTA_WIFI_SCAN_BEFORE_CONNECT", True))
        saved_fail_limit = int(getattr(config, "OTA_SAVED_FAIL_LIMIT", 3))

        def _attempt_connect(ssid, password, label, allow_scan=True):
            if not ssid:
                return False
            for attempt in range(1, max_attempts + 1):
                show_loader("Connecting {} WiFi...".format(label))
                _log_wifi_state("STA_CONNECTING", wifi, attempt=attempt, ssid=ssid)
                if allow_scan and scan_before:
                    found = _scan_for_ssid(wifi, ssid)
                    if found is False:
                        _log_wifi_state("STA_SCAN_NO_AP", wifi, attempt=attempt, ssid=ssid)
                        try:
                            wifi.disconnect()
                        except Exception:
                            pass
                        try:
                            wifi.active(False)
                        except Exception:
                            pass
                        if attempt >= max_attempts:
                            return False
                        time.sleep(0.3)
                        continue
                try:
                    wifi.active(True)
                    if password:
                        wifi.connect(ssid, password)
                    else:
                        wifi.connect(ssid)
                except Exception as e:
                    logger.warning(f"[OTA-WIFI] connect error ({label}): {e}")
                    if attempt >= max_attempts:
                        return False
                    time.sleep(0.3)
                    continue

                start_ms = _since_boot_ms()
                last_status = None
                while (_since_boot_ms() - start_ms) < connect_timeout_ms:
                    status = _safe_status(wifi)
                    if status != last_status:
                        _log_wifi_state("STA_STATUS", wifi, status=status, attempt=attempt, ssid=ssid)
                        last_status = status
                    if status in (STAT_WRONG_PASSWORD, STAT_CONNECT_FAIL, STAT_NO_AP_FOUND):
                        _log_wifi_state("STA_STATUS_FAIL", wifi, status=status, attempt=attempt, ssid=ssid)
                        try:
                            wifi.disconnect()
                        except Exception:
                            pass
                        try:
                            wifi.active(False)
                        except Exception:
                            pass
                        # Wrong password is a hard failure; no value in retrying.
                        if status == STAT_WRONG_PASSWORD:
                            return False
                        # Retry transient association errors until attempts are exhausted.
                        if attempt >= max_attempts:
                            return False
                        time.sleep(0.3)
                        break
                    if status == STAT_GOT_IP:
                        _log_wifi_state("STA_GOT_IP", wifi, status=status, attempt=attempt, ssid=ssid)
                        return True
                    try:
                        if wifi.isconnected():
                            _log_wifi_state("STA_GOT_IP", wifi, status=status, attempt=attempt, ssid=ssid)
                            return True
                    except Exception:
                        pass
                    time.sleep(0.25)

                _log_wifi_state("STA_TIMEOUT", wifi, status=last_status, attempt=attempt, ssid=ssid)
                try:
                    wifi.disconnect()
                except Exception:
                    pass
                try:
                    wifi.active(False)
                except Exception:
                    pass
                time.sleep(0.2)
            return False

        connected = False
        try:
            connected = wifi.isconnected()
        except Exception:
            connected = False

        if not connected:
            saved_ssid, saved_pass = load_saved_credentials()
            if saved_ssid:
                saved_failures = load_saved_failure_count()
                if saved_failures >= saved_fail_limit:
                    logger.warning(
                        f"[OTA-WIFI] saved creds skipped (failures={saved_failures} limit={saved_fail_limit})"
                    )
                else:
                    connected = _attempt_connect(saved_ssid, saved_pass, "saved", allow_scan=True)
                    if connected:
                        reset_saved_failure()
                    else:
                        increment_saved_failure()

            if not connected:
                connected = _attempt_connect(OTA_WIFI_SSID, OTA_WIFI_PASSWORD, "OTA", allow_scan=False)

        if connected:
            show_loader("Updating...")
            updater.check_and_perform_ota()
        else:
            logger.warning("WiFi not connected - OTA skipped")

    except Exception as e:
        if str(e) == "OTA not requested":
            logger.info("BOOT not held - skipping OTA check")
        else:
            logger.error(f"OTA check failed: {e}")
            show_loader("Update failed. Reverting...")

        # If the last reset happened mid-update, restore from backup without
        # attempting to talk to the server.
        try:
            if updater.read_text_file(updater.ota_state_file) == OTAState.INSTALLING:
                logger.warning("Incomplete OTA detected; reverting to backup.")
                updater.revert_update()
        except Exception as revert_e:
            logger.error(f"OTA revert check failed: {revert_e}")

_updater_kwargs = {
    "force_update": OTA_FORCED_UPDATE,
    "recurse_http_fs": OTA_MANIFEST_RECURSE_HTTP_FS,
    "http_timeout_s": int(getattr(config, "OTA_HTTP_TIMEOUT_S", 5)),
    "download_retries": int(getattr(config, "OTA_DOWNLOAD_RETRIES", 1)),
    "retry_base_delay_ms": int(getattr(config, "OTA_RETRY_BASE_DELAY_MS", 500)),
    "resume_downloads": bool(getattr(config, "OTA_RESUME_DOWNLOADS", False)),
    "io_chunk_size": int(getattr(config, "OTA_IO_CHUNK_SIZE", 512)),
    "md5_chunk_size": int(getattr(config, "OTA_MD5_CHUNK_SIZE", 512)),
    "strict_http_fs": bool(getattr(config, "OTA_STRICT_HTTP_FS", True)),
    "delete_files_not_in_manifest_policy": str(
        getattr(config, "OTA_DELETE_POLICY", "never")
    ),
    "delete_files_not_in_manifest_extensions": getattr(
        config, "OTA_DELETE_EXTENSIONS", None
    ),
}

updater = OTAUpdater(
    OTA_MANIFEST_URL,
    OTA_BASE_FILE_URL,
    **_updater_kwargs,
)


def _read_int_file(path, default=0):
    try:
        raw = updater.read_text_file(path)
    except Exception:
        raw = None
    if raw is None:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _clear_confirm_pending_counter():
    try:
        if updater.exists(OTA_CONFIRM_PENDING_COUNT_FILE):
            os.remove(OTA_CONFIRM_PENDING_COUNT_FILE)
    except Exception:
        # Non-fatal cleanup failure.
        pass


def _guard_confirm_pending_boot_loop():
    """
    Prevent infinite boot loops when update remains CONFIRM_PENDING.

    First boot in CONFIRM_PENDING is allowed so main can confirm.
    If we see CONFIRM_PENDING again on a subsequent boot, assume crash and revert.
    """
    try:
        state = updater.read_text_file(updater.ota_state_file)
    except Exception as e:
        logger.warning(f"[OTA] pending-state guard skipped: {e}")
        return

    if state != OTAState.CONFIRM_PENDING:
        _clear_confirm_pending_counter()
        return

    boots = _read_int_file(OTA_CONFIRM_PENDING_COUNT_FILE, default=0) + 1
    try:
        updater.write_text_file(OTA_CONFIRM_PENDING_COUNT_FILE, str(boots))
    except Exception as e:
        logger.warning(f"[OTA] failed to persist pending boot counter: {e}")

    logger.warning(
        f"[OTA] confirm_pending boot count={boots} (max={OTA_CONFIRM_PENDING_MAX_BOOTS})"
    )

    if boots > OTA_CONFIRM_PENDING_MAX_BOOTS:
        logger.error("[OTA] confirm_pending persisted across boots; reverting update")
        updater.revert_update()


_guard_confirm_pending_boot_loop()

# Minimal WiFi setup
wifi = network.WLAN(network.WLAN.IF_STA)

if not _HEADLESS_MODE:
    # Hardware Configuration - use centralized pin definitions
    # Explicitly convert to int to handle soft reboot edge cases where
    # module state may be corrupted
    PIN_TFT_RESET = int(config.PIN_TFT_RESET)
    PIN_TFT_DC = int(config.PIN_TFT_DC)
    PIN_TFT_CS = int(config.PIN_TFT_CS)
    PIN_TFT_MOSI = int(config.PIN_TFT_MOSI)
    PIN_TFT_SCK = int(config.PIN_TFT_SCK)
    PIN_TFT_LED = int(config.PIN_TFT_LED)

    # Clean up any residual SPI bus state from soft reboot
    # This prevents "can't convert str to int" errors when SPI bus has stale state
    try:
        # Try to deinit any existing display_bus if it exists in globals
        _old_bus = globals().get('display_bus')
        if _old_bus:
            _old_bus.deinit()
            del _old_bus
        spi_bus = machine.SPI.Bus(host=1, mosi=PIN_TFT_MOSI, sck=PIN_TFT_SCK)
    except Exception as e:
        # Pulse the TFT reset pin to ensure clean state before retrying SPI bus creation
        try:
            reset_pin = Pin(int(config.PIN_TFT_RESET), Pin.OUT)
            reset_pin.value(0)
            time.sleep(0.1)
            reset_pin.value(1)
            time.sleep(0.1)
        except Exception as reset_e:
            logger.error(f"TFT reset pulse failed: {reset_e}")
        try:
            spi_bus = machine.SPI.Bus(host=1, mosi=PIN_TFT_MOSI, sck=PIN_TFT_SCK)
        except Exception as spi_e:
            logger.error(f"SPI bus initialization failed: {spi_e}")
            time.sleep(1)
            machine.reset()

    display_bus = lcd_bus.SPIBus(spi_bus=spi_bus, freq=40000000, dc=PIN_TFT_DC, cs=PIN_TFT_CS)
    display = ili9341.ILI9341(
        data_bus=display_bus,
        display_width=config.DISPLAY_HEIGHT,
        display_height=config.DISPLAY_WIDTH,
        backlight_pin=PIN_TFT_LED,
        color_space=lv.COLOR_FORMAT.RGB565,
        color_byte_order=ili9341.BYTE_ORDER_BGR,
        rgb565_byte_swap=True
    )

    # Hardware reset pulse to ensure clean display state
    reset_pin = Pin(PIN_TFT_RESET, Pin.OUT)
    reset_pin.value(0)
    time.sleep(0.1)
    reset_pin.value(1)
    time.sleep(0.5)  # Wait for display to stabilize after reset

    display.set_power(True)
    display.init(1)
    time.sleep(0.3)  # Wait for display init to complete
    display.set_color_inversion(True)  # Fix color inversion in LVGL 9.4 binding
    display.set_rotation(lv.DISPLAY_ROTATION._90)  # 90 degrees
    display.set_backlight(100)

    # Start LVGL task handler so the display gets updated
    th = task_handler.TaskHandler()
    time.sleep(0.2)  # Give task handler time to start

    # ============================================================================
    # BOOT SEQUENCE (Both modes)
    # ============================================================================
    show_loader("Booting...")
    try:
        min_ms = int(getattr(config, "BOOT_VERSION_SPLASH_MS", 2000))
    except Exception:
        min_ms = 2000
    if min_ms > 0:
        try:
            time.sleep_ms(min_ms)
        except Exception:
            time.sleep(min_ms / 1000.0)

    # Run OTA setup - always continue even if this fails
    try:
        setup(updater=updater, wifi=wifi)
    except Exception as e:
        logger.error(f"Setup failed: {e}")

    try:
        updater.release()
    except Exception as e:
        logger.error(f"OTA release failed: {e}")
    updater = None

    # Cleanup WiFi - don't let failures block boot
    try:
        if wifi:
            wifi.disconnect()
            wifi.active(False)
    except Exception as e:
        logger.error(f"WiFi cleanup failed: {e}")
    wifi = None

# Cleanup display - don't let failures block boot (normal mode only)
if not _HEADLESS_MODE:
    try:
        if display_bus and spi_bus:
            display_bus.deinit()
            logger.info("SPI bus released")
    except Exception as e:
        logger.error(f"Display cleanup failed: {e}")
    try:
        display = None
        display_bus = None
        spi_bus = None
        th = None
    except Exception:
        pass

_purge_modules(
    prefixes=(
        "saguarota",
        "cactuscon.hw.wifi",
    ),
    keep=(
        "lvgl",
        "lcd_bus",
        "ili9341",
        "task_handler",
    ),
)

gc.collect()
logger.info("Boot complete - starting main application")
