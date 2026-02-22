"""Main application coordinator for CactusCon14 badge."""

import gc
import asyncio
import time
try:
    from machine import WDT
except Exception:
    WDT = None

# Memory debug utility - import early to track memory usage during imports
from cactuscon.utils import mem_modules_summary, Logger

# Explicit imports - no package-level re-exports to keep module count low
from cactuscon.hw.bluetooth import BluetoothManager
from cactuscon.game.battle_manager import BattleManager
from cactuscon.game.comms import GameBTComms
from cactuscon.game.engine.characters import validate_and_cleanup_player_characters, is_valid_character, migrate_global_stats_to_creature
from cactuscon.prefs import (
    prefs,
    HANDLE_KEY,
    LEGACY_HANDLE_KEY,
    HANDLE_PENDING_KEY,
    HANDLE_REG_ERROR_KEY,
)
from cactuscon import config

from cactuscon.hw.pixels import NeoPixelController

# Conditionally import UI components only for normal badge mode
_HEADLESS_MODE = getattr(config, "AUTO_BATTLE_MODE", False)

if not _HEADLESS_MODE:
    import lvgl as lv
    from cactuscon.hw.wifi import WiFiManager
    from cactuscon.hw.screen import TFT

    # Import only GameUI - panels are lazy-loaded via PANEL_REGISTRY
    from cactuscon.ui.graphics import GameUI, PRELOAD_PANELS
    from cactuscon.ui.sprites import Sprite, SpriteActor, preload_essential_sprites, switch_player_creature_cache
    # Pre-import registration panel class so first-time registration flow
    # does not spend watchdog budget in dynamic import.
    from cactuscon.ui.panels.registration import RegistrationPanel

    # NO panel imports here - they are lazy-loaded on-demand by GameUI
    # See PANEL_REGISTRY in graphics.py for panel name -> module mapping
    from cactiotpad import CactIOTPadClient
    from cactiotpad.config import ClientConfig
    from cactiotpad.utils import default_device_id_generator
    from cactuscon.hw.power_meter import fuel_gauge
    # Glow LEDs
    np = NeoPixelController()
else:
    from cactuscon.game.engine.stations import get_station
    from cactuscon.game.auto_battle import AutoBattleComms

mem_modules_summary()


