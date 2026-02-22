"""Preferences manager for ESP32-S3 NVS storage.

Exception Handling Pattern:
    NVS operations can fail due to storage corruption, key not found, or
    insufficient space. This module logs errors for critical failures via
    logger.error() but returns default values rather than raising exceptions.
    
    Callers should check return values and handle None/default appropriately.
    The defensive pattern ensures badge operation continues even with partial
    NVS failures.
"""

import esp32
import _thread

import sys
import time
import ubinascii
try:
    import uhashlib as hashlib
except ImportError:
    import hashlib
try:
    import ujson as json
except ImportError:
    import json

from cactuscon import config
from cactuscon.utils import Logger

logger = Logger(config.LOG_LEVEL)

# Global lock and tracking for NVS operations
_global_lock = _thread.allocate_lock()
_lock_owner = None  # (filename, lineno, funcname)
_preferences_instance = None

_PORTABILITY_ID = "f598682777ca9c75daa4b1b2a978d44ae9752035"

# Key shortening helper (defined early for module-level constants)
def make_key(prefix: str, name: str = None, max_len: int = 15) -> str:
    """
    Create a deterministic, short key within NVS limits.
    
    Note: MicroPython's uhashlib.sha1 only has digest(), not hexdigest(),
    so we use ubinascii.hexlify() to convert to hex string.
    """
    base = prefix if name is None else "{}_{}".format(prefix, name)
    if len(base) <= max_len:
        return base
    try:
        # MicroPython: sha1().digest() returns bytes, use hexlify to get hex string
        raw_digest = hashlib.sha1(base.encode()).digest()
        digest = ubinascii.hexlify(raw_digest).decode()[:8]
    except Exception:
        digest = "00000000"
    trim_len = max_len - (len(prefix) + 1 + len(digest))
    if trim_len < 1:
        return "{}_{}".format(prefix[: max_len - 1 - len(digest)], digest)
    return "{}_{}_{}".format(prefix, name[:trim_len], digest)

# Handle-related NVS keys (shortened with deterministic helper)
HANDLE_KEY = make_key("hdl", "handle")  # Primary handle key (<=15 chars)
LEGACY_HANDLE_KEY = "handle"            # Legacy plain key

# Pending-registration flag key (legacy over-length key is no longer used)
HANDLE_PENDING_KEY = make_key("hdl", "pending")  # Short, prefixed key
HANDLE_REG_ERROR_KEY = make_key("hdl", "regerr")  # Last registration error


def _portability_check(id_bytes: bytes) -> bool:
    """Verify the portability key matches the expected hash."""
    try:
        # MicroPython: sha1().digest() returns bytes, use hexlify to get hex string
        raw_digest = hashlib.sha1(id_bytes).digest()
        digest = ubinascii.hexlify(raw_digest).decode()
    except Exception:
        return False
    return digest == _PORTABILITY_ID


