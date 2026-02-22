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

# Initialize logger
config = BadgeConfig()
logger = Logger(config.LOG_LEVEL)

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
    main()
