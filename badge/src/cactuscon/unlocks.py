"""Unlock code registry and redemption helpers."""

try:
    import uhashlib as hashlib
except ImportError:  # Fallback for non-MicroPython tooling
    import hashlib
import ubinascii
import time

from cactuscon.utils import Logger
from cactuscon import config
from cactuscon.prefs import prefs
from cactuscon.game.engine.achievements import Achievements


_LOG = Logger(config.LOG_LEVEL)

# Not a secret; reduces simple rainbow lookups for plaintext codes.
HASH_VERSION = 1
HASH_ALGO = "sha256"
_SALT = b"CC14:"

ENABLE_REDEEM_STORE = getattr(config, "ENABLE_UNLOCK_REDEEM_STORE", True)
RL_ENABLED = getattr(config, "UNLOCK_RL_ENABLED", True)
RL_MIN_INTERVAL_S = getattr(config, "UNLOCK_RL_MIN_INTERVAL_S", 0.6)
RL_FAIL_THRESHOLD = getattr(config, "UNLOCK_RL_FAIL_THRESHOLD", 5)
RL_LOCKOUT_BASE_S = getattr(config, "UNLOCK_RL_LOCKOUT_BASE_S", 10)
RL_LOCKOUT_MAX_S = getattr(config, "UNLOCK_RL_LOCKOUT_MAX_S", 60)

_REDEEMED = None
_REDEEMED_LIST = None
_REDEEMED_LOADED = False
_WARNED = set()

# NVS keys (<=15 chars)
_REDEEMED_BLOB_KEY = "ul_rb"
_REDEEMED_LEN_KEY = "ul_rbl"

# Rate limit state (RAM only)
_rl_last_attempt_ms = None
_rl_fail_count = 0
_rl_lockout_until_ms = None
_rl_lockout_level = 0


def _normalize_code(code_str):
    """Normalize unlock code input for hashing."""
    if code_str is None:
        return ""
    if not isinstance(code_str, str):
        try:
            code_str = code_str.decode()
        except Exception:
            code_str = str(code_str)
    code_str = code_str.strip()
    if code_str:
        code_str = code_str.upper()
    return code_str


def _digest_normalized(normalized_code):
    """Return SHA-256 digest bytes for a normalized code string."""
    if not normalized_code:
        return b""
    hasher = hashlib.sha256()
    hasher.update(_SALT)
    hasher.update(normalized_code.encode())
    return hasher.digest()


def _verify_digest(digest_bytes, normalized):
    """Re-hash normalized code and compare with expected digest bytes."""
    if not digest_bytes or not normalized:
        return False
    return digest_bytes == _digest_normalized(normalized)


def _warn_once(key, message):
    if key in _WARNED:
        return
    _WARNED.add(key)
    _LOG.warning(message)


def _load_redeemed_if_needed():
    global _REDEEMED, _REDEEMED_LIST, _REDEEMED_LOADED
    if _REDEEMED_LOADED:
        return
    _REDEEMED = set()
    _REDEEMED_LIST = []
    _REDEEMED_LOADED = True
    if not ENABLE_REDEEM_STORE:
        return
    blob = b""
    try:
        prefs.begin("cactuscon", context="unlocks.load")
        blob = prefs.get_blob_with_len(_REDEEMED_BLOB_KEY, _REDEEMED_LEN_KEY, default=b"")
    finally:
        prefs.end()
    if not blob:
        return
    if len(blob) % 32 != 0:
        _warn_once("redeem_len", "Unlock redeemed blob length invalid; truncating")
        blob = blob[: len(blob) - (len(blob) % 32)]
    for i in range(0, len(blob), 32):
        digest_bytes = blob[i : i + 32]
        if len(digest_bytes) == 32:
            _REDEEMED.add(digest_bytes)
            _REDEEMED_LIST.append(digest_bytes)


def _is_redeemed(digest_bytes):
    if not ENABLE_REDEEM_STORE:
        _load_redeemed_if_needed()
        return digest_bytes in _REDEEMED
    _load_redeemed_if_needed()
    return digest_bytes in _REDEEMED