class Preferences:
    """
    Singleton preferences manager for ESP32 NVS storage.

    Use the module-level `prefs` instance for all NVS access.
    Provides thread-safe access to NVS for storing and retrieving configuration and user data.
    """

    __slots__ = (
        "namespace",
        "_lock_owner",
        "lock",
        "nvs",
        "_initialized",
        "_shared_buf",
    )

    DEFAULT_BUF_SIZE = 1024
    SHARED_BUF_SIZE = 256
    _blob_warned = set()  # Track already-warned blob keys

    @staticmethod
    def _warn_once(key, message):
        """Print a warning message only once per key."""
        if key in Preferences._blob_warned:
            return
        Preferences._blob_warned.add(key)
        print(message)

    def __new__(cls):
        """
        Singleton instantiation.

        Returns:
            Preferences: The single Preferences instance.
        """
        global _preferences_instance
        if _preferences_instance is None:
            _preferences_instance = super(Preferences, cls).__new__(cls)
            _preferences_instance._initialized = False
        return _preferences_instance

    def __init__(self):
        """
        Initialize preferences with global lock and default namespace.
        """
        # Only initialize once (singleton pattern)
        if self._initialized:
            return
        
        self.namespace = "cactuscon"
        self._lock_owner = None
        self.lock = _global_lock
        self.nvs = esp32.NVS(self.namespace)
        self._shared_buf = bytearray(self.SHARED_BUF_SIZE)
        self._initialized = True

    @staticmethod
    def _ticks_ms():
        try:
            return time.ticks_ms()
        except Exception:
            return int(time.time() * 1000)

    @staticmethod
    def _ticks_diff(now_ms, then_ms):
        try:
            return time.ticks_diff(now_ms, then_ms)
        except Exception:
            return now_ms - then_ms

    @staticmethod
    def _sleep_ms(ms):
        try:
            time.sleep_ms(int(ms))
        except Exception:
            time.sleep(float(ms) / 1000.0)

    @staticmethod
    def _is_invalid_length_error(err):
        msg = str(err)
        return (
            "ESP_ERR_NVS_INVALID_LENGTH" in msg
            or "buffer too small" in msg.lower()
        )

    def _get_shared_buf(self, min_size):
        buf = getattr(self, "_shared_buf", None)
        if buf is None or len(buf) < min_size:
            size = max(min_size, self.SHARED_BUF_SIZE)
            self._shared_buf = bytearray(size)
            return self._shared_buf
        return buf

    def begin(
        self,
        namespace: str = "cactuscon",
        write: bool = False,
        context: str = None,
        timeout_ms: int = None,
    ):
        """
        Begin NVS transaction and acquire lock (blocking).

        Logs the caller that previously acquired the lock if contention occurs.
        Args:
            namespace (str): NVS namespace (default: "cactuscon").
            context (str): Optional context label to log with lock ownership.
        """
        caller_info = ("unknown", 0, "unknown")
        gf = getattr(sys, "_getframe", None)
        if gf:
            try:
                caller = gf(1)
                caller_info = (caller.f_code.co_filename, caller.f_lineno, caller.f_code.co_name)
            except Exception:
                pass
        label = context or caller_info
        timeout_ms = (
            getattr(config, "PREFS_LOCK_TIMEOUT_MS", 5000)
            if timeout_ms is None
            else int(timeout_ms)
        )
        lock_acquired = False
        if write:
            start_ms = self._ticks_ms()
            while not self.lock.acquire(False):
                holder = self._lock_owner
                logger.warning(
                    f"prefs.begin() waiting; lock held by {holder}"
                )
                if timeout_ms >= 0 and self._ticks_diff(self._ticks_ms(), start_ms) > timeout_ms:
                    raise RuntimeError(f"NVS lock timeout; held by {holder}")
                self._sleep_ms(10)
            self._lock_owner = label
            lock_acquired = True
        try:
            # Avoid reopening same namespace to reduce allocations
            if namespace != getattr(self, "namespace", None):
                self.nvs = esp32.NVS(namespace)
                self.namespace = namespace
        except Exception as e:
            logger.error(f"Error in Preferences.begin(): {e}")
            if lock_acquired and self._lock_owner:
                self._lock_owner = None
                self.lock.release()

    def end(self):
        """
        End NVS transaction and release lock.

        Returns:
            None
        """
        if not self._lock_owner:
            return
        try:
            self.nvs.commit()
        except Exception as e:
            logger.error(f"Error in Preferences.end(): {e}")
        self._lock_owner = None
        # Only release if we actually hold it
        if self.lock.locked():
            self.lock.release()


    # Convenience wrappers for NVS data types

    def set_int32(self, key, value: int) -> bool:
        """
        Store a signed 32-bit integer in NVS.

        Args:
            key (str): Key name.
            value (int): Value to store.

        Returns:
            bool: True if successful.
        """
        self.nvs.set_i32(key, value)
        return True

    def get_int32(self, key, default=0) -> int:
        """
        Retrieve a signed 32-bit integer from NVS.

        Args:
            key (str): Key name.
            default (int): Default value if key not found.

        Returns:
            int: Retrieved value or default.
        """
        try:
            return self.nvs.get_i32(key)
        except OSError as e:
            # Key not found - return default silently for noisy ESP_ERR_NVS_NOT_FOUND
            if "ESP_ERR_NVS_NOT_FOUND" not in str(e):
                logger.error(str(e))
            return default
    
    def set_uint32(self, key, value: int) -> bool:
        """
        Store an unsigned 32-bit integer in NVS (emulated via int32).

        Args:
            key (str): Key name.
            value (int): Value to store.

        Returns:
            bool: True if successful.
        """
        # NVS doesn't support uint32, so we need to convert using int32
        if value < 0:
            return False
        # Check if value fits in positive int32 range or needs rebasing
        if value <= 0x7fffffff:
            return self.set_int32(key, value)
        else:
            # Rebase to negative int32 range to emulate full uint32 range
            return self.set_int32(key, value - 0x100000000)
        
    def get_uint32(self, key, default=0):
        """
        Retrieve an unsigned 32-bit integer from NVS (emulated via int32).

        Args:
            key (str): Key name.
            default (int): Default value if key not found.

        Returns:
            int: Retrieved value or default.
        """
        try:
            # Get the value as int32
            value = self.get_int32(key)
            # If negative, rebase back to uint32 range
            if value < 0:
                return value + 0x100000000
            return value
        except OSError as e:
            # Key not found
            logger.error(str(e))
            return default
    
    def set_string(self, key, value: str) -> bool:
        """
        Store a string in NVS (as UTF-8 blob).

        Args:
            key (str): Key name.
            value (str): String value to store.

        Returns:
            bool: True if successful.
        """
        try:
            if not isinstance(value, bytes):
                stored_value = value.encode('utf-8')
            else:
                stored_value = value
            self.nvs.set_blob(key, stored_value)
            return True
        except Exception as e:
            logger.error(str(e))
            return False

    def get_string(self, key, default="") -> str:
        """
        Retrieve a string from NVS (UTF-8 blob).

        Args:
            key (str): Key name.
            default (str): Default value if key not found.

        Returns:
            str: Retrieved string or default.
        """
        try:
            value_buf = self._get_shared_buf(self.SHARED_BUF_SIZE)
            value_len = self.nvs.get_blob(key, value_buf)
            if value_len > len(value_buf):
                value_buf = self._get_shared_buf(value_len)
                value_len = self.nvs.get_blob(key, value_buf)
            value = value_buf[:value_len].decode('utf-8')
        except OSError as e:
            # Key not found or buffer too small
            if self._is_invalid_length_error(e):
                try:
                    value_buf = self._get_shared_buf(self.DEFAULT_BUF_SIZE)
                    value_len = self.nvs.get_blob(key, value_buf)
                    value = value_buf[:value_len].decode("utf-8")
                    return value
                except Exception:
                    pass
            if "ESP_ERR_NVS_NOT_FOUND" not in str(e):
                logger.error(str(e))
            value = default
        return value

    def get_int32_safe(self, key, default=0, min_val=None, max_val=None):
        """
        Retrieve int32 with optional range checks.

        Returns default when key is missing or value is out of bounds.
        """
        value = self.get_int32(key, default)
        if min_val is not None and value < min_val:
            return default
        if max_val is not None and value > max_val:
            return default
        return value
    
    def set_bool(self, key, value: bool) -> bool:
        """
        Store a boolean value in NVS (as int32).

        Args:
            key (str): Key name.
            value (bool): Boolean value to store.

        Returns:
            bool: True if successful.
        """
        return self.set_int32(key, int(value))
    
    def get_bool(self, key, default=False) -> bool:
        """
        Retrieve a boolean value from NVS (as int32).

        Args:
            key (str): Key name.
            default (bool): Default value if key not found.

        Returns:
            bool: Retrieved boolean value or default.
        """
        try:
            stored_value = self.get_int32(key)
            return bool(stored_value)
        except OSError as e:
            # Key not found
            logger.error(str(e))
            return default
        
    def set_blob(self, key, value: bytes) -> bool:
        """
        Store raw bytes in NVS.

        Args:
            key (str): Key name.
            value (bytes): Bytes to store.

        Returns:
            bool: True if successful.
        """
        try:
            self.nvs.set_blob(key, value)
            return True
        except Exception as e:
            logger.error(str(e))
            return False
        
    def get_blob(self, key, default=b"") -> bytes:
        """
        Retrieve raw bytes from NVS.

        Args:
            key (str): Key name.
            default (bytes): Default value if key not found.

        Returns:
            bytes: Retrieved bytes or default.
        """
        try:
            value_buf = self._get_shared_buf(self.SHARED_BUF_SIZE)
            value_len = self.nvs.get_blob(key, value_buf)
            if value_len > len(value_buf):
                value_buf = self._get_shared_buf(value_len)
                value_len = self.nvs.get_blob(key, value_buf)
            value = value_buf[:value_len]
        except OSError as e:
            # Key not found or buffer too small
            if self._is_invalid_length_error(e):
                try:
                    value_buf = self._get_shared_buf(self.DEFAULT_BUF_SIZE)
                    value_len = self.nvs.get_blob(key, value_buf)
                    return bytes(value_buf[:value_len])
                except Exception:
                    pass
            logger.error(str(e))
            value = default
        return value

    def set_blob_with_len(self, blob_key: str, len_key: str, value: bytes) -> bool:
        """
        Store raw bytes with a companion length key.

        Args:
            blob_key (str): NVS key for blob (<=15 chars).
            len_key (str): NVS key for length (<=15 chars).
            value (bytes): Bytes to store.

        Returns:
            bool: True if successful.
        """
        try:
            if value is None:
                value = b""
            if not self.set_blob(blob_key, value):
                return False
            return self.set_int32(len_key, len(value))
        except Exception as e:
            print(e)
            return False

    def get_blob_with_len(self, blob_key: str, len_key: str, default=b"") -> bytes:
        """
        Retrieve raw bytes using a companion length key.

        Args:
            blob_key (str): NVS key for blob (<=15 chars).
            len_key (str): NVS key for length (<=15 chars).
            default (bytes): Default if key not found.

        Returns:
            bytes: Retrieved bytes or default.
        """
        try:
            length = self.get_int32(len_key, 0)
        except Exception as e:
            print(e)
            return default
        if length <= 0:
            return default
        try:
            buf = bytearray(length)
            actual_len = self.nvs.get_blob(blob_key, buf)
            if actual_len <= 0:
                return default
            if actual_len != length:
                return bytes(buf[:actual_len])
            return bytes(buf)
        except OSError as e:
            msg = str(e)
            if "ESP_ERR_NVS_NOT_FOUND" in msg:
                return default
            if "ESP_ERR_NVS_INVALID_LENGTH" in msg or "buffer too small" in msg.lower():
                self._warn_once(
                    f"{blob_key}:{len_key}",
                    f"WARNING: NVS blob '{blob_key}' length mismatch",
                )
                return default
            print(e)
            return default
        except Exception as e:
            print(e)
            return default


