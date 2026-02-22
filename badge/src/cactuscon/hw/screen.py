"""TFT display and touch screen initialization for ESP32-S3 with ILI9341 and FT6336U."""

from cactuscon.utils import Logger
from cactuscon import config
logger = Logger(config.LOG_LEVEL)

import asyncio
import gc
from machine import Pin, SoftI2C, I2C, lightsleep as sleep
from time import ticks_ms, ticks_add, ticks_diff, sleep_ms

import lvgl as lv
import lcd_bus
import machine
import ili9341

from thirdparty.uFT6336U import FT6336U
from thirdparty.xglcd_font import XglcdFont

# concat the main executable path with the font file path
FONT_NAME = "ArcadePix9x11.c"
FONT_PATH = f"/assets/fonts/{FONT_NAME}"

# pins - use centralized configuration
# TFT display
PIN_TFT_RESET = config.PIN_TFT_RESET
PIN_TFT_DC = config.PIN_TFT_DC
PIN_TFT_LED = config.PIN_TFT_LED
PIN_TFT_CS = config.PIN_TFT_CS
PIN_TFT_MOSI = config.PIN_TFT_MOSI
PIN_TFT_SCK = config.PIN_TFT_SCK

# touch screen
PIN_I2C_SDA = config.PIN_I2C_SDA
PIN_I2C_SCL = config.PIN_I2C_SCL
PIN_TOUCH_INT = config.PIN_TOUCH_INT
PIN_TOUCH_RST = config.PIN_TOUCH_RST
TOUCH_INTERVAL = 100  # how often to check for touch events, in ms