def _mark_redeemed(digest_bytes):
    if not digest_bytes or len(digest_bytes) != 32:
        return
    _load_redeemed_if_needed()
    if digest_bytes in _REDEEMED:
        return
    _REDEEMED.add(digest_bytes)
    if not ENABLE_REDEEM_STORE:
        return
    _REDEEMED_LIST.append(digest_bytes)
    try:
        prefs.begin("cactuscon", write=True, context="unlocks.store")
        blob = b"".join(_REDEEMED_LIST)
        if not prefs.set_blob_with_len(_REDEEMED_BLOB_KEY, _REDEEMED_LEN_KEY, blob):
            _warn_once("redeem_write", "Unlock redeemed store write failed")
    finally:
        prefs.end()


def _now_ms():
    return time.ticks_ms()


def _seconds_to_ms(seconds):
    if seconds <= 0:
        return 0
    return int(seconds * 1000)


def _ms_until(deadline_ms, now_ms):
    if deadline_ms is None:
        return 0
    remaining = time.ticks_diff(deadline_ms, now_ms)
    return remaining if remaining > 0 else 0


def _rate_limit_precheck(now_ms):
    global _rl_last_attempt_ms, _rl_lockout_until_ms
    if not RL_ENABLED:
        return True, None
    remaining = _ms_until(_rl_lockout_until_ms, now_ms)
    if remaining > 0:
        secs = (remaining + 999) // 1000
        if secs < 1:
            secs = 1
        return False, "Too many attempts. Wait {}s.".format(secs)
    if _rl_lockout_until_ms is not None:
        _rl_lockout_until_ms = None
    min_interval_ms = _seconds_to_ms(RL_MIN_INTERVAL_S)
    if min_interval_ms > 0 and _rl_last_attempt_ms is not None:
        if time.ticks_diff(now_ms, _rl_last_attempt_ms) < min_interval_ms:
            return False, "Too fast. Try again."
    _rl_last_attempt_ms = now_ms
    return True, None


def _rate_limit_on_invalid(now_ms):
    global _rl_fail_count, _rl_lockout_until_ms, _rl_lockout_level
    if not RL_ENABLED:
        return
    _rl_fail_count += 1
    if _rl_fail_count < RL_FAIL_THRESHOLD:
        return
    base_ms = _seconds_to_ms(RL_LOCKOUT_BASE_S)
    max_ms = _seconds_to_ms(RL_LOCKOUT_MAX_S)
    lockout_ms = base_ms * (1 << _rl_lockout_level)
    if max_ms > 0 and lockout_ms > max_ms:
        lockout_ms = max_ms
    _rl_lockout_until_ms = time.ticks_add(now_ms, lockout_ms)
    if max_ms == 0 or lockout_ms < max_ms:
        _rl_lockout_level += 1
    _rl_fail_count = 0


def _rate_limit_on_success():
    global _rl_fail_count, _rl_lockout_until_ms, _rl_lockout_level
    if not RL_ENABLED:
        return
    _rl_fail_count = 0
    _rl_lockout_until_ms = None
    _rl_lockout_level = 0


def get_lockout_remaining_seconds():
    if not RL_ENABLED or _rl_lockout_until_ms is None:
        return 0
    now_ms = _now_ms()
    remaining = _ms_until(_rl_lockout_until_ms, now_ms)
    if remaining <= 0:
        return 0
    return (remaining + 999) // 1000


def unlock_focus(code_str, digest_bytes, normalized, context=None):
    if not _verify_digest(digest_bytes, normalized):
        return False, "Invalid code"
    _LOG.info("[UNLOCK] unlocked focus")
    try:
        Achievements()._award("focus")
    except Exception as e:
        _LOG.debug(f"award focus failed: {e}")
    return True, "Unlocked!"


