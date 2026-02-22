"""Achievement engine - definitions, ownership, and trigger helpers."""

import time
import os

from cactuscon.utils import Logger
from cactuscon import config
from cactuscon.prefs import prefs

# Canonical achievement definitions
ACHIEVEMENTS = [
    {"id": "first_battle", "name": "First Clash", "desc": "Complete your first battle.", "action": "info"},
    {"id": "clean_care", "name": "Clean Streak", "desc": "Keep your creature clean with no temperament issues.", "action": "info"},
    {"id": "collector", "name": "Collector", "desc": "Unlock three unique creatures.", "action": "info"},
    {"id": "win_streak_3", "name": "On Fire", "desc": "Win three battles in a row.", "action": "info"},
    {"id": "loss_streak_3", "name": "Perseverance", "desc": "Endure three losses in a row.", "action": "info"},
    {"id": "tough_love", "name": "Tough Love", "desc": "Use Discipline on your creature.", "action": "info"},
    {"id": "sweet_tooth", "name": "Sweet Tooth", "desc": "Use Treat on your creature.", "action": "info"},
    {"id": "temper_max", "name": "Volatile", "desc": "Reach max temperament.", "action": "info"},
    {"id": "focus", "name": "Focus", "desc": "CTF Award: Reusable 5% XP buff! 15min active, 30min cooldown.", "action": "focus"},
    {"id": "rage", "name": "Rage", "desc": "CTF Award: Reusable +5 Attack, +10 Temper buff! 15min active, 1.5hr cooldown.", "action": "rage"},
    {"id": "work_play", "name": "Work Hard, Play Hard", "desc": "CTF Award: Rainbow LED Mode!", "action": "rgb_rainbow"},
    {"id": "sao_unlock_hackachu", "name": "SAO Hackachu", "desc": "SAO crossover: A rogue Hackachu teaches your creature some hacky tricks. Grants +5 Attack +5 Defense for 15m (30m cooldown).", "action": "sao_buff_easy"},
    {"id": "sao_unlock_enigmox", "name": "SAO Enigmox", "desc": "SAO crossover: Enigmox, the evasive cipher-mage casts wards on your creatures. Grants +5 Defense +5 Evasion for 15m (60m cooldown).", "action": "sao_buff_medium"},
    {"id": "sao_unlock_glyphbat", "name": "SAO Glyphbat", "desc": "SAO crossover: Glyphbat, an aerial radiowave antagonist helps flank your enemies. Grants +10 Attack +5 Defense +5 Evasion for 15m (60m cooldown).", "action": "sao_buff_hard"},
]

# Achievement icon path template
_ICON_CANDIDATES = (
    "/assets/images/icons/{id}.rgb565",
    "assets/images/icons/{id}.rgb565",
    "badge/src/assets/images/icons/{id}.rgb565",
    "releases/badge/assets/images/icons/{id}.rgb565",
)
ACHIEVEMENT_ICON_PATH = _ICON_CANDIDATES[0]

# Power/buff definitions for actionable achievements
_MINUTE_MS = 60 * 1000
_MAX_REASONABLE_TIMER_MS = int(
    getattr(config, "ACHIEVEMENTS_MAX_REASONABLE_TIMER_MS", 12 * 60 * 60 * 1000)
)
if _MAX_REASONABLE_TIMER_MS <= 0:
    _MAX_REASONABLE_TIMER_MS = 12 * 60 * 60 * 1000
