"""Mocked hardware tests for WiFiManager singleton/control behavior."""

def test_wifi_manager_is_singleton(fresh_wifi_module):
    wifi_mod = fresh_wifi_module
    manager_a = wifi_mod.WiFiManager.get_instance()
    manager_b = wifi_mod.WiFiManager()
    assert manager_a is manager_b
    manager_a.set_auto_reconnect(False)
    assert manager_b.get_auto_reconnect() is False


def test_wifi_manager_ensure_connected_starts_connect_when_disconnected(fresh_wifi_module):
    wifi_mod = fresh_wifi_module
    manager = wifi_mod.WiFiManager.get_instance()
    manager.wlan.active(True)

    connected = manager.ensure_connected(wait=False, timeout_s=1)
    assert connected is False
    assert manager.connecting is True
    assert len(manager.wlan.connect_calls) == 1


def test_wifi_manager_pause_resume_reconnect_flow(fresh_wifi_module):
    wifi_mod = fresh_wifi_module
    manager = wifi_mod.WiFiManager.get_instance()
    manager.set_auto_reconnect(True)
    manager.connecting = True

    previous = manager.pause_background_reconnect(reason="test pause", force_radio=True)
    assert previous is True
    assert manager.get_auto_reconnect() is False
    assert manager.connecting is False

    manager.resume_background_reconnect(previous_auto_reconnect=previous, reconnect_if_needed=False)
    assert manager.get_auto_reconnect() is True