class BadgeApplication:
    """
    Main badge application coordinator.

    Manages initialization, registration, battle system, and main loop.
    Supports headless mode for gyms/stations (AUTO_BATTLE_MODE).
    """

    # Auto-test state machine states
    AUTO_TEST_IDLE = 0
    AUTO_TEST_GOTO_BATTLE = 1
    AUTO_TEST_SCANNING = 2
    AUTO_TEST_CHALLENGING = 3
    AUTO_TEST_IN_BATTLE = 4
    AUTO_TEST_COMPLETE = 5

    def __init__(self, config_overrides=None):
        """
        Initialize badge application.

        Args:
            config_overrides (dict, optional): Configuration overrides.
        """
        self.logger = Logger(config.LOG_LEVEL)
        self.headless = _HEADLESS_MODE

        # Apply configuration overrides if provided
        if config_overrides:
            for key, value in config_overrides.items():
                if hasattr(config, key):
                    setattr(config, key, value)

        # Load configuration from NVS
        config.load_from_nvs(prefs)

        if self.headless:
            self.logger.info("=" * 50)
            self.logger.info("BadgeApplication: HEADLESS AUTO-BATTLE MODE")
            self.logger.info("=" * 50)
        else:
            self.logger.info("BadgeApplication initializing...")
            self.logger.info(config.get_summary())

        # Core subsystems (headless mode only needs Bluetooth)
        self.wifi: WiFiManager|None = None  # Assigned in setup() for normal mode, not used in headless mode
        self.screen = None

        if not self.headless:
            self.wifi = WiFiManager.get_instance()
            self.screen = TFT()
            try:
                prefs.begin("cactuscon")
                brightness = prefs.get_int32("brightness", 100)
                prefs.end()
                brightness = max(10, min(100, brightness))
                self.screen.display.set_backlight(brightness)
            except Exception as e:
                self.logger.debug(f"Boot brightness apply failed: {e}")

        # Init power meter (not present on stations/headless builds)
        if not self.headless:
            try:
                fuel_gauge.quickStart()
            except Exception as e:
                self.logger.debug(f"Power meter init skipped: {e}")

        # Optional subsystems (initialized in setup())
        self.api_client: CactIOTPadClient|None = None
        self.bt_mgr = None
        self.game_bt = None
        self.battle_mgr = None

        # Application state (not used in headless mode)
        self.game_ui = None
        self.pending_show_panel = None

        # Track WiFi task so we can re-init safely if WiFi goes missing.
        self._wifi_task = None
        self.tasks = []
        self.wdt = None
        self._watchdog_last_feed_ms = 0
        self._init_watchdog()

        # Auto-test battle mode state
        self.auto_test_enabled = getattr(config, "AUTO_TEST_BATTLE", False)
        self.auto_test_state = self.AUTO_TEST_IDLE
        self.auto_test_last_action = 0
        self.auto_test_delay = getattr(config, "AUTO_TEST_DELAY_MS", 2000)
        self._last_stats_log = 0
        self._last_api_setup_ms = 0
        self._last_bg_chat_poll_ms = 0
        self._bg_chat_poll_interval_ms = 60_000
        self._bg_chat_poll_inflight = False
        self._bg_chat_poll_sessions = []
        self._bg_chat_poll_index = 0
        self._bg_chat_poll_new_count = 0
        self._bg_chat_poll_connect_started_ms = 0
        self._bg_chat_poll_connect_timeout_ms = 5000

        # Demo sprites (not used in headless mode)
        self.init_sprite = None
        self.demo_actor = None

    def _init_watchdog(self):
        """Enable hardware watchdog in production (or when explicitly configured)."""
        if WDT is None:
            return
        # machine.WDT cannot be disabled once started on ESP32 MicroPython.
        # In development, avoid arming it unless explicitly forced so CTRL+C
        # can return to REPL without a later watchdog reset.
        if config.DEVELOPMENT and not bool(getattr(config, "WATCHDOG_FORCE_IN_DEV", False)):
            self.logger.info("[WDT] disabled in development")
            return
        enabled = bool(getattr(config, "WATCHDOG_ENABLED", not config.DEVELOPMENT))
        if not enabled:
            return
        timeout_ms = int(getattr(config, "WATCHDOG_TIMEOUT_MS", 30000))
        try:
            self.wdt = WDT(timeout=timeout_ms)
            self._watchdog_last_feed_ms = 0
            self.logger.info(f"[WDT] enabled ({timeout_ms}ms)")
        except Exception as e:
            self.logger.warning(f"[WDT] init failed: {e}")
            self.wdt = None

    def _feed_watchdog(self, force=False):
        """Feed hardware watchdog at a bounded interval."""
        if self.wdt is None:
            return
        now = self._ticks_ms()
        feed_interval_ms = int(getattr(config, "WATCHDOG_FEED_INTERVAL_MS", 500))
        if not force and self._watchdog_last_feed_ms:
            if self._ticks_diff(now, self._watchdog_last_feed_ms) < feed_interval_ms:
                return
        try:
            self.wdt.feed()
            self._watchdog_last_feed_ms = now
        except Exception as e:
            self.logger.warning(f"[WDT] feed failed: {e}")

    def _watchdog_safe_sleep(self, delay_s):
        """
        Sleep helper for sync retry/backoff paths that keeps watchdog fed.

        This is passed into API client retry logic so transient network retries
        do not starve hardware watchdog feeding.
        """
        try:
            total_ms = int(float(delay_s) * 1000)
        except Exception:
            total_ms = 0
        if total_ms <= 0:
            return

        slice_ms = int(getattr(config, "WATCHDOG_SLEEP_SLICE_MS", 100) or 100)
        if slice_ms < 25:
            slice_ms = 25

        remaining_ms = total_ms
        while remaining_ms > 0:
            chunk = slice_ms if remaining_ms > slice_ms else remaining_ms
            self._feed_watchdog()
            try:
                time.sleep_ms(chunk)
            except Exception:
                time.sleep(chunk / 1000.0)
            # Keep UI responsive during sync retries when possible.
            if not self.headless:
                try:
                    lv.task_handler()
                except Exception:
                    pass
            remaining_ms -= chunk

    def _on_api_retry(self, attempt, max_retries, delay_s, error):
        """Retry callback hook for API client backoff."""
        try:
            self.logger.warning(
                f"[API] retry {attempt}/{max_retries} in {delay_s}s: {error}"
            )
        except Exception:
            pass
        self._feed_watchdog(force=True)

    def register_task(self, task):
        """Track a created asyncio task for coordinated cleanup."""
        if task is None:
            return None
        if self.tasks is None:
            self.tasks = []
        self.tasks.append(task)
        return task

    def cancel_all_tasks(self):
        """Cancel all tracked asyncio tasks and clear the registry."""
        for task in self.tasks or ():
            if not task:
                continue
            try:
                task.cancel()
            except Exception:
                pass
        self.tasks = []
        self._wifi_task = None

    def _load_assets(self, player_char_id=None):
        """
        Load initial assets (splash screen, demo sprites, character sprites).

        Only loads essential sprites: station creatures + player's evolution tree.
        This reduces memory usage from ~1.6MB (all 15 sprites) to ~800KB (8 sprites max).

        Args:
            player_char_id: Player's current character ID for evo tree loading.

        Returns:
            None
        """
        try:
            # Any runtime-loaded assets can be preloaded here
            self.logger.info("Pre-embedded assets at (cactuscon.ui.assets)")
            
            # Preload essential sprites: station creatures + player's evolution tree
            # LVGL handles scaling at render time using set_scale()
            self.logger.info("Preloading essential sprites (stations + player evo tree)...")
            result = preload_essential_sprites(
                player_char_id=player_char_id,
                progress_callback=lambda *_args, **_kwargs: self._feed_watchdog(),
            )
            self.logger.info(f"Sprite preload: {result['raw_loaded']} sprites in {result['total_time_ms']}ms")
        except Exception as e:
            self.logger.error(f"Failed to load assets: {e}")

    async def _setup_api_client(self):
        """
        Initialize CactIOTPad API client.

        Returns:
            None
        """
        if not self.wifi.is_connected():
            self.logger.warning("WiFi not connected, skipping API setup")
            return

        try:
            self.logger.info("Initializing CactIOTPad client...")
            client_config = ClientConfig(
                base_url=config.CACTIOT_URL,
                device_type=config.CACTIOT_DEVICE_TYPE,
                device_version=config.CACTIOT_DEVICE_VERSION,
                nvs_lock=prefs.lock,
                verify_ssl=config.CACTIOT_VERIFY_SSL,
                timeout=config.CACTIOT_TIMEOUT,
                max_retries=config.CACTIOT_MAX_RETRIES,
                sleep_fn=self._watchdog_safe_sleep,
                on_retry=self._on_api_retry,
                debug=config.DEVELOPMENT,
            )
            self.api_client = CactIOTPadClient(config=client_config)

            # Health check
            if self.api_client.health_check():
                self.logger.info("API health check: OK")
            else:
                self.logger.warning("API health check failed")

        except Exception as e:
            self.logger.error(f"Failed to initialize API client: {e}")
            self.api_client = None

    async def _setup_bluetooth(self, player_config=None):
        """
        Orchestrate Bluetooth and battle manager initialization.
        
        Args:
            player_config: Pre-gathered player config dict. If None, will gather it.
        """
        try:
            self.logger.info("Initializing Bluetooth...")
            if player_config is None:
                player_config = self._gather_player_config()
            self._init_bluetooth_manager()
            self._init_game_comms(player_config)
            self._init_battle_manager(player_config)
            self.logger.info("Bluetooth and battle manager initialized")
        except Exception as e:
            self.logger.error(f"Failed to initialize Bluetooth: {e}")
            self.bt_mgr = None
            self.game_bt = None
            self.battle_mgr = None

    def _gather_player_config(self):
        """
        Gather player-related configuration from prefs, config, and env.
        Returns a dict with device_name, player_character_id, station_id, battle_timeout_ms.
        
        Also validates and cleans up the player's character inventory, removing
        any characters that are no longer in the evolution tree and assigning
        a random starter if needed.
        """
        from cactuscon.game.engine.characters import get_random_starter, get_player_pack, ACTIVE_CHAR_KEY

        def _read_active_character():
            """Read active character from canonical key first, then legacy fallback."""
            active = ""
            try:
                pack = get_player_pack(prefs)
                active = (pack or {}).get("active_character", "") or ""
            except Exception:
                active = ""
            if not active:
                try:
                    # Legacy fallback for older builds.
                    active = prefs.get_string("character", "")
                except Exception:
                    active = ""
            return active
        
        # Device name
        try:
            device_name = prefs.get_string(
                HANDLE_KEY,
                prefs.get_string(LEGACY_HANDLE_KEY, ""),
            )
        except Exception:
            device_name = ""

        # Validate and cleanup player characters before loading
        # This removes any invalid characters and assigns a random starter if needed
        try:
            cleanup_result = validate_and_cleanup_player_characters(prefs)
            if cleanup_result['cleaned']:
                self.logger.info(f"Character cleanup performed: {cleanup_result}")
                if cleanup_result['removed_chars']:
                    self.logger.warning(
                        f"Removed invalid characters from inventory: {cleanup_result['removed_chars']}"
                    )
                if cleanup_result['new_active']:
                    self.logger.info(
                        f"Assigned new starter character: {cleanup_result['new_active']}"
                    )
                if cleanup_result['level_reset']:
                    self.logger.info("Reset player level to 1 and XP to 0 for new character")
        except Exception as e:
            self.logger.warning(f"Error during character validation: {e}")

        # Character ID - reload after cleanup (validation should have set a valid active)
        try:
            saved_character = _read_active_character()
            self.logger.info(f"Saved active character from prefs: '{saved_character}'")
        except Exception as e:
            self.logger.warning(f"Error reading saved active character: {e}")
            saved_character = ""
        
        # Validate the saved character is still valid
        if saved_character and not is_valid_character(saved_character):
            self.logger.warning(
                f"Saved character '{saved_character}' is not valid, will use validated active"
            )
            saved_character = ""
        
        # Check config fallback - but only if it's valid
        config_character = getattr(config, "PLAYER_CHARACTER_ID", "")
        if config_character and not is_valid_character(config_character):
            self.logger.warning(
                f"Config PLAYER_CHARACTER_ID '{config_character}' is not valid, ignoring"
            )
            config_character = ""
        
        # If we recovered only legacy key, mirror it into canonical key.
        if saved_character and is_valid_character(saved_character):
            try:
                prefs.begin(write=True, context="app.migrate_active_character")
                prefs.set_string(ACTIVE_CHAR_KEY, saved_character)
                prefs.end()
            except Exception:
                try:
                    prefs.end()
                except Exception:
                    pass

        player_character_id = saved_character or config_character
        
        # If still no valid character, assign a random starter
        if not player_character_id or not is_valid_character(player_character_id):
            self.logger.info("No valid character set, assigning random starter")
            try:
                cleanup_result = validate_and_cleanup_player_characters(prefs)
                if cleanup_result['new_active']:
                    player_character_id = cleanup_result['new_active']
                    self.logger.info(f"Assigned random starter: {player_character_id}")
                else:
                    # Cleanup may have preserved an existing active without setting new_active.
                    current_active = _read_active_character()
                    if current_active and is_valid_character(current_active):
                        player_character_id = current_active
                    else:
                        # Cleanup didn't assign one, force random selection
                        player_character_id = get_random_starter(exclude_hackachu_line=True)
                        if player_character_id:
                            self.logger.info(f"Force-assigned random starter: {player_character_id}")
            except Exception as e:
                self.logger.error(f"Failed to assign valid character: {e}")
                # Last resort - get random starter directly
                player_character_id = get_random_starter(exclude_hackachu_line=True)
        
        # Final check - if still nothing, we have a critical error
        if not player_character_id:
            self.logger.error("CRITICAL: Could not assign any character!")
        else:
            # Migrate any existing global player stats to per-creature tracking
            # This is a one-time migration that moves old pl_lvl/pl_xp keys to the active creature
            try:
                migration_result = migrate_global_stats_to_creature(prefs)
                if migration_result:
                    self.logger.info(
                        f"Migrated global stats to {migration_result['char_id']}: "
                        f"level={migration_result['migrated_level']}, xp={migration_result['migrated_xp']}"
                    )
            except Exception as e:
                self.logger.warning(f"Error migrating global stats: {e}")

        # Station ID
        station_id = getattr(config, "STATION_ID", None)
        station_mode = getattr(config, "AUTO_BATTLE_MODE", False)
        if station_mode and station_id:
            try:
                station = get_station(station_id)
                if station:
                    player_character_id = station.character_id
                    # Use station name as Bluetooth/device name in auto-battle mode
                    device_name = station.name or device_name
                    self.logger.info(
                        f"Station mode: using character '{player_character_id}' and device_name '{device_name}' from station '{station_id}'"
                    )
                else:
                    self.logger.warning(
                        f"Station '{station_id}' not found, using config character"
                    )
            except Exception as e:
                self.logger.warning(f"Error loading station info: {e}")

        # Battle timeout (hard cap for all battles)
        battle_timeout_ms = getattr(config, "BATTLE_DURATION_CAP_MS", 300000)

        self.logger.info(f"[APP] Player character configured: {player_character_id}")
        return {
            "device_name": device_name,
            "player_character_id": player_character_id,
            "station_id": station_id,
            "battle_timeout_ms": battle_timeout_ms,
        }

    def _init_bluetooth_manager(self):
        """
        Initialize the BluetoothManager instance.
        """
        self.bt_mgr = BluetoothManager(
            max_devices=config.BT_MAX_DEVICES,
            rssi_threshold=config.BT_RSSI_THRESHOLD,
            logger_level=config.LOG_LEVEL,
        )

    def _init_game_comms(self, player_config):
        """
        Initialize the GameBTComms or AutoBattleComms instance.
        """
        device_name = player_config["device_name"]
        if getattr(config, "AUTO_BATTLE_MODE", False):
            self.logger.info("AUTO-BATTLE TESTING MODE ENABLED")
            station_id = player_config.get("station_id")
            self.game_bt = AutoBattleComms(
                self.bt_mgr,
                device_name=device_name,
                auto_battle_duration_ms=getattr(
                    config, "AUTO_BATTLE_DURATION_MS", 10000
                ),
                station_id=station_id,
                logger_level=config.LOG_LEVEL,
            )
            self.game_bt.start_auto_battle_mode(
                getattr(config, "AUTO_BATTLE_DURATION_MS", 10000)
            )
        else:
            self.game_bt = GameBTComms(
                self.bt_mgr, device_name=device_name, logger_level=config.LOG_LEVEL
            )

    def _init_battle_manager(self, player_config):
        """
        Initialize the BattleManager instance.
        """
        self.battle_mgr = BattleManager(
            self.game_bt,
            screen=self.screen,
            player_character_id=player_config["player_character_id"],
            battle_timeout_ms=player_config["battle_timeout_ms"],
            logger_level=config.LOG_LEVEL,
        )

    def _save_registration_error(self, message):
        try:
            prefs.begin("cactuscon", write=True, context="registration.save_error")
            prefs.set_string(HANDLE_REG_ERROR_KEY, message or "")
            prefs.end()
        except Exception as e:
            self.logger.warning(f"Failed to save registration error: {e}")

    def _ensure_wifi_manager(self):
        """
        Ensure the app-owned WiFi manager exists and is wired into the UI.
        This guards against cases where WiFi failed to init during boot.
        """
        if self.headless:
            return
        if self.wifi:
            return
        try:
            self.logger.warning("[WIFI] manager missing; reinitializing")
            self.wifi = WiFiManager.get_instance()
            if self.game_ui:
                self.game_ui.set_wifi_manager(self.wifi)
            if self.tasks is not None and self._wifi_task is None:
                self._wifi_task = self.register_task(asyncio.create_task(self.wifi.loop_forever()))
        except Exception as e:
            self.logger.error(f"[WIFI] reinit failed: {e}")

    def _check_registration(self):
        """
        Check device registration status.
        Checks local NVS, then API. Restores handle from API if needed.

        Returns:
            bool: True if registration is required, False otherwise.
        """
        # Check local handle
        local_handle = ""
        try:
            local_handle = prefs.get_string(
                HANDLE_KEY,
                prefs.get_string(LEGACY_HANDLE_KEY, ""),
            )
        except Exception as e:
            self.logger.warning(f"Could not read handle from NVS: {e}")

        # Track if we need to sync a locally stored handle to the API
        pending_registration = False
        try:
            pending_registration = prefs.get_bool(HANDLE_PENDING_KEY, False)
        except Exception as e:
            self.logger.warning(f"Could not read pending registration flag: {e}")

        if local_handle:
            self.logger.info(f"Using local handle: {local_handle}")

        if not self.api_client:
            self.logger.warning("API client not available")
            return not local_handle

        # If we have a local handle with no pending sync, skip API lookup
        if local_handle and not pending_registration:
            return False

        # Get device ID for API lookup / pending registration
        try:
            device_id = default_device_id_generator()
        except Exception as e:
            self.logger.warning(f"Could not get device ID: {e}")
            return not local_handle

        # Check API for device registration (single attempt to avoid long hangs)
        try:
            device_info = self.api_client.get_device_info(
                device_id=device_id,
                timeout=config.CACTIOT_TIMEOUT,
                max_retries=0,
                include_auth=True,
            )
            if device_info and device_info.handle:
                # /devices/{id} returns type/version only when authenticated.
                is_authenticated_view = bool(getattr(device_info, "type", None))

                if is_authenticated_view:
                    self.logger.info(f"Device registered: {device_info.handle}")

                    # Restore handle to NVS if missing locally
                    if not local_handle and device_info.handle:
                        self.logger.info(f"Restoring handle from API: {device_info.handle}")
                        try:
                            prefs.begin("cactuscon", write=True, context="registration.restore_handle")
                            prefs.set_string(HANDLE_KEY, device_info.handle)
                            # Keep legacy key in sync for older builds
                            try:
                                prefs.set_string(LEGACY_HANDLE_KEY, device_info.handle)
                            except Exception:
                                pass
                            prefs.set_bool(HANDLE_PENDING_KEY, False)
                            prefs.set_string(HANDLE_REG_ERROR_KEY, "")
                            prefs.end()
                        except Exception as e:
                            self.logger.error(f"Failed to save handle: {e}")
                    elif pending_registration:
                        try:
                            prefs.begin("cactuscon", write=True, context="registration.clear_pending")
                            prefs.set_bool(HANDLE_PENDING_KEY, False)
                            prefs.set_string(HANDLE_REG_ERROR_KEY, "")
                            prefs.end()
                        except Exception as e:
                            self.logger.warning(f"Failed to clear pending registration: {e}")

                    return False

                # If a deferred handle only gets the public profile response,
                # registration has not been completed with API auth yet.
                if pending_registration and local_handle:
                    self.logger.info("Deferred registration still unauthenticated; syncing local handle")
                    try:
                        self.api_client.register(
                            device_id=device_id,
                            handle=local_handle,
                            timeout=self._sync_api_timeout_s(),
                            max_retries=0,
                            retry=True,
                        )
                        try:
                            prefs.begin("cactuscon", write=True, context="registration.clear_pending")
                            prefs.set_bool(HANDLE_PENDING_KEY, False)
                            prefs.set_string(HANDLE_REG_ERROR_KEY, "")
                            prefs.end()
                        except Exception as pending_e:
                            self.logger.warning(f"Failed to clear pending registration: {pending_e}")
                        return False
                    except Exception as reg_e:
                        self.logger.warning(f"Deferred registration sync failed: {reg_e}")
                        reg_status = getattr(reg_e, "status_code", None)
                        if reg_status in (400, 409, 422):
                            self._save_registration_error(str(reg_e))
                            return True
                        return False

        except Exception as e:
            # If device isn't registered, attempt to register using local handle
            try:
                status_code = getattr(e, "status_code", None)
                error_code = getattr(e, "error_code", "")
            except Exception:
                status_code = None
                error_code = ""

            if status_code == 404 or error_code == "NOT_FOUND":
                if local_handle:
                    self.logger.info("Device not registered; attempting to register local handle")
                    try:
                        self.api_client.register(
                            device_id=device_id,
                            handle=local_handle,
                            timeout=self._sync_api_timeout_s(),
                            max_retries=0,
                            retry=True,
                        )
                        try:
                            prefs.begin("cactuscon", write=True, context="registration.clear_pending")
                            prefs.set_bool(HANDLE_PENDING_KEY, False)
                            prefs.set_string(HANDLE_REG_ERROR_KEY, "")
                            prefs.end()
                        except Exception as pending_e:
                            self.logger.warning(f"Failed to clear pending registration: {pending_e}")
                        return False
                    except Exception as reg_e:
                        self.logger.warning(f"Local registration attempt failed: {reg_e}")
                        reg_status = getattr(reg_e, "status_code", None)
                        if reg_status in (400, 409, 422):
                            self._save_registration_error(str(reg_e))
                            return True
                        return False

            self.logger.debug(f"Device not found in API: {e}")

        if local_handle:
            if pending_registration:
                try:
                    pending_error = prefs.get_string(HANDLE_REG_ERROR_KEY, "")
                except Exception:
                    pending_error = ""
                if pending_error:
                    self.logger.info("Local handle pending with error; registration required")
                    return True
                self.logger.info("Local handle set; registration pending (no error)")
                return False
            self.logger.info("Local handle set; registration deferred")
            return False

        # No registration found locally or remotely
        self.logger.info("No handle set - registration required")
        return True

    def _log_auto_battle_stats(self):
        """Log auto-battle statistics periodically."""
        if self.game_bt and hasattr(self.game_bt, "get_auto_battle_stats"):
            stats = self.game_bt.get_auto_battle_stats()
            self.logger.info(f"Auto-Battle Stats: {stats}")

    def _update_auto_test(self):
        """
        Update auto-test battle state machine.

        Automatically navigates: Main Menu -> Battle -> Select First Opponent -> Auto-Attack

        Checks state of other components to know when to proceed, rather than
        blindly waiting fixed delays.
        """
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.auto_test_last_action)

        # Minimum delay between actions to avoid spamming
        min_delay = 500  # 500ms minimum between checks
        if elapsed < min_delay:
            return

        if self.auto_test_state == self.AUTO_TEST_GOTO_BATTLE:
            # Step 1: Wait for initial delay, then go to battle matchmaking panel
            if elapsed < self.auto_test_delay:
                return  # Still waiting initial delay

            self.logger.info("AUTO-TEST: Going to battle matchmaking...")
            if self.game_ui:
                self.game_ui.show_panel("battle_matchmaking")
            self.auto_test_state = self.AUTO_TEST_SCANNING
            self.auto_test_last_action = now

        elif self.auto_test_state == self.AUTO_TEST_SCANNING:
            # Step 2: Wait for scan to complete and opponents to appear
            # Check the matchmaking panel's state directly
            panel = (
                self.game_ui.panel_instances.get("battle_matchmaking")
                if self.game_ui
                else None
            )

            if panel:
                # Check if still scanning
                if panel.scanning:
                    # Still scanning, wait more
                    return

                # Scan complete - check if we have opponents
                if panel.opponents and len(panel.opponents) > 0:
                    # Found opponents! Challenge the first one
                    opponent = panel.opponents[0]
                    self.logger.info(
                        f"AUTO-TEST: Found {len(panel.opponents)} opponents, challenging: {opponent.name}"
                    )

                    if self.battle_mgr:
                        success = self.battle_mgr.challenge_opponent(opponent)
                        if success:
                            self.auto_test_state = self.AUTO_TEST_CHALLENGING
                            self.auto_test_last_action = now
                        else:
                            self.logger.warning(
                                "AUTO-TEST: Challenge failed, will retry on next scan"
                            )
                else:
                    # No opponents yet - wait for next scan cycle
                    # The panel auto-refreshes every 3 seconds
                    if elapsed > 5000:
                        self.logger.debug(
                            "AUTO-TEST: Still waiting for opponents..."
                        )
                        self.auto_test_last_action = now  # Reset to avoid spam
            else:
                # Panel not loaded yet, wait
                if elapsed > 3000:
                    self.logger.warning(
                        "AUTO-TEST: Matchmaking panel not loaded, retrying..."
                    )
                    self.auto_test_state = self.AUTO_TEST_GOTO_BATTLE
                    self.auto_test_last_action = now

        elif self.auto_test_state == self.AUTO_TEST_CHALLENGING:
            # Step 3: Wait for battle to start
            if self.battle_mgr and self.battle_mgr.in_battle:
                self.logger.info(
                    "AUTO-TEST: Battle started! Will auto-select moves."
                )
                self.auto_test_state = self.AUTO_TEST_IN_BATTLE
                self.auto_test_last_action = now
            elif elapsed > 10000:
                # Timeout waiting for battle
                error = self.battle_mgr.last_error if self.battle_mgr else None
                self.logger.warning(
                    f"AUTO-TEST: Battle didn't start in time, error={error}, restarting..."
                )
                self.auto_test_state = self.AUTO_TEST_GOTO_BATTLE
                self.auto_test_last_action = now

        elif self.auto_test_state == self.AUTO_TEST_IN_BATTLE:
            # Step 4: Auto-select first move when it's our turn
            if not self.battle_mgr:
                self.auto_test_state = self.AUTO_TEST_COMPLETE
                return

            if not self.battle_mgr.in_battle:
                # Battle ended
                self.logger.info("AUTO-TEST: Battle ended!")
                self.auto_test_state = self.AUTO_TEST_COMPLETE
                self.auto_test_last_action = now
            elif self.game_bt and self.game_bt.is_our_turn():
                # Check we haven't already selected this turn
                if not self.battle_mgr.waiting_for_opponent:
                    # It's our turn - select first available move
                    if self.battle_mgr.player_moves:
                        move_id = self.battle_mgr.player_moves[0]
                        self.logger.info(f"AUTO-TEST: Selecting move {move_id}")
                        self.battle_mgr.use_move(move_id)
                        self.auto_test_last_action = now

        elif self.auto_test_state == self.AUTO_TEST_COMPLETE:
            # Step 5: Battle finished - wait then restart test cycle
            if elapsed > 5000:  # 5 second pause before restart
                self.logger.info("AUTO-TEST: Cycle complete, restarting...")
                self.auto_test_state = self.AUTO_TEST_GOTO_BATTLE
                self.auto_test_last_action = now

    async def _run_headless(self):
        """
        Headless auto-battle loop for gyms/stations.

        Runs indefinitely, processing auto-battle connections.
        """
        self.logger.info("=" * 50)
        self.logger.info("HEADLESS AUTO-BATTLE LOOP STARTED")
        self.logger.info("Waiting for challenger connections...")
        self.logger.info("=" * 50)

        while True:
            try:
                self._feed_watchdog()
                await asyncio.sleep(0.1)  # 100ms cycle

                # Update battle manager (handles timeout, panel transitions, etc.)
                # This also calls game_bt.update() internally
                if self.battle_mgr:
                    self.battle_mgr.update()
                elif self.game_bt:
                    # Fallback if no battle manager
                    self.game_bt.update()

                # Periodic stats logging (every ~30 seconds)
                if hasattr(self, "_last_stats_log"):
                    if time.ticks_diff(time.ticks_ms(), self._last_stats_log) > 30000:
                        self._log_auto_battle_stats()
                        self._last_stats_log = time.ticks_ms()
                else:
                    self._last_stats_log = time.ticks_ms()

            except Exception as e:
                self.logger.error(f"Error in headless loop: {e}")
                gc.collect()
                await asyncio.sleep(1)

    async def _run_normal(self):
        """
        Normal badge run loop with full UI.
        """
        # Ensure WiFi manager exists before starting loop tasks.
        self._ensure_wifi_manager()
        # No manual panel registration needed - PANEL_REGISTRY handles it
        # Panels are imported on-demand when show_panel() is called

        # Check if registration is required (no handle set)
        needs_registration = self._check_registration()

        if not config.DEVELOPMENT and needs_registration:
            # Show registration panel - blocks until registered
            self.pending_show_panel = "registration"
            self.logger.info("Registration required - showing registration panel")
        else:
            # Set character panel as home screen (Digimon-style virtual pet view)
            self.pending_show_panel = "character"

        # Wire up BattleManager to GameUI for panel transitions
        if self.battle_mgr:
            self.battle_mgr.set_game_ui(self.game_ui)

        # Start async tasks
        self.logger.info("Starting main loop...")

        self.tasks = []
        self.register_task(asyncio.create_task(self.screen.loop_forever()))
        if self.wifi:
            self._wifi_task = self.register_task(asyncio.create_task(self.wifi.loop_forever()))

        # Auto-test: start after a short delay
        if self.auto_test_enabled:
            self.logger.info(
                "AUTO-TEST MODE ENABLED - will auto-battle after startup"
            )
            self.auto_test_state = self.AUTO_TEST_GOTO_BATTLE
            self.auto_test_last_action = time.ticks_ms()

        # Main event loop
        self.logger.info(
            f"Entering main loop, pending_show_panel={self.pending_show_panel}"
        )
        # Memory monitoring timer (every 15 seconds)
        _last_mem_log_ms = time.ticks_ms()
        _MEM_LOG_INTERVAL_MS = 15000 if config.DEVELOPMENT else 60000  # 15s dev, 60s prod
        
        while True:
            try:
                self._feed_watchdog()
                await asyncio.sleep(0)  # Yield to async tasks

                # If WiFi manager ever goes missing, re-init and reattach to UI.
                self._ensure_wifi_manager()
                
                # Periodic memory monitoring
                now_ms = time.ticks_ms()
                if time.ticks_diff(now_ms, _last_mem_log_ms) >= _MEM_LOG_INTERVAL_MS:
                    gc.collect()
                    free = gc.mem_free()
                    alloc = gc.mem_alloc()
                    total = free + alloc
                    pct = (alloc / total) * 100 if total > 0 else 0
                    msg = f"[MEM] MainLoop: {alloc:,} used / {free:,} free ({pct:.1f}% used)"
                    if config.DEVELOPMENT:
                        self.logger.info(msg)
                    else:
                        print(msg)
                    _last_mem_log_ms = now_ms

                # Show pending panel on first iteration
                if self.pending_show_panel and self.game_ui:
                    panel_name = self.pending_show_panel
                    self.logger.info(f"Transitioning from loading to '{panel_name}'")
                    success = self.game_ui.show_panel(panel_name)
                    self.logger.info(f"Panel transition result: {success}")
                    if success:
                        self.pending_show_panel = None
                    else:
                        gc.collect()
                        await asyncio.sleep(0.1)
                        continue

                    # Pass API client to panels that need network access
                    if (
                        panel_name in ("registration", "chat")
                        and panel_name in self.game_ui.panel_instances
                    ):
                        if self.api_client is None and self.wifi and self.wifi.is_connected():
                            await self._setup_api_client()
                        self.game_ui.panel_instances[panel_name].set_api_client(
                            self.api_client
                        )
                        if panel_name == "chat":
                            try:
                                self.game_ui.panel_instances[panel_name].bt = self.bt_mgr
                            except Exception:
                                pass
                            self.game_ui.panel_instances[panel_name].wifi = self.wifi
                    else:
                        for panel in self.game_ui.panel_instances:
                            if panel not in PRELOAD_PANELS and panel != panel_name:
                                # unload panels to free memory
                                self.game_ui.panel_instances[panel].unload()

                # Update battle manager
                if self.battle_mgr:
                    self.battle_mgr.update()

                # Lazy API client setup once WiFi comes online
                if self.wifi and self.api_client is None and self.wifi.is_connected():
                    if time.ticks_diff(time.ticks_ms(), self._last_api_setup_ms) > 2000:
                        self._last_api_setup_ms = time.ticks_ms()
                        self.logger.info("[API] WiFi online, initializing API client...")
                        await self._setup_api_client()
                        if self.api_client and self.game_ui:
                            try:
                                self.game_ui.api_client = self.api_client
                                if "chat" in self.game_ui.panel_instances:
                                    self.game_ui.panel_instances["chat"].api_client = self.api_client
                                    self.game_ui.panel_instances["chat"].bt = self.bt_mgr
                                if "registration" in self.game_ui.panel_instances:
                                    self.game_ui.panel_instances["registration"].set_api_client(self.api_client)
                                self.logger.info("[API] API client seeded to panels")
                            except Exception as e:
                                self.logger.debug(f"[API] Panel seed failed: {e}")

                # Power-save background chat sync while outside API-heavy panels.
                await self._maybe_background_chat_poll()

                # Auto-test: run automated battle test
                if self.auto_test_enabled:
                    self._update_auto_test()

                # Normal operation - run UI loop
                if self.game_ui:
                    if self.game_ui.active:
                        self.game_ui.loop()

            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                try:
                    import traceback
                    traceback.print_exc()
                except Exception:
                    try:
                        import sys
                        sys.print_exception(e)
                    except Exception:
                        pass
                gc.collect()
                await asyncio.sleep(1)
                # Don't re-raise - try to recover

    def _ticks_ms(self):
        try:
            return time.ticks_ms()
        except Exception:
            return int(time.time() * 1000)

    def _ticks_diff(self, now_ms, last_ms):
        try:
            return time.ticks_diff(now_ms, last_ms)
        except Exception:
            return now_ms - last_ms

    def _sync_api_timeout_s(self):
        """Bound synchronous API calls so they don't exhaust watchdog budget."""
        timeout_s = int(getattr(config, "CACTIOT_TIMEOUT", 10) or 10)
        return max(2, min(timeout_s, 5))

    async def _maybe_background_chat_poll(self):
        if not self.game_ui or not self.wifi or not self.api_client:
            return
        # Don't background-poll while a foreground panel actively controls
        # WiFi usage (e.g. connect flow, chat, registration).
        if self._wifi_panel_demands_radio():
            if self._bg_chat_poll_inflight:
                self._bg_chat_finish_cycle()
            return
        # Pause polling during battle/matchmaking to avoid extra radio load.
        if self._bg_chat_should_pause():
            if self._bg_chat_poll_inflight:
                self._bg_chat_finish_cycle()
            return

        now_ms = self._ticks_ms()
        if not self._bg_chat_poll_inflight:
            # Rate-limit the start of a background poll cycle.
            if self._last_bg_chat_poll_ms and self._ticks_diff(now_ms, self._last_bg_chat_poll_ms) < self._bg_chat_poll_interval_ms:
                return
            # Snapshot session list once per cycle to avoid churn mid-poll.
            sessions = self.api_client.storage.get_chat_sessions().get("sessions", {})
            session_hashes = list(sessions.keys()) if sessions else []
            # Back off polling window even when there are no sessions.
            self._last_bg_chat_poll_ms = now_ms
            if not session_hashes:
                self._power_save_wifi_if_idle("background chat: no sessions")
                return
            # Begin incremental polling cycle (one session per loop tick).
            self._bg_chat_poll_inflight = True
            self._bg_chat_poll_sessions = session_hashes
            self._bg_chat_poll_index = 0
            self._bg_chat_poll_new_count = 0
            self._bg_chat_poll_connect_started_ms = 0
            self.wifi.set_auto_reconnect(True)

        # Non-blocking WiFi bring-up: don't hold up main loop waiting here.
        if not self.wifi.is_connected():
            if not self._bg_chat_poll_connect_started_ms:
                self._bg_chat_poll_connect_started_ms = now_ms
                # Kick off connect and return; main loop keeps running.
                self.wifi.connect(timeout_s=min(getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10), 5), enable_auto_reconnect=True)
                return
            # Abort the cycle if we can't connect quickly.
            if self._ticks_diff(now_ms, self._bg_chat_poll_connect_started_ms) > self._bg_chat_poll_connect_timeout_ms:
                self._bg_chat_finish_cycle()
            return

        # Keep memory safety guard active during incremental polling.
        if self._is_low_memory():
            self.logger.warning("[CHAT] background polling paused: low memory")
            self._bg_chat_finish_cycle()
            return

        # Process one session per tick to minimize UI impact.
        if self._bg_chat_poll_index >= len(self._bg_chat_poll_sessions):
            # End of cycle: surface unread flag and optional LED pulse.
            if self._bg_chat_poll_new_count > 0:
                try:
                    self.game_ui.chat_has_unread = True
                except Exception:
                    pass
                try:
                    if not self.headless:
                        await np.flash_chat_alert(repeats=3, interval_ms=150)
                except Exception as e:
                    self.logger.debug(f"Chat LED alert failed: {e}")
            self._bg_chat_finish_cycle()
            return

        session_hash = self._bg_chat_poll_sessions[self._bg_chat_poll_index]
        try:
            # Fetch/ack a small batch to keep RAM and time bounded.
            self._bg_chat_poll_new_count += int(
                self.api_client.sync_chat_messages(session_hash, limit=10, ack=True) or 0
            )
        except Exception:
            pass
        self._bg_chat_poll_index += 1
        # Advance timestamp for each processed session to avoid overlap/rerun storms.
        self._last_bg_chat_poll_ms = self._ticks_ms()

    def _bg_chat_finish_cycle(self):
        self._bg_chat_poll_inflight = False
        self._bg_chat_poll_sessions = []
        self._bg_chat_poll_index = 0
        self._bg_chat_poll_new_count = 0
        self._bg_chat_poll_connect_started_ms = 0
        self._last_bg_chat_poll_ms = self._ticks_ms()
        self._power_save_wifi_if_idle("background chat finished")

    def _wifi_panel_demands_radio(self):
        active_panel = None
        try:
            active_panel = getattr(self.game_ui, "current_panel", None) if self.game_ui else None
        except Exception:
            active_panel = None
        return active_panel in ("registration", "chat", "wifi_connect", "handle_edit")

    def _power_save_wifi_if_idle(self, reason="idle"):
        if not self.wifi:
            return
        if self._bg_chat_poll_inflight:
            return
        if self._wifi_panel_demands_radio():
            return
        try:
            snapshot = self.wifi.get_status_snapshot()
            if snapshot.get("is_connected") or snapshot.get("active") or getattr(self.wifi, "connecting", False):
                self.logger.info(f"[WIFI] power save: disabling WiFi ({reason})")
                self.wifi.disconnect()
        except Exception as e:
            self.logger.debug(f"[WIFI] power-save disconnect skipped ({reason}): {e}")

    def _bg_chat_should_pause(self):
        if not self.battle_mgr:
            return False
        try:
            if self.battle_mgr.is_in_battle():
                return True
        except Exception:
            pass
        try:
            if getattr(self.battle_mgr, "in_battle", False):
                return True
            if getattr(self.battle_mgr, "matchmaking_enabled", False):
                return True
        except Exception:
            pass
        return False

    def _is_low_memory(self):
        try:
            # Force a collection before measuring so transient garbage
            # doesn't trip the low-memory guard.
            gc.collect()
            free = gc.mem_free()
            alloc = gc.mem_alloc()
            total = free + alloc
            if total <= 0:
                return False
            return (free / total) < 0.10
        except Exception:
            return False

    async def initialize(self):
        """
        Initialize all badge subsystems.

        Normal mode: Core (WiFi, screen) -> Network (API) -> Optional (BT)
        Headless mode: Bluetooth only

        Returns:
            None
        """
        if self.headless:
            # Headless mode - only initialize Bluetooth for auto-battle
            self.logger.info("=== Headless Initialization ===")
            self._feed_watchdog(force=True)
            await self._setup_bluetooth()
            self._feed_watchdog(force=True)
            self.logger.info("=== Headless Initialization Complete ===")
            return

        np.fade_in((255,0,0), duration_ms=3000)
        #np_task = asyncio.create_task(np.pulse(color=(0, 255, 0)))

        # Setup game UI
        self.game_ui = GameUI(self.screen, memory_efficient=False)
        self.game_ui.set_pixels_controller(np)
        self.game_ui.register_panel("registration", RegistrationPanel)
        
        # Pin map buffer early to avoid heap fragmentation later.
        try:
            from cactuscon.ui.panels import cactuscon_info
            cactuscon_info.ensure_map_buffer_pinned()
        except Exception as e:
            self.logger.warning(f"[MAP] pin buffer init failed: {e}")

        # Show loading/splash screen immediately (panel imported on-demand)
        self.logger.info("Showing splash screen...")
        self.game_ui.show_panel("loading")

        loading_panel = None
        while not loading_panel:
            self._feed_watchdog()
            # Wait for loading panel to be available
            if self.game_ui and "loading" in self.game_ui.panel_instances:
                loading_panel = self.game_ui.panel_instances["loading"]
            else:
                self.logger.info("Waiting for loading panel to initialize...")
                await asyncio.sleep(0.2)

        # Normal badge mode - full initialization
        self.logger.info("=== Phase 1: Core Initialization ===")

        # Gather player config early to know which character's sprites to preload
        player_config = self._gather_player_config()
        player_char_id = player_config.get("player_character_id")

        # Load assets (only essential sprites: stations + player evo tree)
        loading_panel.set_status("Loading assets...", 5)
        self._load_assets(player_char_id=player_char_id)

        # Connect WiFi
        loading_panel.set_status("Connecting to WiFi...", 20)
        timeout_s = getattr(config, "WIFI_CONNECT_TIMEOUT_S", 10)

        async def _await_connect(label):
            start_ms = time.ticks_ms()
            while not self.wifi.is_connected():
                self._feed_watchdog()
                if time.ticks_diff(time.ticks_ms(), start_ms) >= int(timeout_s * 1000):
                    self.logger.warning(
                        f"[WIFI] init: {label} not connected after {timeout_s}s"
                    )
                    return False
                self.logger.debug("Waiting for WiFi connection...")
                await asyncio.sleep(0.5)
            return True

        saved_ssid, saved_pass = self.wifi.load_saved_credentials()
        ota_ssid = getattr(config, "OTA_WIFI_SSID", None)
        ota_pass = getattr(config, "OTA_WIFI_PASSWORD", None)
        connected = False
        connected_via = None
        if saved_ssid:
            self.logger.info(f"[WIFI] init: attempting saved ssid='{saved_ssid}'")
            self.wifi.connect(ssid=saved_ssid, password=saved_pass, timeout_s=timeout_s, force=True)
            connected = await _await_connect("saved")
            if not connected:
                self.wifi.cancel_connect("saved timeout")
                try:
                    self.wifi.disconnect()
                except Exception as e:
                    self.logger.debug(f"[WIFI] init: saved disconnect failed: {e}")
                await asyncio.sleep(0.2)
                if ota_ssid:
                    self.logger.info(f"[WIFI] init: attempting OTA ssid='{ota_ssid}'")
                    self.wifi.connect(
                        ssid=ota_ssid,
                        password=ota_pass,
                        timeout_s=timeout_s,
                        force=True,
                    )
                    connected = await _await_connect("OTA")
                    if connected:
                        self.wifi.mark_connected("init")
                        connected_via = "ota"
                else:
                    self.logger.warning("[WIFI] init: OTA_WIFI_SSID not set; skipping OTA attempt")
            else:
                self.wifi.mark_connected("init")
                connected_via = "saved"
        else:
            self.logger.info("[WIFI] init: no saved SSID")
            if ota_ssid:
                self.logger.info(f"[WIFI] init: attempting OTA ssid='{ota_ssid}'")
                self.wifi.connect(ssid=ota_ssid, password=ota_pass, timeout_s=timeout_s, force=True)
                connected = await _await_connect("OTA")
                if connected:
                    self.wifi.mark_connected("init")
                    connected_via = "ota"
            else:
                self.logger.warning("[WIFI] init: OTA_WIFI_SSID not set; skipping OTA attempt")

        if not connected:
            self.logger.warning(
                f"[WIFI] init: not connected after {timeout_s}s; continuing offline"
            )
            self.wifi.cancel_connect("init timeout")
        elif connected_via == "ota":
            try:
                if ota_ssid:
                    self.wifi.clear_saved_credentials()
                    self.wifi.save_credentials(ota_ssid, ota_pass)
                    self.wifi.reset_saved_failure()
                    self.logger.info("[WIFI] init: OTA creds stored as saved WiFi")
                else:
                    self.logger.warning("[WIFI] init: connected via OTA but OTA_WIFI_SSID is empty")
            except Exception as e:
                self.logger.warning(f"[WIFI] init: failed to update saved creds: {e}")

        loading_panel.set_status("Initializing input...", 35)
        self.logger.info(f"[WIFI] init: {self.wifi.get_status_snapshot()}")
        if self.wifi.is_connected():
            self.logger.info("WiFi connected")

        loading_panel.set_status("Connecting to API...", 40)
        self.logger.info("=== Phase 2: Network Services ===")

        # Initialize API client
        if self.wifi.is_connected() and self.api_client is None:
            self._feed_watchdog(force=True)
            await self._setup_api_client()
            self._feed_watchdog(force=True)

        # Share app-owned WiFi manager with panels via GameUI
        self.game_ui.set_wifi_manager(self.wifi)
        # Share API client via GameUI for panel injection
        self.game_ui.set_api_client(self.api_client)

        loading_panel.set_status("Setting up Bluetooth...", 50)
        self.logger.info("=== Phase 3: Optional Services ===")

        # Initialize Bluetooth and battle system (reuse player_config from earlier)
        self._feed_watchdog(force=True)
        await self._setup_bluetooth(player_config=player_config)
        self._feed_watchdog(force=True)

        self.logger.info("=== Phase 4: Game Systems ===")
        loading_panel.set_status("Initializing battle system...", 60)

        # Share battle manager with GameUI for panel transitions and updates
        self.game_ui.set_battle_manager(self.battle_mgr)
        
        loading_panel.set_status("Preloading UI...", 70)
        # Preload commonly used panels for faster access
        self.game_ui.preload_panels(
            progress_callback=lambda *_args, **_kwargs: self._feed_watchdog()
        )
        # Seed chat panel with BT manager if it was preloaded
        if self.game_ui and "chat" in self.game_ui.panel_instances and self.bt_mgr:
            try:
                setattr(self.game_ui.panel_instances["chat"], "bt", self.bt_mgr)
            except Exception:
                self.logger.error("Failed to set BT manager on chat panel")
                pass

        loading_panel.set_status("Checking registration...", 90)
        # Cleanup initialization resources
        self.init_sprite = None
        scr = lv.screen_active()
        if scr:
            scr.set_style_bg_color(lv.color_black(), 0)
        gc.collect()
        self._power_save_wifi_if_idle("post-init")

        self.logger.info("=== Initialization Complete ===")
        np.fade_out((255,0,0), duration_ms=3000)
        #np.running = False

    async def run(self):
        """
        Main application run loop.

        Normal mode: Full UI with registration, battle, etc.
        Headless mode: Simple loop running auto-battle only.

        Returns:
            None
        """
        # Initialize all subsystems
        await self.initialize()

        # Headless auto-battle mode - simple loop
        if self.headless:
            await self._run_headless()
            return

        # Normal badge mode - full UI
        await self._run_normal()

    def cleanup(self):
        """
        Graceful shutdown and resource cleanup.

        Returns:
            None
        """
        self.logger.info("Shutting down badge application...")

        # Cancel async tasks
        self.cancel_all_tasks()

        # Cleanup subsystems
        if self.battle_mgr:
            try:
                self.battle_mgr.end_battle()
            except Exception as e:
                self.logger.debug(f"Battle manager cleanup failed: {e}")

        if self.bt_mgr:
            try:
                self.bt_mgr.disconnect()
            except Exception as e:
                self.logger.debug(f"Bluetooth cleanup failed: {e}")

        if self.wifi:
            try:
                self.wifi.disconnect()
            except Exception as e:
                self.logger.debug(f"WiFi cleanup failed: {e}")

        # Final garbage collection
        gc.collect()

        self.logger.info("Shutdown complete")
