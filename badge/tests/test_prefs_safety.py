"""Behavior tests for preferences lock/timeouts and bounded integer reads."""

from cactuscon.prefs import Preferences


def test_prefs_begin_timeout_under_lock_contention():
    """begin(write=True) should fail fast when lock never becomes available."""
    prefs = Preferences()

    class LockedForever:
        def acquire(self, _blocking=True):
            return False

        def release(self):
            return None

        def locked(self):
            return True

    original_lock = prefs.lock
    original_owner = prefs._lock_owner
    try:
        prefs.lock = LockedForever()
        prefs._lock_owner = "holder"
        timed_out = False
        try:
            prefs.begin(write=True, context="test.lock_timeout", timeout_ms=15)
        except RuntimeError as exc:
            timed_out = "timeout" in str(exc).lower()
        assert timed_out, "prefs.begin() should raise timeout RuntimeError"
    finally:
        prefs.lock = original_lock
        prefs._lock_owner = original_owner


def test_prefs_get_int32_safe_enforces_bounds():
    """Out-of-range values should fall back to the provided default."""
    prefs = Preferences()

    prefs.set_int32("safe_level", 7)
    assert prefs.get_int32_safe("safe_level", default=1, min_val=1, max_val=99) == 7

    prefs.set_int32("safe_level", 0)
    assert prefs.get_int32_safe("safe_level", default=1, min_val=1, max_val=99) == 1

    prefs.set_int32("safe_level", 150)
    assert prefs.get_int32_safe("safe_level", default=1, min_val=1, max_val=99) == 1