ACHIEVEMENT_POWERS = {
    "focus": {
        "id": "focus",
        "name": "Focus",
        "duration_ms": 15 * _MINUTE_MS,
        "cooldown_ms": 30 * _MINUTE_MS,
        "xp_boost_pct": 20,
    },
    "rage": {
        "id": "rage",
        "name": "Rage",
        "duration_ms": 15 * _MINUTE_MS,
        "cooldown_ms": 90 * _MINUTE_MS,
        "atk_delta": 5,
        "temperament_delta": 10,
        "temperament_gate": 5,
    },
    "work_play": {
        "id": "work_play",
        "name": "Work Hard, Play Hard",
        "duration_ms": 0,           # instant toggle; no active/cooldown
        "cooldown_ms": 0,
        "hardware_action": "rgb_rainbow",
    },
    "sao_unlock_hackachu": {
        "id": "sao_unlock_hackachu",
        "name": "SAO Hackachu",
        "duration_ms": 15 * _MINUTE_MS,
        "cooldown_ms": 30 * _MINUTE_MS,
        "atk_delta": 5,
        "def_delta": 5,
    },
    "sao_unlock_enigmox": {
        "id": "sao_unlock_enigmox",
        "name": "SAO Enigmox",
        "duration_ms": 15 * _MINUTE_MS,
        "cooldown_ms": 60 * _MINUTE_MS,
        "def_delta": 5,
        "evasion_delta": 10,
    },
    "sao_unlock_glyphbat": {
        "id": "sao_unlock_glyphbat",
        "name": "SAO Glyphbat",
        "duration_ms": 15 * _MINUTE_MS,
        "cooldown_ms": 60 * _MINUTE_MS,
        "atk_delta": 10,
        "def_delta": 5,
        "evasion_delta": 5,
    },
}

# NVS keys for power state (<=15 chars)
KEY_POWER_ACTIVE = "ach_actv"       # CSV of id:ttl_ms_remaining
KEY_POWER_COOLDOWN = "ach_cdwn"     # CSV of id:ttl_ms_remaining
KEY_WORK_PLAY_STATE = "ach_wp_on"   # bool flag for rainbow toggle
KEY_POWER_LAST_CHECK = "ach_lchk"   # ticks_ms when TTLs were last decremented
KEY_POWER_BASIS = "ach_basis"       # legacy basis key (migration only)


def get_achievement_catalog():
    """Return active achievement definition list."""
    return ACHIEVEMENTS


def get_achievement_powers():
    """Return active achievement power definitions."""
    return ACHIEVEMENT_POWERS


def set_achievement_catalog(achievements=None, powers=None):
    """
    Replace active achievement and/or power definitions in place.

    This keeps default game content as the built-in baseline while allowing
    custom engines to inject their own catalogs at runtime.
    """
    if achievements is not None:
        if not isinstance(achievements, (list, tuple)):
            raise TypeError("achievements must be a list/tuple of dicts")
        seen_ids = set()
        normalized = []
        for ach in achievements:
            if not isinstance(ach, dict):
                raise TypeError("achievement entries must be dicts")
            aid = ach.get("id")
            if not aid or not isinstance(aid, str):
                raise ValueError("achievement entries require string 'id'")
            if aid in seen_ids:
                raise ValueError(f"duplicate achievement id: {aid}")
            seen_ids.add(aid)
            normalized.append(dict(ach))
        ACHIEVEMENTS[:] = normalized

    if powers is not None:
        if not isinstance(powers, dict):
            raise TypeError("powers must be a dict keyed by power id")
        normalized_powers = {}
        for pid, effect in powers.items():
            if not pid or not isinstance(pid, str):
                raise ValueError("power IDs must be non-empty strings")
            if not isinstance(effect, dict):
                raise TypeError("power entries must be dicts")
            effect_copy = dict(effect)
            effect_copy.setdefault("id", pid)
            if effect_copy.get("id") != pid:
                raise ValueError(f"power id mismatch for key '{pid}'")
            normalized_powers[pid] = effect_copy
        ACHIEVEMENT_POWERS.clear()
        ACHIEVEMENT_POWERS.update(normalized_powers)


def get_achievement_ids():
    """Get list of all achievement IDs."""
    return [a["id"] for a in get_achievement_catalog()]