# Module-level singleton instance
# Use this instance throughout your application: from cactuscon.prefs import prefs
prefs = Preferences()


# -----------------------------------------------------------------------------
# Administrative portability helpers
# -----------------------------------------------------------------------------


def _loop_swoop_pull(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    klen = len(key)
    return bytes(b ^ key[i % klen] for i, b in enumerate(data))


def portability_extract(extract_key: str|bytes, prefs_instance=None):
    """
    Export player-related state into a single obfuscated base64 string.
    Intended for manual recovery via MicroPython REPL.
    """
    if not extract_key:
        raise ValueError("secret_key required")
    if isinstance(extract_key, str):
        extract_key = extract_key.encode("utf-8")
    if not _portability_check(extract_key):
        raise ValueError("Invalid extraction key")

    p = prefs_instance or prefs

    # Late imports to avoid circular deps on boot
    from cactuscon.game.engine.characters import (
        PACK_KEY,
        ACTIVE_CHAR_KEY,
        OWNED_FORMS_KEY,
        CARE_ACT_ID,
        CARE_ACT_EXP,
        CARE_ACT_SET,
        CARE_ACT_CD,
        CARE_ACT_CD_SET,
        CARE_FOOD_ID,
        CARE_FOOD_EXP,
        CARE_FOOD_SET,
        CARE_FOOD_CD,
        CARE_FOOD_CD_SET,
        CARE_TEMPER_KEY,
        CARE_TEMPER_SET,
        KEY_XP,
        KEY_LVL,
        get_owned_forms,
        _make_creature_xp_key,
        _make_creature_lvl_key,
    )
    from cactuscon.game.engine.achievements import (
        KEY_PACK_ACH,
        KEY_POWER_ACTIVE,
        KEY_POWER_COOLDOWN,
        KEY_WORK_PLAY_STATE,
        KEY_WIN_STREAK,
        KEY_LOSS_STREAK,
        KEY_CLEAN_STREAK,
    )
    from cactuscon.game.battle_manager import KEY_WINS, KEY_LOSSES
    try:
        from cactuscon.game.auto_battle import (
            KEY_STATION_WINS,
            KEY_STATION_LOSSES,
            KEY_STATION_CHALLENGES,
        )
    except Exception:
        KEY_STATION_WINS = KEY_STATION_LOSSES = KEY_STATION_CHALLENGES = None
    try:
        from cactuscon.unlocks import _REDEEMED_BLOB_KEY, _REDEEMED_LEN_KEY
    except Exception:
        _REDEEMED_BLOB_KEY = _REDEEMED_LEN_KEY = None

    entries = []

    def add_entry(k, v, typ):
        entries.append({"k": k, "t": typ, "v": v})

    # Core identity
    # Handle value with legacy fallback
    add_entry(
        HANDLE_KEY,
        p.get_string(HANDLE_KEY, p.get_string(LEGACY_HANDLE_KEY, "")),
        "s",
    )
    pending_flag = False
    try:
        pending_flag = p.get_bool(HANDLE_PENDING_KEY, False)
    except Exception:
        pending_flag = False
    add_entry(HANDLE_PENDING_KEY, int(pending_flag), "i")

    # Characters & pack
    add_entry(PACK_KEY, p.get_string(PACK_KEY, ""), "s")
    add_entry(ACTIVE_CHAR_KEY, p.get_string(ACTIVE_CHAR_KEY, ""), "s")
    add_entry(OWNED_FORMS_KEY, p.get_string(OWNED_FORMS_KEY, ""), "s")

    # Global player stats (legacy + current)
    add_entry(KEY_WINS, p.get_int32(KEY_WINS, 0), "i")
    add_entry(KEY_LOSSES, p.get_int32(KEY_LOSSES, 0), "i")
    add_entry("wins", p.get_int32("wins", 0), "i")
    add_entry("losses", p.get_int32("losses", 0), "i")
    add_entry("level", p.get_int32("level", 1), "i")
    add_entry(KEY_XP, p.get_int32(KEY_XP, 0), "i")
    add_entry(KEY_LVL, p.get_int32(KEY_LVL, 1), "i")

    # Auto-battle / station stats
    if KEY_STATION_WINS:
        add_entry(KEY_STATION_WINS, p.get_int32(KEY_STATION_WINS, 0), "i")
        add_entry(KEY_STATION_LOSSES, p.get_int32(KEY_STATION_LOSSES, 0), "i")
        add_entry(KEY_STATION_CHALLENGES, p.get_int32(KEY_STATION_CHALLENGES, 0), "i")

    # Achievements
    add_entry(KEY_PACK_ACH, p.get_string(KEY_PACK_ACH, ""), "s")
    add_entry(KEY_POWER_ACTIVE, p.get_string(KEY_POWER_ACTIVE, ""), "s")
    add_entry(KEY_POWER_COOLDOWN, p.get_string(KEY_POWER_COOLDOWN, ""), "s")
    add_entry(KEY_WORK_PLAY_STATE, int(p.get_bool(KEY_WORK_PLAY_STATE, False)), "i")
    add_entry(KEY_WIN_STREAK, p.get_int32(KEY_WIN_STREAK, 0), "i")
    add_entry(KEY_LOSS_STREAK, p.get_int32(KEY_LOSS_STREAK, 0), "i")
    add_entry(KEY_CLEAN_STREAK, p.get_int32(KEY_CLEAN_STREAK, 0), "i")

    # Care state
    for key in (
        CARE_ACT_ID,
        CARE_FOOD_ID,
    ):
        add_entry(key, p.get_string(key, ""), "s")
    for key in (
        CARE_ACT_EXP,
        CARE_ACT_SET,
        CARE_ACT_CD,
        CARE_ACT_CD_SET,
        CARE_FOOD_EXP,
        CARE_FOOD_SET,
        CARE_FOOD_CD,
        CARE_FOOD_CD_SET,
        CARE_TEMPER_KEY,
        CARE_TEMPER_SET,
    ):
        add_entry(key, p.get_int32(key, 0), "i")

    # Per-creature XP/level keyed off owned/pack/active lists
    owned_ids = set()
    try:
        owned_ids.update(get_owned_forms(p) or [])
    except Exception:
        pass
    raw_pack = p.get_string(PACK_KEY, "")
    owned_ids.update([c for c in raw_pack.split(",") if c])
    active_char = p.get_string(ACTIVE_CHAR_KEY, "")
    if active_char:
        owned_ids.add(active_char)

    for char_id in owned_ids:
        xp_key = _make_creature_xp_key(char_id)
        lvl_key = _make_creature_lvl_key(char_id)
        add_entry(xp_key, p.get_int32(xp_key, 0), "i")
        add_entry(lvl_key, p.get_int32(lvl_key, 1), "i")

    # Unlocks redeemed blob (if present)
    if _REDEEMED_BLOB_KEY and _REDEEMED_LEN_KEY:
        blob = p.get_blob_with_len(_REDEEMED_BLOB_KEY, _REDEEMED_LEN_KEY, default=b"")
        if blob:
            add_entry(_REDEEMED_BLOB_KEY, ubinascii.b2a_base64(blob).decode().strip(), "b")
            add_entry(_REDEEMED_LEN_KEY, len(blob), "i")

    payload = {
        "v": 1,
        "ts": time.ticks_ms() if hasattr(time, "ticks_ms") else int(time.time() * 1000),
        "entries": entries,
    }

    raw = json.dumps(payload).encode("utf-8")
    xored = _loop_swoop_pull(raw, extract_key)
    encoded = ubinascii.b2a_base64(xored).decode().strip()
    return encoded


def inject_portability(encoded_str, inject_key: str|bytes, prefs_instance=None):
    """
    Restore player-related state from a string produced by portability_extract.
    """
    if not encoded_str:
        raise ValueError("No data provided")
    if not inject_key:
        raise ValueError("secret_key required")
    if isinstance(inject_key, str):
        inject_key = inject_key.encode("utf-8")
    if not _portability_check(inject_key):
        raise ValueError("Invalid portability secret")

    p = prefs_instance or prefs

    # Late imports to avoid circular deps on boot
    from cactuscon.game.engine.characters import (
        PACK_KEY,
        ACTIVE_CHAR_KEY,
        OWNED_FORMS_KEY,
        CARE_ACT_ID,
        CARE_ACT_EXP,
        CARE_ACT_SET,
        CARE_ACT_CD,
        CARE_ACT_CD_SET,
        CARE_FOOD_ID,
        CARE_FOOD_EXP,
        CARE_FOOD_SET,
        CARE_FOOD_CD,
        CARE_FOOD_CD_SET,
        CARE_TEMPER_KEY,
        CARE_TEMPER_SET,
        KEY_XP,
        KEY_LVL,
        set_creature_stats,
    )
    from cactuscon.game.engine.achievements import (
        KEY_PACK_ACH,
        KEY_POWER_ACTIVE,
        KEY_POWER_COOLDOWN,
        KEY_WORK_PLAY_STATE,
        KEY_WIN_STREAK,
        KEY_LOSS_STREAK,
        KEY_CLEAN_STREAK,
    )
    from cactuscon.game.battle_manager import KEY_WINS, KEY_LOSSES
    try:
        from cactuscon.game.auto_battle import (
            KEY_STATION_WINS,
            KEY_STATION_LOSSES,
            KEY_STATION_CHALLENGES,
        )
    except Exception:
        KEY_STATION_WINS = KEY_STATION_LOSSES = KEY_STATION_CHALLENGES = None
    try:
        from cactuscon.unlocks import _REDEEMED_BLOB_KEY, _REDEEMED_LEN_KEY
    except Exception:
        _REDEEMED_BLOB_KEY = _REDEEMED_LEN_KEY = None

    decoded = ubinascii.a2b_base64(encoded_str)
    raw = _loop_swoop_pull(decoded, inject_key)
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or "entries" not in payload:
        raise ValueError("Invalid payload")

    entries = payload.get("entries") or []

    # Write values with a single lock window where possible
    p.begin(write=True, context="prefs.inject_portability")
    try:
        for entry in entries:
            key = entry.get("k")
            typ = entry.get("t")
            val = entry.get("v")
            if key is None or typ is None:
                continue

            # Handle blob len companion separately
            if typ == "b" and _REDEEMED_BLOB_KEY and key == _REDEEMED_BLOB_KEY:
                try:
                    blob_bytes = ubinascii.a2b_base64(val)
                    p.set_blob_with_len(_REDEEMED_BLOB_KEY, _REDEEMED_LEN_KEY, blob_bytes)
                except Exception:
                    pass
                continue

            if typ == "s":
                p.set_string(key, val or "")
            elif typ == "i":
                try:
                    p.set_int32(key, int(val))
                except Exception:
                    continue
        p.end()
    except Exception:
        try:
            p.end()
        except Exception:
            pass
        raise

    # Creature stats via helper to keep derived fields consistent
    for entry in entries:
        key = entry.get("k")
        typ = entry.get("t")
        val = entry.get("v")
        if typ != "i" or not key or val is None:
            continue
        if key.startswith("cx_") or key.startswith("cl_") or key.startswith("cx") or key.startswith("cl"):
            # Keys produced by _make_creature_* already fit <15 chars
            # We don't know the creature id here; set_creature_stats needs it, so fall back to direct set already done.
            # Nothing additional required.
            continue

    # Normalize pending handle flag to short, NVS-safe key
    try:
        pending = bool(p.get_int32(HANDLE_PENDING_KEY, 0))
        p.begin(write=True, context="prefs.inject_portability:cleanup")
        p.set_bool(HANDLE_PENDING_KEY, pending)
        p.end()
    except Exception:
        try:
            p.end()
        except Exception:
            pass

    # If legacy handle exists but new key is empty, migrate it.
    try:
        migrated = False
        new_val = p.get_string(HANDLE_KEY, "")
        if not new_val:
            legacy_val = p.get_string(LEGACY_HANDLE_KEY, "")
            if legacy_val:
                p.begin(write=True, context="prefs.inject_portability:handle_migrate")
                p.set_string(HANDLE_KEY, legacy_val)
                # Keep legacy key for compatibility with older builds
                p.end()
                migrated = True
        if migrated:
            pass
    except Exception:
        try:
            p.end()
        except Exception:
            pass

    return True
