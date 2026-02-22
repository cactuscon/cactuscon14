"""WiFi connection management for ESP32-S3 badge."""

from cactuscon.utils import Logger
from cactuscon import config
logger = Logger(config.LOG_LEVEL)

# micropython
import asyncio
import network
import time

from cactuscon.prefs import prefs

WIFI_PERSIST_DEBUG = False
_WIFI_SAVED_FLAG_KEY = "wifi_saved"
_WIFI_SAVED_SSID_KEY = "wifi_ssid"
_WIFI_SAVED_PASS_KEY = "wifi_pass"
_WIFI_SAVED_FAIL_KEY = "wifi_fail"
_WIFI_LAST_SSID_KEY = "wifi_last_ssid"
_WIFI_LAST_PASS_KEY = "wifi_last_pass"

STAT_IDLE = getattr(network, "STAT_IDLE", 0)
STAT_CONNECTING = getattr(network, "STAT_CONNECTING", 1)
STAT_WRONG_PASSWORD = getattr(network, "STAT_WRONG_PASSWORD", -3)
STAT_NO_AP_FOUND = getattr(network, "STAT_NO_AP_FOUND", -2)
STAT_CONNECT_FAIL = getattr(network, "STAT_CONNECT_FAIL", -1)
STAT_GOT_IP = getattr(network, "STAT_GOT_IP", 3)


def _sleep_ms(ms):
    if ms <= 0:
        return
    if hasattr(time, "sleep_ms"):
        try:
            time.sleep_ms(int(ms))
            return
        except Exception:
            pass
    time.sleep(float(ms) / 1000.0)


def reset_wifi_stack(include_ap=False, settle_ms=250, bounce_sta=True):
    """
    Best-effort WiFi driver teardown/reset.

    Useful during boot or recovery paths after rapid resets where STA/AP state
    (association/DHCP) can remain in-flight briefly.
    """
    sta = None
    ap = None
    try:
        sta = network.WLAN(network.WLAN.IF_STA)
    except Exception:
        sta = None
    if include_ap:
        try:
            if hasattr(network.WLAN, "IF_AP"):
                ap = network.WLAN(network.WLAN.IF_AP)
        except Exception:
            ap = None

    for iface in (sta, ap):
        if not iface:
            continue
        try:
            iface.disconnect()
        except Exception:
            pass
        try:
            iface.active(False)
        except Exception:
            pass

    _sleep_ms(max(0, int(settle_ms)))

    if sta and bounce_sta:
        try:
            sta.active(True)
            try:
                # Supported on many ESP32 ports; harmless if unsupported.
                sta.ifconfig("dhcp")
            except Exception:
                pass
            _sleep_ms(120)
            try:
                sta.disconnect()
            except Exception:
                pass
        except Exception:
            pass
        try:
            sta.active(False)
        except Exception:
            pass


