from cactuscon.utils import Logger
from thirdparty.max1704x import max1704x
from cactuscon import config

fuel_gauge = max1704x(0, config.PIN_I2C_SDA, config.PIN_I2C_SCL)

if not fuel_gauge.sensor_exists():
    logger = Logger(config.LOG_LEVEL)
    logger.error("Power meter (MAX1704x) not found, some battery operations will fail.")