def unlock_rage(code_str, digest_bytes, normalized, context=None):
    if not _verify_digest(digest_bytes, normalized):
        return False, "Invalid code"
    _LOG.info("[UNLOCK] unlocked rage")
    try:
        Achievements()._award("rage")
    except Exception as e:
        _LOG.debug(f"award rage failed: {e}")
    return True, "Unlocked!"


def unlock_workhard_playhard(code_str, digest_bytes, normalized, context=None):
    if not _verify_digest(digest_bytes, normalized):
        return False, "Invalid code"
    _LOG.info("[UNLOCK] unlocked workhard_playhard")
    try:
        Achievements()._award("work_play")
    except Exception as e:
        _LOG.debug(f"award work_play failed: {e}")
    return True, "Unlocked!"

def unlock_complete_hackachu(code_str, digest_bytes, normalized, context=None):
    if not _verify_digest(digest_bytes, normalized):
        return False, "Invalid code"
    _LOG.info("[UNLOCK] unlocked complete_hackachu")
    try:
        Achievements()._award("sao_unlock_hackachu")
    except Exception as e:
        _LOG.debug(f"award hackachu failed: {e}")
    return True, "Unlocked!"


def unlock_complete_enigmox(code_str, digest_bytes, normalized, context=None):
    if not _verify_digest(digest_bytes, normalized):
        return False, "Invalid code"
    _LOG.info("[UNLOCK] unlocked complete_enigmox")
    try:
        Achievements()._award("sao_unlock_enigmox")
    except Exception as e:
        _LOG.debug(f"award enigmox failed: {e}")
    return True, "Unlocked!"


def unlock_complete_glyphbat(code_str, digest_bytes, normalized, context=None):
    if not _verify_digest(digest_bytes, normalized):
        return False, "Invalid code"
    _LOG.info("[UNLOCK] unlocked complete_glyphbat")
    try:
        Achievements()._award("sao_unlock_glyphbat")
    except Exception as e:
        _LOG.debug(f"award glyphbat failed: {e}")
    return True, "Unlocked!"

# Unlock codes (normalized, salted SHA-256).
CODE_REGISTRY_HEX = {
    "2e1e001c43305cf9d9f4ba4c9f82fd36a4de67c4608e1285eb62918a71d87001": unlock_focus,
    "04bf72c2c207bd86151af0345169797df6e89bb966bd854ff7668dda64246d09": unlock_rage,
    "b4ba99622b643921c168451571b230c95f47c3a3efcb87d3bfe2532eac0293f7": unlock_workhard_playhard,
    "8be810a276278511cbd07c0141f23a6f898606e698826ca85673e8a2d9041874": unlock_complete_hackachu,
    "7625dfdb07a223ee07a9475bc42b406230171cf700fe96d006494f8b8310d06c": unlock_complete_enigmox,
    "b0e1e7a7aa077388e1c58f2304b037abaa4bbb2ccde058288c19772f8314d117": unlock_complete_glyphbat,
}

CODE_REGISTRY = {ubinascii.unhexlify(k): v for k, v in CODE_REGISTRY_HEX.items()}


def try_redeem(code_str, context=None):
    """Attempt to redeem an unlock code.

    Returns:
        (ok: bool, message: str)
    """
    normalized = _normalize_code(code_str)
    if not normalized:
        return False, "Enter a code"

    digest_bytes = _digest_normalized(normalized)
    if _is_redeemed(digest_bytes):
        return False, "Already redeemed"

    now_ms = _now_ms()
    ok, message = _rate_limit_precheck(now_ms)
    if not ok:
        return False, message

    handler = CODE_REGISTRY.get(digest_bytes)
    if not handler:
        _rate_limit_on_invalid(now_ms)
        return False, "Invalid code"

    ok, message = handler(code_str, digest_bytes, normalized, context)
    if ok:
        _mark_redeemed(digest_bytes)
        _rate_limit_on_success()
        return True, message or "Unlocked!"

    _rate_limit_on_invalid(now_ms)
    return False, message or "Invalid code"