def _decode_ssid(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except Exception:
            try:
                return value.decode("latin-1")
            except Exception:
                return ""
    try:
        return str(value)
    except Exception:
        return ""


def _log_persist(message, ssid=None):
    if not WIFI_PERSIST_DEBUG:
        return
    if ssid:
        logger.info("[WIFI] {} ssid={}".format(message, ssid))
    else:
        logger.info("[WIFI] {}".format(message))


def load_saved_credentials():
    try:
        prefs.begin("cactuscon")
        saved = prefs.get_bool(_WIFI_SAVED_FLAG_KEY, False)
        ssid = prefs.get_string(_WIFI_SAVED_SSID_KEY, "")
        password = prefs.get_string(_WIFI_SAVED_PASS_KEY, "")
        last_ssid = prefs.get_string(_WIFI_LAST_SSID_KEY, "")
        last_password = prefs.get_string(_WIFI_LAST_PASS_KEY, "")
    except Exception as e:
        _log_persist("load saved credentials failed: {}".format(e))
        return (None, None)
    finally:
        try:
            prefs.end()
        except Exception:
            pass
    ssid = (ssid or "").strip()
    last_ssid = (last_ssid or "").strip()
    if saved and ssid:
        return (ssid, password)
    # Backward compatibility: older builds may have ssid/pass set without wifi_saved flag.
    if ssid:
        _log_persist("load saved credentials fallback (flag missing)", ssid=ssid)
        return (ssid, password)
    # Keep a reconnect target even if main saved creds were cleared.
    if last_ssid:
        _log_persist("load saved credentials fallback (last successful)", ssid=last_ssid)
        return (last_ssid, last_password)
    return (None, None)


def save_last_successful_credentials(ssid, password):
    if not ssid:
        return False
    try:
        prefs.begin("cactuscon", write=True, context="wifi.save_last_successful")
        prefs.set_string(_WIFI_LAST_SSID_KEY, ssid)
        prefs.set_string(_WIFI_LAST_PASS_KEY, password or "")
        prefs.end()
        _log_persist("saved last successful credentials", ssid=ssid)
        return True
    except Exception as e:
        _log_persist("save last successful credentials failed: {}".format(e), ssid=ssid)
        try:
            prefs.end()
        except Exception:
            pass
        return False


def save_credentials(ssid, password):
    if not ssid:
        return False
    try:
        prefs.begin("cactuscon", write=True, context="wifi.save_credentials")
        prefs.set_bool(_WIFI_SAVED_FLAG_KEY, True)
        prefs.set_string(_WIFI_SAVED_SSID_KEY, ssid)
        prefs.set_string(_WIFI_SAVED_PASS_KEY, password or "")
        prefs.set_string(_WIFI_LAST_SSID_KEY, ssid)
        prefs.set_string(_WIFI_LAST_PASS_KEY, password or "")
        prefs.end()
        _log_persist("saved credentials", ssid=ssid)
        return True
    except Exception as e:
        _log_persist("save credentials failed: {}".format(e), ssid=ssid)
        try:
            prefs.end()
        except Exception:
            pass
        return False


def clear_saved_credentials():
    try:
        prefs.begin("cactuscon", write=True, context="wifi.clear_credentials")
        prefs.set_bool(_WIFI_SAVED_FLAG_KEY, False)
        prefs.set_string(_WIFI_SAVED_SSID_KEY, "")
        prefs.set_string(_WIFI_SAVED_PASS_KEY, "")
        prefs.end()
        _log_persist("cleared credentials")
        return True
    except Exception as e:
        _log_persist("clear credentials failed: {}".format(e))
        try:
            prefs.end()
        except Exception:
            pass
        return False


def clear_last_successful_credentials():
    try:
        prefs.begin("cactuscon", write=True, context="wifi.clear_last_successful")
        prefs.set_string(_WIFI_LAST_SSID_KEY, "")
        prefs.set_string(_WIFI_LAST_PASS_KEY, "")
        prefs.end()
        _log_persist("cleared last successful credentials")
        return True
    except Exception as e:
        _log_persist("clear last successful credentials failed: {}".format(e))
        try:
            prefs.end()
        except Exception:
            pass
        return False


def load_saved_failure_count():
    try:
        prefs.begin("cactuscon")
        count = prefs.get_int32(_WIFI_SAVED_FAIL_KEY, 0)
    except Exception as e:
        _log_persist("load failure count failed: {}".format(e))
        return 0
    finally:
        try:
            prefs.end()
        except Exception:
            pass
    return count


def increment_saved_failure():
    count = 0
    try:
        prefs.begin("cactuscon", write=True, context="wifi.increment_failure")
        count = prefs.get_int32(_WIFI_SAVED_FAIL_KEY, 0) + 1
        prefs.set_int32(_WIFI_SAVED_FAIL_KEY, count)
        prefs.end()
        _log_persist("saved credentials failure count={}".format(count))
        return count
    except Exception as e:
        _log_persist("increment failure count failed: {}".format(e))
        try:
            prefs.end()
        except Exception:
            pass
        return count


def reset_saved_failure():
    try:
        prefs.begin("cactuscon", write=True, context="wifi.reset_failure")
        prefs.set_int32(_WIFI_SAVED_FAIL_KEY, 0)
        prefs.end()
        _log_persist("saved credentials failure count reset")
        return True
    except Exception as e:
        _log_persist("reset failure count failed: {}".format(e))
        try:
            prefs.end()
        except Exception:
            pass
        return False

class WiFiManager:
    """
    WiFi connection manager for ESP32-S3 badge.

    Handles connection, disconnection, status, and auto-reconnect logic for WiFi.
    Provides methods to retrieve link information and supports async polling for
    connection maintenance.
    """

    _instance = None
    __slots__ = (
        "logger",
        "wlan",
        "_initialized",
        "connecting",
        "_auto_reconnect",
        "_connect_started_ms",
        "_connect_timeout_s",
        "_last_snapshot",
        "_reconnect_backoff_ms",
        "_reconnect_backoff_max_ms",
        "_next_reconnect_ms",
        "_reconnect_attempts",
        "_missing_ssid_logged",
        "_busy_since_ms",
        "_last_attempt_source",
        "_last_attempt_ssid",
        "_last_attempt_password",
        "_auto_target_preference",
        "_last_error",
        "_last_scan_ms",
        "_networks",
        "_connect_active",
        "_connect_session_ssid",
        "_connect_session_password",
        "_connect_session_timeout_ms",
        "_connect_last_status",
    )

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(WiFiManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    @classmethod
    def get_instance(cls):
        """Return the shared WiFiManager singleton instance."""
        return cls()

    def __init__(self):
        """
        Initialize the WiFiManager and set up the WLAN interface.
        """
        if self._initialized:
            return
        self.logger = Logger(config.LOG_LEVEL)
        self.wlan = network.WLAN(network.WLAN.IF_STA)
        self.connecting = False
        self._auto_reconnect = True  # Enable auto-reconnect by default
        self._connect_started_ms = None
        self._connect_timeout_s = getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
        self._last_snapshot = None
        self._reconnect_backoff_ms = getattr(config, "WIFI_RECONNECT_BACKOFF_MS", 1000)
        self._reconnect_backoff_max_ms = getattr(config, "WIFI_RECONNECT_BACKOFF_MAX_MS", 15000)
        self._next_reconnect_ms = 0
        self._reconnect_attempts = 0
        self._missing_ssid_logged = False
        self._busy_since_ms = None
        self._last_attempt_source = None
        self._last_attempt_ssid = None
        self._last_attempt_password = None
        self._auto_target_preference = "saved"
        # UI/flow-facing state (shared with panel code; no separate controller).
        self._last_error = None
        self._last_scan_ms = None
        self._networks = []
        self._connect_active = False
        self._connect_session_ssid = None
        self._connect_session_password = None
        self._connect_session_timeout_ms = None
        self._connect_last_status = None
        self._initialized = True

    def _now_ms(self):
        if hasattr(time, "ticks_ms"):
            return time.ticks_ms()
        return int(time.time() * 1000)

    def _elapsed_ms(self, start_ms):
        if start_ms is None:
            return 0
        if hasattr(time, "ticks_diff"):
            return time.ticks_diff(self._now_ms(), start_ms)
        return self._now_ms() - start_ms

    def _log_snapshot(self, reason, force=False):
        snapshot = self.get_status_snapshot()
        if not force and snapshot == self._last_snapshot:
            return
        self._last_snapshot = snapshot
        self.logger.info(
            "[WIFI] {reason}: connected={connected} ssid={ssid} ip={ip} status={status} "
            "auto_reconnect={auto_reconnect} active={active}".format(
                reason=reason,
                connected=snapshot.get("is_connected"),
                ssid=snapshot.get("ssid"),
                ip=snapshot.get("ip"),
                status=snapshot.get("status"),
                auto_reconnect=snapshot.get("auto_reconnect"),
                active=snapshot.get("active"),
            )
        )

    def _status_is_connecting(self, status):
        if status is None:
            return False
        try:
            if status == getattr(network, "STAT_CONNECTING", 1):
                return True
        except Exception:
            pass
        # Common ESP32 build returns 1001 for connecting.
        if status in (1, 1001):
            return True
        return False

    def _status_is_connecting_error(self, exc):
        if exc is None:
            return False
        try:
            msg = str(exc).lower()
            if ("connecting" in msg) or ("internal error" in msg):
                return True
        except Exception:
            pass
        return False

    def _safe_status(self):
        try:
            return self.wlan.status()
        except Exception:
            return None

    def _radio_cycle(self, down_ms=120, up_ms=160):
        try:
            self.wlan.active(False)
        except Exception:
            pass
        _sleep_ms(down_ms)
        try:
            self.wlan.active(True)
        except Exception:
            pass
        _sleep_ms(up_ms)

    def _prepare_radio_for_scan(self):
        try:
            self.cancel_connect("wifi scan", force_radio=True)
            _sleep_ms(140)
        except Exception:
            pass
        status = self._safe_status()
        if self._status_is_connecting(status):
            try:
                self.wlan.disconnect()
            except Exception:
                pass
            _sleep_ms(140)
            if self._status_is_connecting(self._safe_status()):
                self._radio_cycle(down_ms=140, up_ms=180)

    def _normalize_scan(self, raw_results):
        by_ssid = {}
        for entry in raw_results or []:
            try:
                ssid_raw = entry[0]
                rssi = entry[3] if len(entry) > 3 else None
                authmode = entry[4] if len(entry) > 4 else None
                hidden = entry[5] if len(entry) > 5 else None
            except Exception:
                continue

            ssid = _decode_ssid(ssid_raw)
            if not ssid:
                ssid = "<hidden>"

            try:
                rssi_val = int(rssi)
            except Exception:
                rssi_val = -999

            candidate = {
                "ssid": ssid,
                "rssi": rssi_val,
                "authmode": authmode,
                "hidden": hidden,
                "raw": entry,
            }
            existing = by_ssid.get(ssid)
            if (existing is None) or (rssi_val > existing.get("rssi", -999)):
                by_ssid[ssid] = candidate

        networks = list(by_ssid.values())
        networks.sort(key=lambda item: item.get("rssi", -999), reverse=True)
        return networks

    def _status_reason(self, status):
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

    def get_last_error(self):
        return self._last_error

    def get_last_scan_ms(self):
        return self._last_scan_ms

    def get_networks(self):
        return list(self._networks)

    def _driver_reset(self, reason="reset"):
        try:
            self.wlan.disconnect()
        except Exception:
            pass
        try:
            self.wlan.active(False)
        except Exception:
            pass
        try:
            time.sleep(0.2)
        except Exception:
            pass
        try:
            self.wlan.active(True)
        except Exception:
            pass
        print(f"[WIFI] driver reset ({reason})")

    async def _driver_reset_async(self, reason="reset"):
        """
        Async-safe variant to avoid blocking the event loop during driver recovery.
        """
        try:
            self.wlan.disconnect()
        except Exception:
            pass
        try:
            self.wlan.active(False)
        except Exception:
            pass
        await asyncio.sleep(0.2)
        try:
            self.wlan.active(True)
        except Exception:
            pass
        print(f"[WIFI] driver reset ({reason})")

    def _clear_last_attempt(self):
        self._last_attempt_source = None
        self._last_attempt_ssid = None
        self._last_attempt_password = None

    def _set_last_attempt(self, source, ssid, password):
        self._last_attempt_source = source
        self._last_attempt_ssid = ssid
        self._last_attempt_password = password or ""

    def _choose_auto_target(self):
        saved_ssid, saved_pass = load_saved_credentials()
        ota_ssid = getattr(config, "OTA_WIFI_SSID", None)
        ota_pass = getattr(config, "OTA_WIFI_PASSWORD", None)

        if saved_ssid and ota_ssid and (saved_ssid != ota_ssid):
            if self._auto_target_preference == "ota":
                return ("ota", ota_ssid, ota_pass)
            return ("saved", saved_ssid, saved_pass)
        if saved_ssid:
            return ("saved", saved_ssid, saved_pass)
        if ota_ssid:
            return ("ota", ota_ssid, ota_pass)
        return ("none", None, None)

    def _note_connect_failure(self, reason=None):
        source = self._last_attempt_source
        if source == "saved":
            if reason in ("timeout", "connect error"):
                increment_saved_failure()
            self._auto_target_preference = "ota"
        elif source == "ota":
            self._auto_target_preference = "saved"

    def _note_connect_success(self):
        source = self._last_attempt_source
        ssid = self._last_attempt_ssid
        password = self._last_attempt_password
        if ssid:
            save_last_successful_credentials(ssid, password)
        if source == "saved":
            reset_saved_failure()
        # Prefer user/saved creds on future reconnect attempts.
        self._auto_target_preference = "saved"

    def connect(
        self,
        ssid=None,
        password=None,
        timeout_s=None,
        force=False,
        enable_auto_reconnect=True,
    ):
        """
        Connect to a WiFi network.

        Args:
            ssid (str): WiFi SSID to connect to.
            password (str): WiFi password.

        Returns:
            bool: True if connection is active/already connected, False otherwise.
        """
        self._last_error = None
        source = "manual"
        if ssid is None:
            source, ssid, auto_password = self._choose_auto_target()
            if password is None:
                password = auto_password
        if timeout_s is None:
            timeout_s = getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
        self._auto_reconnect = bool(enable_auto_reconnect)

        if self.connecting and not force:
            return True
        if self.connecting and force:
            self.cancel_connect("force reconnect")

        if not ssid:
            self._clear_last_attempt()
            if not self._missing_ssid_logged:
                print("[WIFI] connect skipped: no SSID available")
                self._missing_ssid_logged = True
            if self._auto_reconnect:
                self._schedule_reconnect("no ssid", delay_ms=5000)
            self._last_error = "no ssid"
            return False

        try:
            status = self.wlan.status()
        except Exception:
            status = None
        if self._status_is_connecting(status) and not force:
            self._set_last_attempt(source, ssid, password)
            self._note_connect_failure("driver connecting")
            if self._auto_reconnect:
                self._schedule_reconnect("driver busy")
            self._clear_last_attempt()
            self._last_error = "driver busy"
            return False
        if self._status_is_connecting(status) and force:
            self._driver_reset("force connect")

        self.connecting = True
        self._set_last_attempt(source, ssid, password)
        self._connect_timeout_s = timeout_s
        self._connect_started_ms = self._now_ms()
        self.wlan.active(True)
        if self.is_connected():
            self.connecting = False
            self._connect_started_ms = None
            current_ssid = None
            try:
                current_ssid = self.get_ssid()
            except Exception:
                current_ssid = None
            if (not ssid) or (current_ssid == ssid):
                self._note_connect_success()
            elif current_ssid:
                save_last_successful_credentials(current_ssid, "")
            self._clear_last_attempt()
            self._log_snapshot("connect: already connected")
            self._reset_reconnect_backoff()
            return True
        self.logger.info("[WIFI] connect: starting")
        try:
            if password is None:
                self.wlan.connect(ssid)
            else:
                self.wlan.connect(ssid, password)
            return True
        except Exception as e:
            err_text = str(e).lower()
            status_after = None
            try:
                status_after = self.wlan.status()
            except Exception:
                status_after = None
            if ("internal error" in err_text) or self._status_is_connecting(status_after):
                # Treat busy STA driver as transient and retry soon.
                self.connecting = False
                self._connect_started_ms = None
                self._note_connect_failure("driver busy")
                if self._auto_reconnect:
                    self._schedule_reconnect("driver busy")
                self._clear_last_attempt()
                self.logger.warning(f"[WIFI] connect deferred: {e}")
                self._last_error = "driver busy"
                return False
            self.logger.error(f"[WIFI] connect error: {e}")
            # Some ports throw transient "internal error" while the station is
            # already mid-connect; keep connecting state and let timeout logic
            # in loop() resolve it.
            try:
                if self.wlan.active() and not self.is_connected():
                    return True
            except Exception:
                pass
            self.connecting = False
            self._connect_started_ms = None
            self._note_connect_failure("connect error")
            self._driver_reset("connect error")
            if self._auto_reconnect:
                self._schedule_reconnect("connect error")
            self._clear_last_attempt()
            self._last_error = "connect error"
            return False

    def scan(self):
        """
        Scan for nearby WiFi networks.

        Returns:
            list: Raw scan results from network.WLAN.scan().
        """
        try:
            self.wlan.active(True)
            return self.wlan.scan()
        except Exception as e:
            self.logger.error(f"[WIFI] scan error: {e}")
            return []

    def refresh_scan(self):
        """
        Scan and return normalized/sorted SSID entries for UI use.
        """
        self._last_error = None
        self._prepare_radio_for_scan()
        raw = None
        last_exc = None
        for attempt in range(3):
            try:
                self.wlan.active(True)
                raw = self.wlan.scan()
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                status = self._safe_status()
                if self._status_is_connecting_error(exc) or self._status_is_connecting(status):
                    try:
                        self.wlan.disconnect()
                    except Exception:
                        pass
                    if attempt >= 1:
                        self._radio_cycle(down_ms=140, up_ms=180)
                    _sleep_ms(180)
                    continue
                break
        if last_exc is not None:
            self._networks = []
            self._last_error = "scan failed: {}".format(last_exc)
            self.logger.warning(f"[WIFI] {self._last_error}")
            return self._networks
        self._networks = self._normalize_scan(raw)
        self._last_scan_ms = self._now_ms()
        return self._networks

    def scan_networks(self):
        """
        Alias for refresh_scan(), preferred by UI flow.
        """
        return self.refresh_scan()

    def start_connect(self, ssid, password, timeout_s=15):
        """
        Start an explicit user-driven connect attempt that can be polled by UI.
        """
        self._last_error = None
        self._connect_last_status = None
        if not ssid:
            self._connect_active = False
            self._last_error = "wlan unavailable"
            return False

        timeout_s = timeout_s if timeout_s is not None else getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
        self._connect_session_ssid = ssid
        self._connect_session_password = password or ""
        self._connect_session_timeout_ms = int(float(timeout_s) * 1000)

        started = self.connect(
            ssid=ssid,
            password=password,
            timeout_s=timeout_s,
            force=True,
            enable_auto_reconnect=False,
        )
        if not started and not self.is_connected():
            self._connect_active = False
            if not self._last_error:
                self._last_error = "connect failed"
            return False
        self._connect_active = True
        return True

    def poll_connect(self):
        """
        Poll current explicit connect attempt state for UI timers.

        Returns:
            dict: {"state": "idle|connecting|success|fail", ...}
        """
        if not self._connect_active:
            return {"state": "idle"}

        if self.is_connected():
            self._connect_active = False
            self._connect_last_status = STAT_GOT_IP
            return {"state": "success", "reason": "got_ip"}

        status = self._safe_status()
        self._connect_last_status = status
        if status == STAT_GOT_IP:
            self._connect_active = False
            return {"state": "success", "reason": "got_ip"}
        if status in (STAT_WRONG_PASSWORD, STAT_NO_AP_FOUND, STAT_CONNECT_FAIL):
            self._connect_active = False
            reason = self._status_reason(status)
            self._last_error = reason
            return {"state": "fail", "reason": reason}

        timeout_ms = self._connect_session_timeout_ms
        if timeout_ms is None and self._connect_timeout_s is not None:
            timeout_ms = int(float(self._connect_timeout_s) * 1000)
        elapsed = self._elapsed_ms(self._connect_started_ms)
        if timeout_ms is not None and elapsed >= timeout_ms:
            self.cancel_connect("timeout")
            self._connect_active = False
            self._last_error = "timeout"
            return {"state": "fail", "reason": "timeout"}

        if (not self.connecting) and (not self._status_is_connecting(status)):
            self._connect_active = False
            self._last_error = "connect_fail"
            return {"state": "fail", "reason": "connect_fail"}

        return {"state": "connecting", "status": status}

    def wait_for_connect(self, timeout_s=None, poll_interval_ms=100, progress_callback=None):
        """
        Blockingly wait for WiFi connect completion while keeping manager state fresh.

        Intended for synchronous UI flows that must gate network calls.

        Args:
            timeout_s: Optional timeout in seconds.
            poll_interval_ms: Poll cadence in milliseconds.
            progress_callback: Optional callback invoked each poll.

        Returns:
            bool: True when connected, else False.
        """
        if self.is_connected():
            return True

        timeout_s = (
            getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)
            if timeout_s is None
            else timeout_s
        )
        timeout_ms = max(0, int(float(timeout_s) * 1000))
        interval_ms = max(10, int(poll_interval_ms))
        start_ms = self._now_ms()

        while not self.is_connected():
            # Drive connection watchdog/backoff during waits.
            try:
                self.loop()
            except Exception:
                pass
            if progress_callback:
                try:
                    progress_callback()
                except Exception:
                    pass
            if self._elapsed_ms(start_ms) >= timeout_ms:
                break
            _sleep_ms(interval_ms)
        return self.is_connected()

    def set_auto_reconnect(self, enabled: bool):
        """Enable or disable auto-reconnect behavior."""
        self._auto_reconnect = bool(enabled)

    def get_auto_reconnect(self):
        """Return current auto-reconnect setting."""
        return bool(self._auto_reconnect)

    def cancel_connect(self, reason="cancelled", force_radio=False):
        """
        Cancel a pending connection attempt and keep auto-reconnect state.
        """
        was_connecting = bool(self.connecting)
        self.connecting = False
        self._connect_started_ms = None
        self._connect_active = False
        self._connect_session_ssid = None
        self._connect_session_password = None
        self._connect_session_timeout_ms = None
        self._connect_last_status = None
        should_drop_radio = bool(force_radio)
        if not should_drop_radio:
            try:
                should_drop_radio = self._status_is_connecting(self.wlan.status())
            except Exception:
                should_drop_radio = False
        if should_drop_radio:
            try:
                self.wlan.disconnect()
            except Exception:
                pass
        if was_connecting or should_drop_radio:
            self._log_snapshot(f"connect: {reason}", force=True)
        if reason == "timeout" and self._auto_reconnect:
            self._note_connect_failure("timeout")
            self._schedule_reconnect("timeout")
        self._clear_last_attempt()

    def disconnect(self):
        """
        Disconnect from WiFi and disable auto-reconnect.
        """
        self.connecting = False
        self._auto_reconnect = False  # Disable auto-reconnect
        self._connect_active = False
        self._connect_session_ssid = None
        self._connect_session_password = None
        self._connect_session_timeout_ms = None
        self._connect_last_status = None
        self.wlan.disconnect()
        self.wlan.active(False)
        self._connect_started_ms = None
        self._clear_last_attempt()
        self._log_snapshot("disconnect", force=True)
        self._reset_reconnect_backoff()

    def is_connected(self):
        """
        Check if the device is currently connected to WiFi.

        Returns:
            bool: True if connected, False otherwise.
        """
        return self.wlan.isconnected()

    def get_ip(self):
        """
        Get the current IP address.

        Returns:
            str: IP address.
        """
        return self.wlan.ifconfig()[0]

    def get_mac(self):
        """
        Get the MAC address of the WiFi interface.

        Returns:
            bytes: MAC address.
        """
        return self.wlan.config('mac')

    def get_mac_string(self, uppercase=False):
        """
        Get MAC address as colon-delimited hex string.
        """
        try:
            mac = self.get_mac()
        except Exception:
            return None
        if not mac:
            return None
        if uppercase:
            return ":".join(["{:02X}".format(b) for b in mac])
        return ":".join(["{:02x}".format(b) for b in mac])

    def load_saved_credentials(self):
        return load_saved_credentials()

    def save_credentials(self, ssid, password):
        return save_credentials(ssid, password)

    def clear_saved_credentials(self):
        return clear_saved_credentials()

    def save_last_successful_credentials(self, ssid, password):
        return save_last_successful_credentials(ssid, password)

    def clear_last_successful_credentials(self):
        return clear_last_successful_credentials()

    def load_saved_failure_count(self):
        return load_saved_failure_count()

    def increment_saved_failure(self):
        return increment_saved_failure()

    def reset_saved_failure(self):
        return reset_saved_failure()

    def forget_saved_credentials(self):
        ok1 = self.clear_saved_credentials()
        ok2 = self.clear_last_successful_credentials()
        return bool(ok1 and ok2)

    def get_ssid(self):
        """
        Get the SSID of the connected network.

        Returns:
            str: SSID.
        """
        return self.wlan.config('essid')

    def get_rssi(self):
        """
        Get the current RSSI (signal strength).

        Returns:
            int: RSSI value in dBm.
        """
        return self.wlan.status('rssi')

    def get_channel(self):
        """
        Get the current WiFi channel.

        Returns:
            int: Channel number.
        """
        return self.wlan.status('channel')

    def get_bssid(self):
        """
        Get the BSSID (MAC address of the access point).

        Returns:
            bytes: BSSID.
        """
        return self.wlan.status('bssid')

    def get_authmode(self):
        """
        Get the authentication mode of the current connection.

        Returns:
            int: Auth mode.
        """
        return self.wlan.status('authmode')

    def get_link_info(self):
        """
        Get a dictionary of current link information.

        Returns:
            dict: Link info including IP, MAC, SSID, RSSI, channel, BSSID, and authmode.
        """
        return {
            "ip": self.get_ip(),
            "mac": self.get_mac(),
            "ssid": self.get_ssid(),
            "rssi": self.get_rssi(),
            "channel": self.get_channel(),
            "bssid": self.get_bssid(),
            "authmode": self.get_authmode()
        }

    def get_status_snapshot(self):
        """
        Return a snapshot of current WiFi status for logging/UI.
        """
        snapshot = {
            "is_connected": False,
            "connecting": bool(self.connecting),
            "ssid": None,
            "ip": None,
            "status": None,
            "auto_reconnect": self._auto_reconnect,
            "active": None,
        }
        try:
            snapshot["active"] = self.wlan.active()
        except Exception:
            pass
        try:
            snapshot["is_connected"] = self.is_connected()
        except Exception:
            pass
        if snapshot["is_connected"]:
            try:
                snapshot["ssid"] = self.get_ssid()
            except Exception:
                pass
            try:
                snapshot["ip"] = self.get_ip()
            except Exception:
                pass
        try:
            snapshot["status"] = self.wlan.status()
        except Exception:
            pass
        return snapshot

    def ensure_connected(
        self,
        timeout_s=None,
        wait=False,
        poll_interval_ms=100,
        progress_callback=None,
        force=False,
        enable_auto_reconnect=True,
    ):
        """
        Ensure WiFi connect has been initiated (and optionally wait until connected).

        This is the shared entrypoint for app + panel code that needs network access.
        """
        if self.is_connected():
            return True

        snapshot = self.get_status_snapshot()
        if (not snapshot.get("connecting")) or force:
            self.connect(
                timeout_s=timeout_s,
                force=force,
                enable_auto_reconnect=enable_auto_reconnect,
            )
        if wait:
            return self.wait_for_connect(
                timeout_s=timeout_s,
                poll_interval_ms=poll_interval_ms,
                progress_callback=progress_callback,
            )
        return self.is_connected()

    def pause_background_reconnect(self, reason="ui pause", force_radio=True):
        """
        Pause auto-reconnect + pending connect attempts for temporary UI ownership.

        Returns:
            bool: Previous auto-reconnect state, for later resume.
        """
        previous = bool(self.get_auto_reconnect())
        self.set_auto_reconnect(False)
        try:
            self.cancel_connect(reason, force_radio=force_radio)
        except Exception:
            pass
        return previous

    def resume_background_reconnect(self, previous_auto_reconnect=True, reconnect_if_needed=False):
        """
        Resume auto-reconnect state previously returned by pause_background_reconnect().
        """
        self.set_auto_reconnect(bool(previous_auto_reconnect))
        if reconnect_if_needed and bool(previous_auto_reconnect):
            self.ensure_connected(wait=False, enable_auto_reconnect=True)

    def _schedule_reconnect(self, reason=None, delay_ms=None):
        if delay_ms is None:
            self._reconnect_attempts += 1
            delay_ms = min(
                self._reconnect_backoff_ms * (2 ** (self._reconnect_attempts - 1)),
                self._reconnect_backoff_max_ms,
            )
        else:
            self._reconnect_attempts = 0
        self._next_reconnect_ms = self._now_ms() + int(delay_ms)
        if reason:
            print(f"[WIFI] reconnect scheduled in {int(delay_ms)}ms ({reason})")

    def _reset_reconnect_backoff(self):
        self._reconnect_attempts = 0
        self._next_reconnect_ms = 0
        self._missing_ssid_logged = False
        self._busy_since_ms = None

    def mark_connected(self, reason="init"):
        self.connecting = False
        self._connect_started_ms = None
        self._connect_active = False
        self._connect_session_ssid = None
        self._connect_session_password = None
        self._connect_session_timeout_ms = None
        self._connect_last_status = STAT_GOT_IP
        self._note_connect_success()
        self._clear_last_attempt()
        self._log_snapshot(f"connect: {reason}", force=True)
        self._reset_reconnect_backoff()

    async def loop(self):
        """
        Periodically check WiFi connection and auto-reconnect if needed.

        Intended to be called in an asyncio event loop.
        """
        try:
            if self.connecting:
                if self.is_connected():
                    self.connecting = False
                    self._connect_started_ms = None
                    self._note_connect_success()
                    self._clear_last_attempt()
                    self._log_snapshot("connected", force=True)
                    self._reset_reconnect_backoff()
                elif self._connect_started_ms is not None:
                    elapsed = self._elapsed_ms(self._connect_started_ms)
                    if elapsed >= int(self._connect_timeout_s * 1000):
                        self.cancel_connect("timeout")

            if (not self.is_connected()) and (not self.connecting) and self._auto_reconnect:
                now_ms = self._now_ms()
                if self._next_reconnect_ms and now_ms < self._next_reconnect_ms:
                    await asyncio.sleep(0)
                    return
                try:
                    status = self.wlan.status()
                except Exception:
                    status = None
                if self._status_is_connecting(status):
                    if self._busy_since_ms is None:
                        self._busy_since_ms = now_ms
                    elif (now_ms - self._busy_since_ms) >= int(self._connect_timeout_s * 1000):
                        await self._driver_reset_async("stuck connecting")
                        self._busy_since_ms = None
                    self._schedule_reconnect("driver connecting")
                    await asyncio.sleep(0)
                    return
                self._busy_since_ms = None
                self._log_snapshot("auto-reconnect: attempting", force=True)
                self.connect()
            await asyncio.sleep(0)
        except Exception as e:
            self.logger.error(f"[WIFI] loop error: {e}")

    async def loop_forever(self):
        """
        Continuously run the WiFi connection loop for background maintenance.
        """
        while True:
            await self.loop()
            await asyncio.sleep(0.05)
