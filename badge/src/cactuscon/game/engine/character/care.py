"""Care system for the CactusCon badge battle system.

Handles feeding, activities, and temperament management for creatures.
"""

import time
from cactuscon.prefs import make_key

# Care timing constants
CARE_EFFECT_DURATION_MS = 600000  # 10 minutes
CARE_EFFECT_COOLDOWN_MS = 900000  # 15 minutes
CARE_TEMPER_DECAY_MS = 15 * 60 * 1000  # 15 minutes per temperament step
CARE_TEMPERAMENT_MAX = 10

# Short NVS keys for care state (<=15 chars)
CARE_ACT_ID = make_key("ca", "id")
CARE_ACT_EXP = make_key("ca", "exp")
CARE_ACT_SET = make_key("ca", "set")
CARE_ACT_CD = make_key("ca", "cd")
CARE_ACT_CD_SET = make_key("ca", "cds")

CARE_FOOD_ID = make_key("cf", "id")
CARE_FOOD_EXP = make_key("cf", "exp")
CARE_FOOD_SET = make_key("cf", "set")
CARE_FOOD_CD = make_key("cf", "cd")
CARE_FOOD_CD_SET = make_key("cf", "cds")

CARE_TEMPER_KEY = make_key("ca", "temp")
CARE_TEMPER_SET = make_key("ca", "tset")


# Care effect catalog - defines available activities and foods
CARE_EFFECT_CATALOG = {
    'activity': [
        {
            'id': 'bathe',
            'name': 'Bathe',
            'desc': 'Calm clean buff; small XP boost, lowers temperament.',
            'temperament_delta': -1,
            'xp_boost_pct': 5,
            'atk_delta': 0,
            'def_delta': 0,
        },
        {
            'id': 'discipline',
            'name': 'Discipline',
            'desc': 'Stricter training; bigger XP boost, raises temperament.',
            'temperament_delta': 1,
            'xp_boost_pct': 5,
            'atk_delta': 0,
            'def_delta': 0,
        },
    ],
    'food': [
        {
            'id': 'feed',
            'name': 'Feed',
            'desc': 'Makes attacks slightly less and defense slightly more effective.',
            'temperament_delta': 0,
            'atk_delta': -1,
            'def_delta': 1,
            'xp_boost_pct': 0,
        },
        {
            'id': 'treat',
            'name': 'Treat',
            'desc': 'Makes attacks slightly more and defense slightly less effective; raises temperament.',
            'temperament_delta': 1,
            'atk_delta': 1,
            'def_delta': -1,
            'xp_boost_pct': 0,
        },
    ],
}


def get_care_catalog():
    """Return available care effects grouped by category."""
    return CARE_EFFECT_CATALOG


def set_care_catalog(catalog):
    """
    Replace the active care-effect catalog in place.

    Expected shape:
        {
            "activity": [ {id, ...}, ... ],
            "food": [ {id, ...}, ... ],
        }
    """
    if not isinstance(catalog, dict):
        raise TypeError("catalog must be a dict")
    for key in ("activity", "food"):
        value = catalog.get(key, [])
        if not isinstance(value, (list, tuple)):
            raise TypeError(f"catalog['{key}'] must be a list/tuple")
        for effect in value:
            if not isinstance(effect, dict):
                raise TypeError(f"catalog['{key}'] must contain dict entries")
            effect_id = effect.get("id")
            if not effect_id or not isinstance(effect_id, str):
                raise ValueError(f"catalog['{key}'] entries require string 'id'")
    CARE_EFFECT_CATALOG.clear()
    CARE_EFFECT_CATALOG.update(
        {
            "activity": list(catalog.get("activity", [])),
            "food": list(catalog.get("food", [])),
        }
    )


def _has_expired(now_ms, expires_at):
    """Check if a timer has expired."""
    try:
        return time.ticks_diff(now_ms, expires_at) >= 0
    except Exception:
        return now_ms >= expires_at


def _normalize_timer(set_at, expires_at, now_ms):
    """
    Normalize a timer that was stored using uptime-based timestamps.
    On reboot, now_ms resets to near zero, so we recompute expires_at from the
    original remaining duration.
    Returns (normalized_set_at, normalized_expires_at, changed_flag).
    """
    if not expires_at:
        return set_at, expires_at, False
    if not set_at or set_at <= 0:
        return now_ms, expires_at, True
    # If set_at is in the future relative to current uptime, assume reboot/wrap
    if set_at > now_ms:
        remaining = max(0, expires_at - set_at)
        new_expires = now_ms + remaining
        return now_ms, new_expires, True
    return set_at, expires_at, False


