"""
Badge application configuration.

Centralized configuration for all badge subsystems. Supports runtime
overrides from NVS for deployment-specific settings.

Game entities (moves, characters, stations) are defined in the game engine:
    - cactuscon.game.engine.moves
    - cactuscon.game.engine.characters
    - cactuscon.game.engine.stations

Also importable via: `from cactuscon import config`
As it's used in both bootstrap (boot.py) and application (cactuscon modules).
"""


class BadgeConfig:
    """
    Centralized badge configuration.
    
    All configuration values in one place for easy management.
    Can be overridden at runtime from NVS preferences.
    
    Game entity access (moves, characters, stations) is via the game engine:
        from cactuscon.game import get_move, get_character, get_station
    
    Usage:
        # Bootstrap phase (boot.py):
        from config import BadgeConfig, config
        
        # Application phase (cactuscon modules):
        from cactuscon import config
        
        # Access configuration
        url = config.CACTIOT_URL
        
        # Load overrides from NVS
        config.load_from_nvs(prefs)
    """
    
    # ==================== OTA Configuration ====================
    OTA_WIFI_SSID = "CactusCon"      # OTA WiFi network (can override from NVS)
    OTA_WIFI_PASSWORD = "Cactus2026!"  # OTA WiFi password (can override from NVS)
    OTA_WIFI_TIMEOUT_S = 15          # WiFi connection timeout
    OTA_WIFI_MAX_ATTEMPTS = 3        # Max attempts before fallback
    OTA_WIFI_SCAN_BEFORE_CONNECT = True  # Pre-scan for SSID before connect
    OTA_SAVED_FAIL_LIMIT = 3         # Consecutive saved-cred failures before skipping saved
    OTA_FORCED_UPDATE = False        # Force OTA update even if same version
    OTA_DEV_BASE_URL = "http://local-badge.cactuscon.com:8000/ota"
    OTA_PROD_BASE_URL = "http://badge-ota.cactuscon.com/"
    OTA_MANIFEST_FILE = "versions.json"
    OTA_DEV_RECURSE_HTTP_FS = False   # Development: serve from local HTTP filesystem
    OTA_HTTP_TIMEOUT_S = 5           # HTTP timeout for manifest/file downloads
    OTA_DOWNLOAD_RETRIES = 2         # Retries after initial download attempt
    OTA_RETRY_BASE_DELAY_MS = 500    # Exponential backoff base between retries
    OTA_RESUME_DOWNLOADS = False     # Attempt HTTP range resume for partial files
    OTA_IO_CHUNK_SIZE = 1024          # Chunk size for file copy/download
    OTA_MD5_CHUNK_SIZE = 1024         # Chunk size for checksum verification
    OTA_STRICT_HTTP_FS = True        # Fail OTA if any HTTP-FS file fails
    OTA_DELETE_POLICY = "never"      # never|manifest_extensions|custom_extensions|all
    OTA_DELETE_EXTENSIONS = None     # Used only when OTA_DELETE_POLICY=custom_extensions

    # ==================== API Configuration ====================
    CACTIOT_URL = "http://your-ip-here:8001"  # Development server
    CACTIOT_DEVICE_TYPE = "badge"
    CACTIOT_DEVICE_VERSION = "1.0.0"
    CACTIOT_VERIFY_SSL = False  # Disabled for development
    CACTIOT_TIMEOUT = 10
    CACTIOT_MAX_RETRIES = 3
    
    # ==================== Bluetooth Configuration ====================
    BT_MAX_DEVICES = 20
    BT_RSSI_THRESHOLD = -85  # Balance between range and reliability
    BT_DEVICE_NAME = "Badge"  # Default, overridden by handle if registered
    # Conference-branded UUID components for battle BLE services/chars.
    # Optional full UUID overrides take precedence when provided.
    BT_GAME_UUID_PREFIX = "CC14"          # 4 hex chars
    BT_GAME_UUID_SUFFIX = "CAC71B072026"  # 12 hex chars
    BT_GAME_SERVICE_UUID_TEMPLATE = None  # e.g. "CC140001-0000-0000-0000-CAC71B072026"
    BT_GAME_CHAR_UUID = None              # e.g. "CC140002-C0DE-4BAD-9E14-CAC71B072026"
    
    # ==================== Chat Configuration ====================
    CHAT_ADV_PREFIX = "CC14PEER"  # BLE advertising prefix for peer discovery
    
    # ==================== Battle Configuration ====================
    AUTO_BATTLE_MODE = False             # Enable automated testing mode (auto-accept challenges)
    AUTO_TEST_BATTLE = False              # Enable auto-test: go to battle, select first opponent, auto-attack
    AUTO_TEST_DELAY_MS = 2000            # Delay between auto-test actions
    BATTLE_CHALLENGE_TIMEOUT_MS = 10000  # 10 seconds  # LEGACY: currently unused
    BATTLE_HANDSHAKE_TIMEOUT_MS = 5000   # 5 seconds  # LEGACY: currently unused
    BATTLE_MOVE_TIMEOUT_MS = 30000       # 30 seconds
    BATTLE_INACTIVITY_TIMEOUT_MS = 40000 # 40 seconds inactivity watchdog (ready-to-ready)
    BATTLE_KEEPALIVE_INTERVAL_MS = 5000  # 5 seconds  # LEGACY: currently unused
    BATTLE_DURATION_CAP_MS = 300000      # 5 minutes hard cap per battle
    ACHIEVEMENTS_MAX_REASONABLE_TIMER_MS = 12 * 60 * 60 * 1000  # 12 hours sanity bound
    # Player character ID - explicitly set which character this badge uses
    # Leave empty or set to None for random first-stage assignment (excluding hackachu line)
    # Valid creatures: voltiny, cindersip, blipbat, cipherkit, hacktarchu (and evolutions)


    # ==================== Unlock Configuration ====================
    PLAYER_CHARACTER_ID = None
    ENABLE_UNLOCK_REDEEM_STORE = True  # Enable NVS unlock redeem tracking
    UNLOCK_RL_ENABLED = True          # Enable unlock submission rate limiting
    UNLOCK_RL_MIN_INTERVAL_S = 0.6    # Minimum seconds between submissions
    UNLOCK_RL_FAIL_THRESHOLD = 5      # Invalid attempts before lockout
    UNLOCK_RL_LOCKOUT_BASE_S = 10     # Base lockout duration in seconds
    UNLOCK_RL_LOCKOUT_MAX_S = 60      # Max lockout duration in seconds
    
    
    # ==================== Station/Gym Configuration ====================
    # Station ID - set this to identify which station this badge is configured as
    # None = regular badge, 'station_demo_1' = demo station, etc.
    STATION_ID = ''

    
    # ==================== Display Configuration ====================
    DISPLAY_WIDTH = 320
    DISPLAY_HEIGHT = 240
    DISPLAY_ROTATION = 90  # Display rotation in degrees
    TOUCH_POLL_INTERVAL_MS = 100  # LEGACY: currently unused
    TOUCH_PROBE_TIMEOUT_MS = 2000  # Touch controller probe timeout
    TOUCH_PROBE_SLEEP_MS = 100     # Sleep between touch probe attempts
    TFT_SPI_HOST = 1  # SPI host for TFT (1=SPI2/FSPI on most ESP32-S3 builds)
    TFT_SPI_FREQ = 40_000_000  # TFT SPI clock in Hz
    TFT_SPI_FREQ_FALLBACKS = [30_000_000, 20_000_000]  # Lower speeds to try on ENODEV
    TFT_SPI_HOST_FALLBACKS = [2]  # Optional fallback hosts to try if ENODEV
    TOUCH_I2C_FREQ = 100_000  # Touch controller I2C frequency
    # Minimum time to hold the early boot splash (hourglass) so humans can read the version.
    BOOT_VERSION_SPLASH_MS = 2000

    # ==================== Logging Configuration ====================
    LOG_LEVEL = 20  # 10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR, 50=FATAL (DEBUG for tracing panel load issues)
    DEVELOPMENT = True  # Enable development features
    
    # ==================== Memory Management ====================
    GC_THRESHOLD_KB = 50  # Run GC if free memory below this  # LEGACY: currently unused
    GC_INTERVAL_MS = 5000  # Run GC periodically  # LEGACY: currently unused
    MAX_SPRITE_CACHE_BYTES = 200 * 1024  # Max memory for sprite caching (200KB)

    # ==================== Runtime Safety ====================
    WATCHDOG_ENABLED = True
    WATCHDOG_FORCE_IN_DEV = False
    WATCHDOG_TIMEOUT_MS = 30000
    WATCHDOG_FEED_INTERVAL_MS = 500
    WATCHDOG_SLEEP_SLICE_MS = 100
    
    # ==================== WiFi Configuration ====================
    WIFI_CONNECT_TIMEOUT_S = 10
    WIFI_RETRY_COUNT = 3  # LEGACY: currently unused
    WIFI_RECONNECT_DELAY_S = 5  # LEGACY: currently unused
    
    # ==================== Hardware Pin Configuration ====================
    # SPI Display pins (ILI9341)
    PIN_TFT_SCK = 12   # SPI Clock
    PIN_TFT_MOSI = 11  # SPI MOSI (Master Out Slave In)
    PIN_TFT_CS = 10    # Chip Select
    PIN_TFT_DC = 5     # Data/Command
    PIN_TFT_RESET = 4  # Reset
    PIN_TFT_LED = 6    # Backlight control pin

    # I2C Device Pins
    PIN_I2C_SDA = 8
    PIN_I2C_SCL = 9
    TOUCH_I2C_USE_HARDWARE = True
    TOUCH_I2C_ID = 0  # I2C bus id for hardware I2C (platform-dependent)

    # Touch Interface
    PIN_TOUCH_INT = 7
    PIN_TOUCH_RST = 3

    # LEDs
    PINS_LED = [13, 14, 15, 16, 17, 46]  # LEGACY: currently unused
    PIN_STATUS_LED = 21  # LEGACY: currently unused
    PIN_NEOPIXEL = 18  # LEGACY: currently unused
    NUM_NEOPIXELS = 6  # LEGACY: currently unused

    # Buzzer
    PIN_BUZZER = 19  # LEGACY: currently unused

    # Rotary Encoder
    PIN_ENCODER_A = 45  # LEGACY: currently unused
    PIN_ENCODER_B = 48  # LEGACY: currently unused
    PIN_ENCODER_BUTTON = 20  # LEGACY: currently unused

    # Buttons
    PIN_BOOT_BUTTON = 0
    PIN_BUTTON_ENTER = 38  # LEGACY: currently unused
    PIN_BUTTON_BACK = 39  # LEGACY: currently unused

    # SD Card
    PIN_SD_MOSI = 35  # LEGACY: currently unused
    PIN_SD_SCK = 36  # LEGACY: currently unused
    PIN_SD_MISO = 37  # LEGACY: currently unused
    PIN_SD_CS = 47  # LEGACY: currently unused
    
    # ==================== Class Methods ====================
    
    @classmethod
    def get_ota_base_url(cls):
        """Get OTA base URL based on development mode."""
        return cls.OTA_DEV_BASE_URL if cls.DEVELOPMENT else cls.OTA_PROD_BASE_URL
    
    @classmethod
    def get_ota_manifest_url(cls):
        """Get OTA manifest URL based on development mode."""
        base_url = cls.get_ota_base_url()
        return f"{base_url}/{cls.OTA_MANIFEST_FILE}"
    
    @classmethod
    def load_from_nvs(cls, prefs):
        """
        Load configuration overrides from NVS preferences.
        
        Allows runtime configuration without firmware changes.
        
        Args:
            prefs: Preferences instance for NVS access
        """
        # Lazy import to avoid circular dependency with prefs -> config
        try:
            from cactuscon import prefs as prefs_module
            HANDLE_KEY = getattr(prefs_module, "HANDLE_KEY", "handle")
            LEGACY_HANDLE_KEY = getattr(prefs_module, "LEGACY_HANDLE_KEY", "handle")
        except Exception:
            HANDLE_KEY = LEGACY_HANDLE_KEY = "handle"

        # API configuration overrides
        url = prefs.get_string("config_api_url", None)
        if url:
            cls.CACTIOT_URL = url
        
        verify_ssl = prefs.get_bool("config_verify_ssl", None)
        if verify_ssl is not None:
            cls.CACTIOT_VERIFY_SSL = verify_ssl
        
        # OTA configuration overrides
        ota_ssid = prefs.get_string("config_ota_ssid", None)
        if ota_ssid:
            cls.OTA_WIFI_SSID = ota_ssid
        
        ota_password = prefs.get_string("config_ota_password", None)
        if ota_password:
            cls.OTA_WIFI_PASSWORD = ota_password
        
        # Bluetooth configuration
        bt_name = prefs.get_string(HANDLE_KEY, prefs.get_string(LEGACY_HANDLE_KEY, None))
        if bt_name:
            cls.BT_DEVICE_NAME = bt_name
        
        rssi = prefs.get_int32("config_bt_rssi", None)
        if rssi is not None:
            cls.BT_RSSI_THRESHOLD = rssi
        
        # Logging level
        log_level = prefs.get_int32("config_log_level", None)
        if log_level is not None:
            cls.LOG_LEVEL = log_level
        
        # Development mode
        dev_mode = prefs.get_bool("config_development", None)
        if dev_mode is not None:
            cls.DEVELOPMENT = dev_mode
    
    @classmethod
    def save_to_nvs(cls, prefs):
        """
        Save current configuration to NVS.
        
        Args:
            prefs: Preferences instance for NVS access
        """
        prefs.set_string("config_api_url", cls.CACTIOT_URL)
        prefs.set_bool("config_verify_ssl", cls.CACTIOT_VERIFY_SSL)
        prefs.set_int32("config_bt_rssi", cls.BT_RSSI_THRESHOLD)
        prefs.set_int32("config_log_level", cls.LOG_LEVEL)
        prefs.set_bool("config_development", cls.DEVELOPMENT)
    
    @classmethod
    def set_production_mode(cls):
        """Configure for production deployment."""
        cls.CACTIOT_URL = "https://cactiot.cactuscon.com"  # Update with actual production URL
        cls.CACTIOT_VERIFY_SSL = True
        cls.DEVELOPMENT = False
        cls.LOG_LEVEL = 30  # WARNING level for production
    
    @classmethod
    def set_development_mode(cls):
        """Configure for development."""
        cls.CACTIOT_URL = "http://your-ip-here:8001"
        cls.CACTIOT_VERIFY_SSL = False
        cls.DEVELOPMENT = True
        cls.LOG_LEVEL = 20  # INFO level for development
    
    @classmethod
    def get_summary(cls):
        """
        Get configuration summary for logging.
        
        Returns:
            str: Human-readable configuration summary
        """
        return f"""Badge Configuration:
  API: {cls.CACTIOT_URL} (SSL: {cls.CACTIOT_VERIFY_SSL})
  Device: {cls.CACTIOT_DEVICE_TYPE} v{cls.CACTIOT_DEVICE_VERSION}
  BT: RSSI >= {cls.BT_RSSI_THRESHOLD} dBm
  Mode: {'DEVELOPMENT' if cls.DEVELOPMENT else 'PRODUCTION'}
  Log Level: {cls.LOG_LEVEL}"""


# Global configuration instance
config = BadgeConfig()