class TFT:

    def __init__(self):
        # placeholder for visible non-keyboard UI
        self.ui = None
        # touch
        self.touched = False
        self.last_tick = -1
        self.last_touched = -1
        self.last_point_x = 0
        self.last_point_y = 0
        self.tx = -1
        self.ty = -1
        self.touch_rst = Pin(PIN_TOUCH_RST, Pin.OUT)
        self.touch_int = Pin(PIN_TOUCH_INT, Pin.IN)
        self.touch_sda = Pin(PIN_I2C_SDA, Pin.OUT)
        self.touch_scl = Pin(PIN_I2C_SCL, Pin.IN)
        self.bounce_pin(PIN_TOUCH_RST)
        touch_freq = getattr(config, "TOUCH_I2C_FREQ", 100_000)
        use_hw_i2c = getattr(config, "TOUCH_I2C_USE_HARDWARE", True)
        self.touch_i2c = None
        if use_hw_i2c:
            try:
                i2c_id = getattr(config, "TOUCH_I2C_ID", 0)
                self.touch_i2c = I2C(
                    i2c_id,
                    scl=Pin(PIN_I2C_SCL),
                    sda=Pin(PIN_I2C_SDA),
                    freq=touch_freq,
                )
            except OSError as e:
                logger.warning(f"[TOUCH] HW I2C init failed, falling back to SoftI2C: {e}")
                self.touch_i2c = None
        if self.touch_i2c is None:
            self.touch_i2c = SoftI2C(
                sda=self.touch_sda,
                scl=self.touch_scl,
                freq=touch_freq,
            )
        print(f"scan: {self.touch_i2c.scan()}")
        # Wait until we read the expected FT6336U ID before initializing touch.
        buf = bytearray(2)
        touch_probe_timeout_ms = getattr(config, "TOUCH_PROBE_TIMEOUT_MS", 6500)
        touch_probe_try_alt_ms = max(
            250, int(getattr(config, "TOUCH_PROBE_TRY_ALT_MS", 2000))
        )
        touch_probe_sleep_ms = getattr(config, "TOUCH_PROBE_SLEEP_MS", 100)
        touch_probe_start = ticks_ms()
        try:
            next_alt_probe_ms = touch_probe_try_alt_ms
            while True:
                try:
                    self.touch_i2c.readfrom_mem_into(0x38, 0xA0, buf)
                except Exception:
                    pass
                if buf == b"\x02\x05":
                    break

                elapsed_ms = ticks_diff(ticks_ms(), touch_probe_start)

                # Periodically try a direct controller init even if ID read is noisy.
                if elapsed_ms >= next_alt_probe_ms:
                    next_alt_probe_ms += touch_probe_try_alt_ms
                    logger.debug(f"[TOUCH] probe read failed, buf={bytes(buf)}, trying alternate check")
                    try:
                        self.touch = FT6336U(self.touch_i2c, rst=self.touch_rst)
                        logger.info(f"[TOUCH] alternate check succeeded")
                        break
                    except Exception as exc:
                        logger.info(f"[TOUCH] alternate check failed: {exc}")
                    
                if elapsed_ms >= touch_probe_timeout_ms:
                    logger.warning(f"[TOUCH] probe timeout, last buf={bytes(buf)}")
                    break
                
                sleep_ms(touch_probe_sleep_ms)
        except KeyboardInterrupt:
            logger.warning("CTRL^C caught.")

        self.touch = FT6336U(self.touch_i2c, rst=self.touch_rst)
        logger.debug(f"gc.mem_free(): {gc.mem_free()}")

        # font
        self.font = XglcdFont(FONT_PATH, 9, 11)
        logger.debug(f"gc.mem_free(): {gc.mem_free()}")

        # display - creating this after lv.init() should register it with LVGL
        self.bounce_pin(PIN_TFT_RESET)
        
        # SPI Bus setup using machine.SPI.Bus (specific to this firmware)
        # Host 1 corresponds to SPI2 (FSPI) or SPI3 (HSPI) depending on mapping
        # Using 1 as per example
        spi_host = getattr(config, "TFT_SPI_HOST", 1)
        spi_freq = getattr(config, "TFT_SPI_FREQ", 40_000_000)
        spi_fallbacks = list(getattr(config, "TFT_SPI_HOST_FALLBACKS", []))
        spi_hosts = [spi_host] + [h for h in spi_fallbacks if h != spi_host]
        self.spi_bus = None
        last_err = None
        for host in spi_hosts:
            try:
                self.spi_bus = machine.SPI.Bus(
                    host=host,
                    mosi=PIN_TFT_MOSI,
                    sck=PIN_TFT_SCK
                )
                if host != spi_host:
                    logger.warning(f"[TFT] SPI host fallback: using host={host}")
                break
            except Exception as e:
                last_err = e
                logger.warning(f"[TFT] SPI bus init failed (host={host}): {e}")
                self.spi_bus = None
        if self.spi_bus is None:
            raise last_err if last_err else OSError("SPI bus init failed")
        
        freq_fallbacks = list(getattr(config, "TFT_SPI_FREQ_FALLBACKS", []))
        freq_list = [spi_freq] + [f for f in freq_fallbacks if f != spi_freq]
        self.display_bus = None
        self.display = None
        last_err = None
        backoff_ms = 100
        backoff_tries = 3
        for freq in freq_list:
            try:
                if freq != spi_freq:
                    logger.warning(f"[TFT] Retrying SPI init at {freq} Hz")
                self.display_bus = lcd_bus.SPIBus(
                    spi_bus=self.spi_bus,
                    freq=freq,
                    dc=PIN_TFT_DC,
                    cs=PIN_TFT_CS
                )
                self.display = ili9341.ILI9341(
                    data_bus=self.display_bus,
                    display_width=config.DISPLAY_HEIGHT,
                    display_height=config.DISPLAY_WIDTH,
                    backlight_pin=PIN_TFT_LED,
                    color_space=lv.COLOR_FORMAT.RGB565,
                    color_byte_order=ili9341.BYTE_ORDER_BGR,
                    rgb565_byte_swap=True,
                    backlight_on_state=ili9341.STATE_PWM
                )
                if freq != spi_freq:
                    logger.warning(f"[TFT] SPI freq fallback: using {freq} Hz")
                break
            except OSError as e:
                last_err = e
                if getattr(e, "errno", None) == 19 or "ENODEV" in str(e):
                    if freq == spi_freq and backoff_tries > 0:
                        logger.warning(
                            f"[TFT] ENODEV at {freq} Hz; backing off {backoff_ms}ms before retry"
                        )
                        try:
                            sleep_ms(backoff_ms)
                        except Exception:
                            sleep(backoff_ms)
                        backoff_ms *= 2
                        backoff_tries -= 1
                        continue
                    logger.warning(f"[TFT] ENODEV at {freq} Hz; trying lower freq")
                    self.display_bus = None
                    self.display = None
                    continue
                raise
        if self.display is None:
            raise last_err if last_err else OSError("TFT display init failed")
        
        self.display.set_power(True)
        self.display.init(1)
        sleep_ms(300)  # Wait for display init to complete
        # Enable color inversion at display level (LVGL 9.4 MicroPython binding requirement)
        # This allows using real color functions instead of inverting all color names
        self.display.set_color_inversion(True)
        self.display.set_rotation(lv.DISPLAY_ROTATION._90)  # 90 deg rotation: native 320x240 → effective 240x320 (portrait)
        self.display.set_backlight(100)
        
        logger.debug(f"gc.mem_free(): {gc.mem_free()}")
        
        logger.info("Display created")

        self.touch_int.irq(trigger=Pin.IRQ_RISING, handler=self.handle_interrupt)
        logger.debug(f"gc.mem_free(): {gc.mem_free()}")

        # Now complete LVGL setup (verify display, setup input device)
        self._init_lvgl()
        
        print("init() complete.")

    def bounce_pin(self, pin):
        # ft6336u didn't show up on the I2C bus until I bounced RST
        Pin(pin, Pin.OUT).value(Pin.PULL_DOWN)
        sleep(10)
        Pin(pin, Pin.OUT).value(Pin.PULL_UP)
        sleep(500)

    def _init_lvgl(self):
        """
        Complete LVGL setup after display driver is initialized (LVGL 9.4).
        
        LVGL 9.4 MicroPython Binding Specifics:
        - Display Rotation: Set to 270° (rotation=3) in display.init()
          * Native display: 320px wide × 240px tall (landscape)
          * After 270° rotation: 240px wide × 320px tall (portrait) - this is the effective coordinate system
          * All LVGL positioning must use rotated dimensions (240×320)
        
        - Color Inversion: LVGL 9.4 binding uses inverted colors by default
          * Solution: Call display.set_color_inversion(True) in display driver setup
          * This allows using real color functions: lv.color_black(), lv.color_white(), lv.color_yellow()
          * Without this setting, all colors render inverted (black→white, white→black)
        
        - Point Types: Use lv.point_precise_t({'x': x, 'y': y}) for line/shape coordinates
          * lv.point_t is NOT available in LVGL 9.4 MicroPython binding
          * point_precise_t provides exact positioning
        
        - Font Handling: lv.font_default() does NOT exist in LVGL 9.4
          * LVGL automatically uses default fonts when not explicitly set
          * No need to configure default fonts
        
        Note: lv.init() must be called BEFORE creating the Display object.
        This method is called AFTER Display() initialization to:
        1. Verify display is registered with LVGL
        2. Configure LVGL theme and colors for RGB565
        3. Create input device for touch
        4. Test that LVGL objects can be created
        """
        try:
            # Step 1: Get default display (should be registered by ili9341 driver)
            logger.debug("Getting LVGL default display...")
            self.lv_display = lv.display_get_default()
            print(f"Default display: {self.lv_display}")
            
            # Step 2: Configure LVGL theme colors for RGB565 (LVGL 9.4)
            logger.debug("Configuring LVGL theme...")
            try:
                # Create a simple theme or use built-in
                scr = lv.screen_active()
                # Set default background to black
                scr.set_style_bg_color(lv.color_hex(0x000000), 0)
                logger.info("Theme configured")
            except Exception as theme_err:
                logger.warning(f"Theme configuration warning: {theme_err}")
            
            # Step 3: Test creating a simple object
            logger.debug("Testing LVGL object creation...")
            test_obj = lv.obj()
            test_obj.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)  # Test white color
            print(f"Test object created: {test_obj}")
            test_obj.delete()
            logger.info("Test object deleted")
            
            # Step 4: Create input device for touch
            logger.debug("Creating input device...")
            try:
                self.lv_indev = lv.indev_create()
                # Try to set type if available in this binding
                if hasattr(lv, 'INDEV_TYPE_POINTER'):
                    self.lv_indev.set_type(lv.INDEV_TYPE_POINTER)
                elif hasattr(lv, 'INDEV_TYPE') and hasattr(lv.INDEV_TYPE, 'POINTER'):
                    self.lv_indev.set_type(lv.INDEV_TYPE.POINTER)
                # Set read callback if supported
                if hasattr(self.lv_indev, 'set_read_cb'):
                    self.lv_indev.set_read_cb(self._lvgl_touch_read)
                print(f"Input device created: {self.lv_indev}")
            except AttributeError as indev_err:
                logger.warning(f"Input device configuration warning: {indev_err}")
                print("  Input device created but type/callback not configured")
                # Input device still created, just may not have callbacks
            
            logger.info("LVGL 9.4 initialization complete")
            print(f"  Display: {self.lv_display}")
            print(f"  Input device: {self.lv_indev}")
        
        except Exception as e:
            print(f"LVGL initialization failed: {e}")
            logger.error(f"Error type: {type(e)}")
            # Note: traceback not available in MicroPython
            # Set to None so we know LVGL isn't available
            self.lv_display = None
            self.lv_indev = None
    
    def _lvgl_flush_cb(self, disp_drv, area, color_p):
        """
        LVGL flush callback - called when LVGL needs to update screen.
        
        Note: This callback may not be supported in MicroPython's minimal LVGL binding.
        The binding may handle display output automatically.
        
        Args:
            disp_drv: LVGL display driver
            area: Area to update (left, top, right, bottom)
            color_p: Pointer to framebuffer with RGB565 data
        """
        # MicroPython LVGL binding may not call this callback
        # Display updates may be handled automatically
        pass
    
    @staticmethod
    def create_line(parent, points_list, color, width=2):
        """
        Create an LVGL 9.4 line widget with precise points.
        
        LVGL 9.4 MicroPython note: There is no canvas.draw_line() in this binding.
        Instead, use individual lv.line() widgets with lv.point_precise_t coordinates.
        
        Args:
            parent: Parent LVGL object
            points_list: List of tuples (x, y) for line endpoints
            color: LVGL color (e.g., lv.color_black(), lv.color_hex(0xRRGGBB))
            width: Line width in pixels (default: 2)
        
        Returns:
            LVGL line object (lv.line)
        
        Example:
            line = TFT.create_line(
                parent,
                [(20, 20), (100, 100)],
                lv.color_yellow(),
                width=3
            )
        """
        try:
            # Convert tuples to lv.point_precise_t objects
            lv_points = [
                lv.point_precise_t({'x': x, 'y': y})
                for x, y in points_list
            ]
            
            # Create line widget
            line = lv.line(parent)
            line.set_points(lv_points, len(lv_points))
            line.set_style_line_color(color, 0)
            line.set_style_line_width(width, 0)
            
            return line
        except Exception as e:
            logger.error(f"Error creating line: {e}")
            return None
    
    def _lvgl_touch_read(self, indev_drv, data):
        """
        LVGL touch input callback - called when LVGL needs touch input.
        
        This matches the C++ badge_touchpad_read() function signature.
        
        Args:
            indev_drv: LVGL input device driver
            data: Input data structure to fill (has .state and .point.x/y)
        """
        try:
            now = ticks_ms()
            num_points = self.touch.get_points()
            # Consider a touch stale if we haven't seen an interrupt for >200ms
            stale = (self.last_touched > 0) and (ticks_diff(now, self.last_touched) > 200)

            if num_points > 0 and not stale:
                # Touch detected - set pressed state
                data.state = lv.INDEV_STATE_PRESSED if hasattr(lv, 'INDEV_STATE_PRESSED') else 1
                
                # Get touch coordinates (rotated 180 degrees to match C++ code)
                self.tx = self.touch.get_p1_x()
                self.ty = self.touch.get_p1_y()
                data.point.x = 240 - self.tx
                data.point.y = 320 - self.ty
                self.last_point_x = data.point.x
                self.last_point_y = data.point.y
                self.last_touched = now
            else:
                # No touch - set released state
                data.state = lv.INDEV_STATE_RELEASED if hasattr(lv, 'INDEV_STATE_RELEASED') else 0
                # Clear stored coords to avoid ghost taps
                self.tx = -1
                self.ty = -1
                data.point.x = self.last_point_x
                data.point.y = self.last_point_y
        except Exception as e:
            logger.error(f"Error in touch callback: {e}")
            data.state = 0  # Released on error
            self.tx = -1
            self.ty = -1

    # setup touch handler
    def handle_interrupt(self, pin):
        self.last_touched = ticks_ms()

    def is_touched(self):
        # return true if touched since the last touch interval
        num_points = self.touch.get_points()
        if num_points > 0:
            self.tx, self.ty = self.touch.get_p1_x(), self.touch.get_p1_y()
            return True

        # reset touch coords
        self.tx = -1
        self.ty = -1
        return False

    async def loop(self, overlay_ui=None):
        """
        Main screen loop - handles touch input and UI updates.
        
        Args:
            overlay_ui: Optional UI overlay to update
        """
        # Handle LVGL timer (must be called periodically)
        # C++ example uses lv_timer_handler(), not lv_task_handler()
        try:
            if hasattr(lv, 'timer_handler'):
                lv.timer_handler()
            elif hasattr(lv, 'task_handler'):
                lv.task_handler()
        except Exception as e:
            logger.error(f"Error in LVGL handler: {e}")
        
        now = ticks_ms()
        # only check for touches every TOUCH_INTERVAL
        if now >= ticks_add(self.last_tick, TOUCH_INTERVAL):
            self.last_tick = now
            if self.is_touched():
                # reset last_tick so we get another full TOUCH interval after keypress
                self.last_tick = ticks_ms()
            else:
                if overlay_ui:
                    overlay_ui.loop()
        else:
            # nap?
            pass

    async def loop_forever(self, overlay_ui=None):
        """
        Run screen loop forever.
        
        Args:
            overlay_ui: Optional UI overlay to update
        """
        while True:
            await self.loop(overlay_ui)
            # sleep for a short time to avoid busy-waiting
            await asyncio.sleep(0.05)
