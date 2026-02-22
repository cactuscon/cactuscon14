# micropython
"""
CactusCon14 Badge - Main Entry Point

Minimal main.py that instantiates and runs the BadgeApplication.
All application logic is contained in BadgeApplication class for
better organization, testing, and maintenance.

Hardware: ESP32-S3 with display, touch, WiFi, BLE
"""

from cactuscon.utils import mem_info, Logger

import asyncio
from cactuscon.application import BadgeApplication
from config import BadgeConfig
from saguarota.saguarota import OTAUpdater

# Initialize logger
config = BadgeConfig()
logger = Logger(config.LOG_LEVEL)


def _finalize_pending_ota():
    """
    Confirm pending OTA only after main imports/startup are healthy.

    This preserves rollback ability when freshly updated code crashes before
    the app reaches main().
    """
    try:
        updater = OTAUpdater(
            config.get_ota_manifest_url(),
            config.get_ota_base_url(),
            force_update=bool(getattr(config, "OTA_FORCED_UPDATE", False)),
            recurse_http_fs=bool(getattr(config, "OTA_DEV_RECURSE_HTTP_FS", False)),
            http_timeout_s=int(getattr(config, "OTA_HTTP_TIMEOUT_S", 5)),
            download_retries=int(getattr(config, "OTA_DOWNLOAD_RETRIES", 1)),
            retry_base_delay_ms=int(getattr(config, "OTA_RETRY_BASE_DELAY_MS", 250)),
            resume_downloads=bool(getattr(config, "OTA_RESUME_DOWNLOADS", False)),
            io_chunk_size=int(getattr(config, "OTA_IO_CHUNK_SIZE", 512)),
            md5_chunk_size=int(getattr(config, "OTA_MD5_CHUNK_SIZE", 512)),
            strict_http_fs=bool(getattr(config, "OTA_STRICT_HTTP_FS", True)),
            delete_files_not_in_manifest_policy=str(
                getattr(config, "OTA_DELETE_POLICY", "never")
            ),
            delete_files_not_in_manifest_extensions=getattr(
                config, "OTA_DELETE_EXTENSIONS", None
            ),
        )
        try:
            if updater.confirm_update(cleanup=True):
                logger.info("OTA update confirmed; backup cleaned")
        finally:
            try:
                updater.release()
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"OTA finalization skipped: {e}")


def main():
    """
    Badge application entry point.
    
    Creates and runs the badge application with default configuration.
    For custom configuration, pass config_overrides to BadgeApplication.
    """
    app = BadgeApplication()
    
    try:
        asyncio.run(app.run())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        app.cleanup()


# Start the badge application
if __name__ == "__main__":
    _finalize_pending_ota()
    main()
