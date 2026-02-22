"""Shared desktop shims for running badge tests under CPython."""

import binascii
import hashlib
import importlib
import json
import os
import random
import sys
import time
import types

import pytest


_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TEST_DIR)
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
for _path in (_PROJECT_ROOT, _SRC_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _install_time_shims() -> None:
    if not hasattr(time, "ticks_ms"):
        time.ticks_ms = lambda: int(time.time() * 1000)
    if not hasattr(time, "ticks_diff"):
        time.ticks_diff = lambda a, b: int(a) - int(b)
    if not hasattr(time, "ticks_add"):
        time.ticks_add = lambda a, b: int(a) + int(b)
    if not hasattr(time, "sleep_ms"):
        time.sleep_ms = lambda ms: time.sleep(float(ms) / 1000.0)


def _install_micropython_module_shims() -> None:
    if "ubinascii" not in sys.modules:
        sys.modules["ubinascii"] = binascii

    if "uhashlib" not in sys.modules:
        uhashlib = types.ModuleType("uhashlib")
        uhashlib.sha1 = hashlib.sha1
        sys.modules["uhashlib"] = uhashlib

    if "ujson" not in sys.modules:
        sys.modules["ujson"] = json

    if "micropython" not in sys.modules:
        micropython = types.ModuleType("micropython")
        micropython.const = lambda value: value
        sys.modules["micropython"] = micropython

    if "urandom" not in sys.modules:
        urandom = types.ModuleType("urandom")
        urandom.random = random.random
        urandom.getrandbits = random.getrandbits
        sys.modules["urandom"] = urandom

    if "uos" not in sys.modules:
        sys.modules["uos"] = os

    if "framebuf" not in sys.modules:
        framebuf = types.ModuleType("framebuf")
        framebuf.RGB565 = 0
        framebuf.FrameBuffer = object
        sys.modules["framebuf"] = framebuf

    if "lvgl" not in sys.modules:
        lvgl = types.ModuleType("lvgl")
        lvgl.COLOR_FORMAT = types.SimpleNamespace(RGB565=0)
        lvgl.obj = types.SimpleNamespace(
            FLAG=types.SimpleNamespace(SCROLLABLE=0, HIDDEN=1)
        )
        lvgl.image_dsc_t = lambda value: value
        lvgl.image = lambda *_args, **_kwargs: None
        lvgl.color_hex = lambda value: value
        sys.modules["lvgl"] = lvgl

def _install_esp32_nvs_shim() -> None:
    if "esp32" in sys.modules:
        return

    esp32 = types.ModuleType("esp32")

    class DummyNVS:
        def __init__(self, namespace):
            self.namespace = namespace
            self._ints = {}
            self._blob = {}

        def set_i32(self, key, value):
            self._ints[key] = int(value)
            return True

        def get_i32(self, key):
            if key not in self._ints:
                raise OSError("ESP_ERR_NVS_NOT_FOUND")
            return self._ints[key]

        def set_blob(self, key, value):
            self._blob[key] = bytes(value)
            return True

        def get_blob(self, key, buf):
            if key not in self._blob:
                raise OSError("ESP_ERR_NVS_NOT_FOUND")
            value = self._blob[key]
            if len(value) > len(buf):
                raise OSError("ESP_ERR_NVS_INVALID_LENGTH")
            buf[: len(value)] = value
            return len(value)

        def commit(self):
            return True

    esp32.NVS = DummyNVS
    sys.modules["esp32"] = esp32


def _install_network_and_bluetooth_shims() -> None:
    if "bluetooth" not in sys.modules:
        bluetooth = types.ModuleType("bluetooth")
        bluetooth.UUID = lambda value: value
        sys.modules["bluetooth"] = bluetooth

    if "network" in sys.modules:
        return

    network = types.ModuleType("network")
    network.STAT_IDLE = 0
    network.STAT_CONNECTING = 1
    network.STAT_WRONG_PASSWORD = -3
    network.STAT_NO_AP_FOUND = -2
    network.STAT_CONNECT_FAIL = -1
    network.STAT_GOT_IP = 3
    network.STA_IF = 0
    network.IF_STA = 0

    class DummyWLAN:
        IF_STA = 0

        def __init__(self, _iface):
            self._active = False
            self._connected = False
            self._status = network.STAT_IDLE
            self.connect_calls = []
            self.disconnect_calls = 0
            self._ssid = ""
            self._mac = b"\xaa\xbb\xcc\xdd\xee\xff"

        def active(self, value=None):
            if value is None:
                return self._active
            self._active = bool(value)
            return self._active

        def isconnected(self):
            return self._connected

        def status(self, what=None):
            if what == "rssi":
                return -50
            if what == "channel":
                return 1
            if what == "bssid":
                return b"\x11\x22\x33\x44\x55\x66"
            if what == "authmode":
                return 3
            return self._status

        def ifconfig(self):
            return ("192.168.1.9", "255.255.255.0", "192.168.1.1", "8.8.8.8")

        def config(self, key):
            if key == "mac":
                return self._mac
            if key == "essid":
                return self._ssid
            return None

        def connect(self, ssid, password=None):
            self.connect_calls.append((ssid, password))
            self._ssid = ssid
            self._status = network.STAT_CONNECTING
            self._connected = False

        def disconnect(self):
            self.disconnect_calls += 1
            self._connected = False
            self._status = network.STAT_IDLE

        def scan(self):
            return []

    network.WLAN = DummyWLAN
    sys.modules["network"] = network


# Install shims as soon as conftest is imported so collection-time imports work.
_install_time_shims()
_install_micropython_module_shims()
_install_esp32_nvs_shim()
_install_network_and_bluetooth_shims()


class DummyLogger:
    def debug(self, *_args, **_kwargs):
        return None

    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


@pytest.fixture
def dummy_logger():
    return DummyLogger()


@pytest.fixture
def fresh_wifi_module():
    wifi_mod = importlib.import_module("cactuscon.hw.wifi")
    wifi_mod = importlib.reload(wifi_mod)
    wifi_mod.WiFiManager._instance = None
    return wifi_mod