def _load_and_normalize_care(prefs, now_ms):
    """
    Shared loader for care timers that normalizes timestamps on reboot/wrap.
    Returns a dict with ids, set/expires, cooldowns, and a changed flag.
    """
    prefs.begin(context="character.care._load_and_normalize_care")
    activity_id = prefs.get_string(CARE_ACT_ID, "")
    activity_expire = prefs.get_int32(CARE_ACT_EXP, 0)
    activity_set = prefs.get_int32(CARE_ACT_SET, 0)
    activity_cooldown = prefs.get_int32(CARE_ACT_CD, 0)
    activity_cooldown_set = prefs.get_int32(CARE_ACT_CD_SET, 0)
    food_id = prefs.get_string(CARE_FOOD_ID, "")
    food_expire = prefs.get_int32(CARE_FOOD_EXP, 0)
    food_set = prefs.get_int32(CARE_FOOD_SET, 0)
    food_cooldown = prefs.get_int32(CARE_FOOD_CD, 0)
    food_cooldown_set = prefs.get_int32(CARE_FOOD_CD_SET, 0)
    temperament = prefs.get_int32(CARE_TEMPER_KEY, 0)
    temper_set = prefs.get_int32(CARE_TEMPER_SET, 0)
    prefs.end()

    activity_set, activity_expire, act_changed = _normalize_timer(activity_set, activity_expire, now_ms)
    food_set, food_expire, food_changed = _normalize_timer(food_set, food_expire, now_ms)
    activity_cooldown_set, activity_cooldown, act_cd_changed = _normalize_timer(activity_cooldown_set, activity_cooldown, now_ms)
    food_cooldown_set, food_cooldown, food_cd_changed = _normalize_timer(food_cooldown_set, food_cooldown, now_ms)

    changed = act_changed or food_changed or act_cd_changed or food_cd_changed
    if changed:
        prefs.begin(write=True, context="character.care._load_and_normalize_care normalize")
        if act_changed:
            prefs.set_int32(CARE_ACT_SET, activity_set)
            prefs.set_int32(CARE_ACT_EXP, activity_expire)
        if food_changed:
            prefs.set_int32(CARE_FOOD_SET, food_set)
            prefs.set_int32(CARE_FOOD_EXP, food_expire)
        if act_cd_changed:
            prefs.set_int32(CARE_ACT_CD_SET, activity_cooldown_set)
            prefs.set_int32(CARE_ACT_CD, activity_cooldown)
        if food_cd_changed:
            prefs.set_int32(CARE_FOOD_CD_SET, food_cooldown_set)
            prefs.set_int32(CARE_FOOD_CD, food_cooldown)
        prefs.end()

    return {
        "activity_id": activity_id,
        "activity_expire": activity_expire,
        "activity_set": activity_set,
        "activity_cooldown": activity_cooldown,
        "activity_cooldown_set": activity_cooldown_set,
        "food_id": food_id,
        "food_expire": food_expire,
        "food_set": food_set,
        "food_cooldown": food_cooldown,
        "food_cooldown_set": food_cooldown_set,
        "temperament": temperament,
        "temper_set": temper_set,
    }


def tick_care_timers(prefs, now_ms=None):
    """
    Clean up expired care effects and cooldowns; call periodically from main loop.
    """
    now_ms = now_ms if now_ms is not None else time.ticks_ms()
    data = _load_and_normalize_care(prefs, now_ms)
    activity_id = data["activity_id"]
    activity_expire = data["activity_expire"]
    activity_cooldown = data["activity_cooldown"]
    food_id = data["food_id"]
    food_expire = data["food_expire"]
    food_cooldown = data["food_cooldown"]
    temper = data["temperament"]
    temper_set = data.get("temper_set", 0)
    changed = False

    # Expire activity effect
    if activity_id and (activity_expire <= 0 or _has_expired(now_ms, activity_expire)):
        prefs.begin(write=True, context="character.care.tick_care_timers expire_activity")
        prefs.set_string(CARE_ACT_ID, "")
        prefs.set_int32(CARE_ACT_EXP, 0)
        prefs.set_int32(CARE_ACT_SET, 0)
        changed = True
        prefs.end()

    # Expire food effect
    if food_id and (food_expire <= 0 or _has_expired(now_ms, food_expire)):
        prefs.begin(write=True, context="character.care.tick_care_timers expire_food")
        prefs.set_string(CARE_FOOD_ID, "")
        prefs.set_int32(CARE_FOOD_EXP, 0)
        prefs.set_int32(CARE_FOOD_SET, 0)
        changed = True
        prefs.end()

    # Clear cooldowns when done
    if activity_cooldown > 0 and _has_expired(now_ms, activity_cooldown):
        prefs.begin(write=True, context="character.care.tick_care_timers clear_activity_cd")
        prefs.set_int32(CARE_ACT_CD, 0)
        prefs.set_int32(CARE_ACT_CD_SET, 0)
        changed = True
        prefs.end()

    if food_cooldown > 0 and _has_expired(now_ms, food_cooldown):
        prefs.begin(write=True, context="character.care.tick_care_timers clear_food_cd")
        prefs.set_int32(CARE_FOOD_CD, 0)
        prefs.set_int32(CARE_FOOD_CD_SET, 0)
        changed = True
        prefs.end()

    # Temperament passive decay (15 minutes per step)
    if temper > 0 and temper_set > 0 and CARE_TEMPER_DECAY_MS > 0:
        try:
            elapsed = time.ticks_diff(now_ms, temper_set)
        except Exception:
            elapsed = now_ms - temper_set
        steps = elapsed // CARE_TEMPER_DECAY_MS
        if steps > 0:
            temper = max(0, temper - int(steps))
            prefs.begin(write=True, context="character.care.tick_care_timers temper_decay")
            prefs.set_int32(CARE_TEMPER_KEY, temper)
            prefs.set_int32(CARE_TEMPER_SET, now_ms)
            changed = True
            prefs.end()

    return changed