def get_achievement_icon_path(achievement_id):
    """Get the first existing icon path for a specific achievement."""
    for tmpl in _ICON_CANDIDATES:
        path = tmpl.format(id=achievement_id)
        try:
            os.stat(path)
            return path
        except OSError:
            continue
    # Fallback to default template (may still be missing but preserves old behavior)
    return ACHIEVEMENT_ICON_PATH.format(id=achievement_id)


def get_achievement_icon_paths():
    """
    Get list of all achievement icon paths for preloading.
    
    Returns:
        list: Paths to all achievement icon files (rgb565 format).
    """
    return [get_achievement_icon_path(aid) for aid in get_achievement_ids()]


# NVS key names must be <=15 chars; keep them short
KEY_PACK_ACH = "ach"       # owned achievements CSV
KEY_WIN_STREAK = "ws"      # win streak counter
KEY_LOSS_STREAK = "ls"     # loss streak counter
KEY_CLEAN_STREAK = "ccs"   # clean-care streak counter


def get_owned_achievements(prefs, default_ids=None):
    """Load owned achievement IDs from prefs."""
    prefs.begin(context="achievements.get_owned_achievements")
    raw = prefs.get_string(KEY_PACK_ACH, "")
    prefs.end()
    if raw:
        return [aid for aid in raw.split(",") if aid]
    return list(default_ids or [])


def _save_owned_achievements(prefs, owned_ids):
    """Persist owned achievements to prefs."""
    prefs.begin(write=True, context="achievements._save_owned_achievements")
    prefs.set_string(KEY_PACK_ACH, ",".join(owned_ids))
    prefs.end()


def _parse_power_csv(raw):
    """Parse stored CSV of id:ts into dict."""
    powers = {}
    if not raw:
        return powers
    for entry in raw.split(","):
        if ":" not in entry:
            continue
        pid, ts = entry.split(":", 1)
        if not pid:
            continue
        try:
            powers[pid] = int(ts)
        except Exception:
            continue
    return powers


def _serialize_power_csv(power_map):
    parts = []
    for pid, ts in (power_map or {}).items():
        parts.append(f"{pid}:{int(ts)}")
    return ",".join(parts)


def _now_ms():
    try:
        return time.ticks_ms()
    except Exception:
        return int(time.time() * 1000)


def _ticks_diff(a, b):
    try:
        return time.ticks_diff(a, b)
    except Exception:
        return a - b


def _ticks_add(a, b):
    try:
        return time.ticks_add(a, b)
    except Exception:
        return a + b


def _remaining_ms(deadline_ms, now_ms):
    """
    Compute remaining ms until deadline, with guardrails for stale/corrupt data.

    Stored cooldown/active timestamps can become invalid across firmware/storage
    history. If a remaining value is absurdly far in the future, treat it as expired.
    """
    try:
        remaining = _ticks_diff(int(deadline_ms), int(now_ms))
    except Exception:
        return -1
    if remaining > _MAX_REASONABLE_TIMER_MS:
        return -1
    return remaining


