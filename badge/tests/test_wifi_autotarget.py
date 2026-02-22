"""Behavior tests for WiFi auto-target selection and reconnect preference logic."""


def test_choose_auto_target_prefers_saved_then_ota_based_on_preference(fresh_wifi_module, monkeypatch):
    wifi_mod = fresh_wifi_module
    manager = wifi_mod.WiFiManager.get_instance()

    monkeypatch.setattr(wifi_mod, "load_saved_credentials", lambda: ("SavedNet", "saved-pass"))
    monkeypatch.setattr(wifi_mod.config, "OTA_WIFI_SSID", "OTANet", raising=False)
    monkeypatch.setattr(wifi_mod.config, "OTA_WIFI_PASSWORD", "ota-pass", raising=False)

    manager._auto_target_preference = "saved"
    assert manager._choose_auto_target() == ("saved", "SavedNet", "saved-pass")

    manager._auto_target_preference = "ota"
    assert manager._choose_auto_target() == ("ota", "OTANet", "ota-pass")


def test_note_connect_failure_switches_preference_and_increments_only_for_expected_reasons(
    fresh_wifi_module, monkeypatch
):
    wifi_mod = fresh_wifi_module
    manager = wifi_mod.WiFiManager.get_instance()
    calls = {"inc": 0}

    monkeypatch.setattr(wifi_mod, "increment_saved_failure", lambda: calls.__setitem__("inc", calls["inc"] + 1))

    manager._last_attempt_source = "saved"
    manager._auto_target_preference = "saved"
    manager._note_connect_failure("timeout")
    assert calls["inc"] == 1
    assert manager._auto_target_preference == "ota"

    manager._last_attempt_source = "saved"
    manager._note_connect_failure("driver busy")
    assert calls["inc"] == 1
    assert manager._auto_target_preference == "ota"

    manager._last_attempt_source = "ota"
    manager._auto_target_preference = "ota"
    manager._note_connect_failure("connect error")
    assert manager._auto_target_preference == "saved"


def test_note_connect_success_persists_last_credentials_and_resets_saved_failures(
    fresh_wifi_module, monkeypatch
):
    wifi_mod = fresh_wifi_module
    manager = wifi_mod.WiFiManager.get_instance()
    calls = {"saved": None, "reset": 0}

    monkeypatch.setattr(
        wifi_mod,
        "save_last_successful_credentials",
        lambda ssid, password: calls.__setitem__("saved", (ssid, password)) or True,
    )
    monkeypatch.setattr(wifi_mod, "reset_saved_failure", lambda: calls.__setitem__("reset", calls["reset"] + 1) or True)

    manager._last_attempt_source = "saved"
    manager._last_attempt_ssid = "SavedNet"
    manager._last_attempt_password = "saved-pass"
    manager._auto_target_preference = "ota"
    manager._note_connect_success()

    assert calls["saved"] == ("SavedNet", "saved-pass")
    assert calls["reset"] == 1
    assert manager._auto_target_preference == "saved"


def test_poll_connect_reports_fail_reason_from_status(fresh_wifi_module):
    wifi_mod = fresh_wifi_module
    manager = wifi_mod.WiFiManager.get_instance()

    manager._connect_active = True
    manager.connecting = True
    manager._connect_started_ms = manager._now_ms()
    manager._connect_session_timeout_ms = 60_000
    manager.wlan._status = wifi_mod.STAT_WRONG_PASSWORD

    result = manager.poll_connect()
    assert result["state"] == "fail"
    assert result["reason"] == "wrong_password"
    assert manager.get_last_error() == "wrong_password"