def get_care_state(prefs, now_ms=None):
    """
    Load care state from prefs.
    
    Returns:
        dict with 'activity', 'food', 'temperament', and cooldowns.
    """
    now_ms = now_ms if now_ms is not None else time.ticks_ms()
    activity = {}
    food = {}
    data = _load_and_normalize_care(prefs, now_ms)
    activity_id = data["activity_id"]
    activity_expire = data["activity_expire"]
    activity_cooldown = data["activity_cooldown"]
    food_id = data["food_id"]
    food_expire = data["food_expire"]
    food_cooldown = data["food_cooldown"]
    temperament = data["temperament"]
    temper_set = data.get("temper_set", 0)

    # Active effects
    if activity_id and activity_expire > 0 and not _has_expired(now_ms, activity_expire):
        remaining = time.ticks_diff(activity_expire, now_ms)
        activity = {"id": activity_id, "expires_at": activity_expire, "remaining_ms": remaining}
    if food_id and food_expire > 0 and not _has_expired(now_ms, food_expire):
        remaining = time.ticks_diff(food_expire, now_ms)
        food = {"id": food_id, "expires_at": food_expire, "remaining_ms": remaining}

    # Cooldowns
    activity_cooldown_active = activity_cooldown > 0 and not _has_expired(now_ms, activity_cooldown)
    food_cooldown_active = food_cooldown > 0 and not _has_expired(now_ms, food_cooldown)

    return {
        "activity": activity or None,
        "food": food or None,
        "temperament": temperament,
        "temper_set": temper_set,
        "activity_cooldown": activity_cooldown if activity_cooldown_active else 0,
        "food_cooldown": food_cooldown if food_cooldown_active else 0,
    }


def set_care_effect(prefs, category, effect_id, duration_ms=None, now_ms=None):
    """Persist selected care effect for a category and adjust temperament."""
    from cactuscon.game.engine.achievements import Achievements
    catalog = get_care_catalog().get(category, [])
    effect = next((c for c in catalog if c.get("id") == effect_id), None)
    if not effect:
        return None

    if duration_ms is None:
        duration_ms = CARE_EFFECT_DURATION_MS
    cooldown_ms = CARE_EFFECT_COOLDOWN_MS

    now_ms = now_ms if now_ms is not None else time.ticks_ms()
    try:
        expires_at = time.ticks_add(now_ms, duration_ms)
    except Exception:
        expires_at = now_ms + duration_ms
    try:
        cooldown_until = time.ticks_add(now_ms, cooldown_ms)
    except Exception:
        cooldown_until = now_ms + cooldown_ms

    prefs.begin(write=True, context="character.care.set_care_effect")
    temperament = prefs.get_int32(CARE_TEMPER_KEY, 0)
    temperament += effect.get("temperament_delta", 0)
    if temperament > CARE_TEMPERAMENT_MAX:
        temperament = CARE_TEMPERAMENT_MAX
    if temperament < 0:
        temperament = 0
    if category == "activity":
        prefs.set_string(CARE_ACT_ID, effect_id)
        prefs.set_int32(CARE_ACT_EXP, expires_at)
        prefs.set_int32(CARE_ACT_SET, now_ms)
        prefs.set_int32(CARE_ACT_CD, cooldown_until)
        prefs.set_int32(CARE_ACT_CD_SET, now_ms)
    elif category == "food":
        prefs.set_string(CARE_FOOD_ID, effect_id)
        prefs.set_int32(CARE_FOOD_EXP, expires_at)
        prefs.set_int32(CARE_FOOD_SET, now_ms)
        prefs.set_int32(CARE_FOOD_CD, cooldown_until)
        prefs.set_int32(CARE_FOOD_CD_SET, now_ms)
    prefs.set_int32(CARE_TEMPER_KEY, temperament)
    prefs.set_int32(CARE_TEMPER_SET, now_ms)
    prefs.end()
    try:
        ach = Achievements()
        if effect_id == "discipline":
            ach.discipline_use()
        elif effect_id == "treat":
            ach.treat_use()
        ach.temperament_max(temperament, CARE_TEMPERAMENT_MAX)
    except Exception:
        pass

    return {"id": effect_id, "expires_at": expires_at, "cooldown_until": cooldown_until, "effect": effect}