class Achievements:
    """Achievement helper that encapsulates awarding logic and persistence."""

    def __init__(self, prefs_instance=None, logger_level=config.LOG_LEVEL):
        # Use global prefs by default to avoid passing around handles
        self.prefs = prefs_instance or prefs
        self.logger = Logger(logger_level)

    # --- internal helpers ---

    def _bump_streak(self, counter_key, reset_key, achievement_id, threshold):
        """
        Increment a streak counter, reset the opposite counter, and award if threshold reached.
        """
        self.prefs.begin(write=True, context="achievements._bump_streak")
        streak = self.prefs.get_int32(counter_key, 0) + 1
        self.prefs.set_int32(counter_key, streak)
        if reset_key:
            self.prefs.set_int32(reset_key, 0)
        self.prefs.end()

        if streak >= threshold:
            self._award(achievement_id)
        return streak

    def list_all(self):
        return get_achievement_catalog()

    def list_owned(self):
        return get_owned_achievements(self.prefs)

    def _award(self, achievement_id):
        owned = set(self.list_owned() or [])
        if achievement_id in owned:
            return False
        owned.add(achievement_id)
        _save_owned_achievements(self.prefs, list(owned))
        self.logger.info(f"Achievement unlocked: {achievement_id}")
        return True

    def _legacy_deadline_map_to_ttl(self, power_map, basis_ms, now_ms):
        """Convert legacy deadline-based map values into TTL milliseconds."""
        ttl_map = {}
        changed = False
        for pid, val in list((power_map or {}).items()):
            if basis_ms >= 0:
                remaining = _ticks_diff(val, basis_ms)
            else:
                # Very old schema stored absolute deadlines.
                remaining = _remaining_ms(val, now_ms)
            if remaining <= 0 or remaining > _MAX_REASONABLE_TIMER_MS:
                changed = True
                continue
            ttl_map[pid] = int(remaining)
            if remaining != val:
                changed = True
        return ttl_map, changed

    def _decrement_ttl_map(self, power_map, elapsed_ms):
        """Decrement TTLs by elapsed ms, dropping expired entries."""
        ttl_map = {}
        for pid, ttl in list((power_map or {}).items()):
            remaining = int(ttl) - int(elapsed_ms)
            if remaining > 0:
                ttl_map[pid] = remaining
        return ttl_map

    # --- power/effect helpers ---

    def _load_power_state(self, now_ms=None):
        """Load active powers/cooldowns as TTL maps and prune expired entries."""
        now_ms = now_ms if now_ms is not None else _now_ms()
        self.prefs.begin(context="achievements.load_powers")
        raw_active = self.prefs.get_string(KEY_POWER_ACTIVE, "")
        raw_cd = self.prefs.get_string(KEY_POWER_COOLDOWN, "")
        last_check_ms = self.prefs.get_int32(KEY_POWER_LAST_CHECK, -1)
        basis_ms = self.prefs.get_int32(KEY_POWER_BASIS, -1)
        self.prefs.end()
        active = _parse_power_csv(raw_active)
        cooldowns = _parse_power_csv(raw_cd)

        changed = False

        # Migrate legacy schemas (deadline-based) to TTL storage.
        if last_check_ms < 0:
            active, _ = self._legacy_deadline_map_to_ttl(active, basis_ms, now_ms)
            cooldowns, _ = self._legacy_deadline_map_to_ttl(cooldowns, basis_ms, now_ms)
            changed = True
        else:
            now_diff = _ticks_diff(now_ms, last_check_ms)
            if now_diff < 0:
                # Device reboot/tick reset: only elapsed time since boot is knowable.
                elapsed_ms = now_ms
            else:
                elapsed_ms = now_diff

            if elapsed_ms < 0:
                elapsed_ms = 0
            if elapsed_ms > _MAX_REASONABLE_TIMER_MS:
                elapsed_ms = _MAX_REASONABLE_TIMER_MS

            if elapsed_ms > 0:
                active = self._decrement_ttl_map(active, elapsed_ms)
                cooldowns = self._decrement_ttl_map(cooldowns, elapsed_ms)
                changed = True

        if changed or basis_ms >= 0 or last_check_ms < 0:
            self._save_power_state(active, cooldowns, last_check_ms=now_ms)
        return active, cooldowns

    def _save_power_state(self, active, cooldowns, last_check_ms=None):
        last_check_ms = _now_ms() if last_check_ms is None else last_check_ms
        self.prefs.begin(write=True, context="achievements.save_powers")
        self.prefs.set_string(KEY_POWER_ACTIVE, _serialize_power_csv(active))
        self.prefs.set_string(KEY_POWER_COOLDOWN, _serialize_power_csv(cooldowns))
        self.prefs.set_int32(KEY_POWER_LAST_CHECK, int(last_check_ms))
        # Keep legacy key inert to avoid future migrations from stale basis values.
        self.prefs.set_int32(KEY_POWER_BASIS, -1)
        self.prefs.end()

    def get_active_powers(self, now_ms=None):
        """Return list of active power IDs (non-expired)."""
        active, _ = self._load_power_state(now_ms=now_ms)
        return list(active.keys())

    def get_power_status(self, now_ms=None):
        """Return detailed power state for UI."""
        now_ms = now_ms if now_ms is not None else _now_ms()
        active, cooldowns = self._load_power_state(now_ms=now_ms)
        return {
            "active": {pid: int(ttl) for pid, ttl in active.items()},
            "cooldowns": {pid: int(ttl) for pid, ttl in cooldowns.items()},
        }

    def use_power(self, achievement_id, now_ms=None):
        """
        Activate an achievement power if owned and off cooldown.

        Returns:
            dict: {'ok': bool, 'msg': str, 'power': dict}
        """
        now_ms = now_ms if now_ms is not None else _now_ms()
        powers = get_achievement_powers()
        if achievement_id not in powers:
            return {"ok": False, "msg": "Not usable"}
        if achievement_id not in (self.list_owned() or []):
            return {"ok": False, "msg": "Locked"}

        power = powers[achievement_id]

        # Special case: work_play should behave as a pure toggle, no cooldown/active gating
        if achievement_id == "work_play":
            try:
                self.prefs.begin(write=True, context="achievements.work_play_toggle")
                current_on = bool(self.prefs.get_int32(KEY_WORK_PLAY_STATE, 0))
                new_on = not current_on
                self.prefs.set_int32(KEY_WORK_PLAY_STATE, int(new_on))
                self.prefs.end()
            except Exception:
                try:
                    self.prefs.end()
                except Exception:
                    pass
            return {
                "ok": True,
                "msg": "Activated" if new_on else "Deactivated",
                "power": power,
                "toggled_off": not new_on,
                "expires_at": now_ms,
                "cooldown_until": now_ms,
            }

        active, cooldowns = self._load_power_state(now_ms=now_ms)

        # Hardware-only actions (duration=0, cooldown=0) act as toggles
        if power.get("hardware_action") and power.get("duration_ms", 0) == 0 and power.get("cooldown_ms", 0) == 0:
            if achievement_id in active:
                # Toggle off
                active.pop(achievement_id, None)
                cooldowns.pop(achievement_id, None)
                self._save_power_state(active, cooldowns)
                return {
                    "ok": True,
                    "msg": "Deactivated",
                    "power": power,
                    "toggled_off": True,
                    "expires_at": now_ms,
                    "cooldown_until": now_ms,
                }
            # Toggle on (store long-lived TTL so we can detect active)
            sentinel_ttl = 24 * 60 * 60 * 1000
            active[achievement_id] = sentinel_ttl
            self._save_power_state(active, cooldowns)
            return {
                "ok": True,
                "msg": "Activated",
                "power": power,
                "expires_at": _ticks_add(now_ms, sentinel_ttl),
                "cooldown_until": now_ms,
            }

        if achievement_id in active:
            remaining = int(active[achievement_id])
            return {"ok": False, "msg": f"Active ({remaining//1000}s left)", "power": power}

        if achievement_id in cooldowns:
            remaining = int(cooldowns[achievement_id])
            if remaining > 0:
                return {"ok": False, "msg": f"Cooling down ({remaining//1000}s)", "power": power}
            cooldowns.pop(achievement_id, None)

        # Temperament gate for rage
        if achievement_id == "rage":
            try:
                from cactuscon.game.engine.characters import get_care_state, CARE_TEMPERAMENT_MAX
                state = get_care_state(self.prefs) or {}
                temper = state.get("temperament", 0)
                if temper >= power.get("temperament_gate", CARE_TEMPERAMENT_MAX):
                    return {"ok": False, "msg": "Too agitated", "power": power}
            except Exception:
                pass

        # Hardware-only instantaneous action (no active/cooldown tracking)
        if power.get("hardware_action") and power.get("duration_ms", 0) == 0:
            return {
                "ok": True,
                "msg": "Activated",
                "power": power,
                "expires_at": now_ms,
                "cooldown_until": now_ms,
            }

        duration = power.get("duration_ms", 0)
        cooldown = power.get("cooldown_ms", 0)
        expires_at = _ticks_add(now_ms, duration)
        cooldown_until = _ticks_add(now_ms, cooldown)

        active[achievement_id] = int(duration) if duration else 0
        cooldowns[achievement_id] = int(cooldown) if cooldown else 0
        self._save_power_state(active, cooldowns)

        # Immediate temperament adjustment if defined
        if power.get("temperament_delta"):
            try:
                from cactuscon.game.engine.characters import CARE_TEMPER_KEY, CARE_TEMPER_SET, CARE_TEMPERAMENT_MAX
                self.prefs.begin(write=True, context="achievements.use_power_temper")
                current = self.prefs.get_int32(CARE_TEMPER_KEY, 0)
                new_val = current + power.get("temperament_delta", 0)
                if new_val > CARE_TEMPERAMENT_MAX:
                    new_val = CARE_TEMPERAMENT_MAX
                if new_val < 0:
                    new_val = 0
                self.prefs.set_int32(CARE_TEMPER_KEY, new_val)
                self.prefs.set_int32(CARE_TEMPER_SET, now_ms)
                self.prefs.end()
            except Exception:
                try:
                    self.prefs.end()
                except Exception:
                    pass

        return {
            "ok": True,
            "msg": "Activated",
            "power": power,
            "expires_at": expires_at,
            "cooldown_until": cooldown_until,
        }

    # --- Achievement-specific methods (call these as triggers) ---

    def first_battle(self, winner):
        """
        Award for completing a non-draw battle.
        Call when a battle ends; ignores draws.
        """
        if winner and winner != 0:
            self._award("first_battle")

    def clean_care(self, is_calm):
        """
        Award for maintaining calm temperament over the required period.
        Call when they've used clean care 3 times when already calm.
        """
        already_owned = "clean_care" in (self.list_owned() or [])
        if is_calm and not already_owned:
            self._bump_streak(KEY_CLEAN_STREAK, None, "clean_care", 3)
        else:
            # Reset streak so we don't inflate past unlock or when not calm
            self.prefs.begin(write=True, context="achievements.clean_care_reset")
            self.prefs.set_int32(KEY_CLEAN_STREAK, 0)
            self.prefs.end()

    def collector(self, owned_character_ids):
        """
        Award for owning three unique hacktarmon.
        Call whenever characters are added/unlocked.
        """
        unique_count = len(set(owned_character_ids or []))
        if unique_count >= 3:
            self._award("collector")

    def discipline_use(self):
        """Award for using Discipline."""
        self._award("tough_love")

    def treat_use(self):
        """Award for using Treat."""
        self._award("sweet_tooth")

    def temperament_max(self, current_temperament, max_temperament):
        """Award when temperament reaches the max threshold."""
        if current_temperament >= max_temperament:
            self._award("temper_max")

    def win_streak(self):
        """
        Call when a battle is won. Tracks consecutive wins internally and resets losses.
        """
        self._bump_streak(KEY_WIN_STREAK, KEY_LOSS_STREAK, "win_streak_3", 3)

    def loss_streak(self):
        """
        Call when a battle is lost. Tracks consecutive losses internally and resets wins.
        """
        self._bump_streak(KEY_LOSS_STREAK, KEY_WIN_STREAK, "loss_streak_3", 3)

    def reset_streaks(self):
        """Reset win/loss streak counters (e.g., on draw)."""
        self.prefs.begin(write=True, context="achievements.reset_streaks")
        self.prefs.set_int32(KEY_WIN_STREAK, 0)
        self.prefs.set_int32(KEY_LOSS_STREAK, 0)
        self.prefs.end()
