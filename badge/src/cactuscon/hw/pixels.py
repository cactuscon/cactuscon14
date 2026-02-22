import asyncio
import time
from machine import Pin
from neopixel import NeoPixel

class NeoPixelController:
    def __init__(self, pin=18, num_leds=8):
        self.np = NeoPixel(Pin(pin), num_leds)
        self.running = False
        self._blink_task = None
        self._mode = "off"
        self._mode_params = {}
        self._last_color = (0, 0, 0)
        self._alert_running = False
    
    def fade_in(self, color=(255, 0, 0), duration_ms=1000):
        steps = 20
        # Fade in
        for i in range(steps):
            brightness = int((i / steps) * 255)
            adjusted = tuple(int(c * brightness / 255) for c in color)
            self.fill(adjusted)
            time.sleep_ms(int(duration_ms / (steps * 2)))

    def fade_out(self, color=(255, 0, 0), duration_ms=1000):
        steps = 20
        # Fade out
        for i in range(steps, 0, -1):
            brightness = int((i / steps) * 255)
            adjusted = tuple(int(c * brightness / 255) for c in color)
            self.fill(adjusted)
            time.sleep_ms(int(duration_ms / (steps * 2)))
        self.fill((0, 0, 0))

    async def _blink_loop(self, color, blinks_ms=500, pause_ms=500, times=3):
        """Internal async loop. If times==0 loop forever until `self.running` is False."""
        while self.running:
            for _ in range(times):
                if not self.running:
                    break
                self.fill(color)
                self.np.write()
                await asyncio.sleep(pause_ms / 1000)
                self.fill((0, 0, 0))
                self.np.write()
                await asyncio.sleep(pause_ms / 1000)

            await asyncio.sleep(blinks_ms / 1000)

    async def _rainbow_loop(self, pause_ms=80):
        """Cycle rainbow colors until stopped."""
        pos = 0
        while self.running:
            color = self._wheel(pos & 255)
            self.fill(color)
            self.np.write()
            pos = (pos + 3) % 256
            await asyncio.sleep(pause_ms / 1000)

    def _wheel(self, pos):
        """Generate rainbow colors across 0-255."""
        if pos < 85:
            return (255 - pos * 3, pos * 3, 0)
        if pos < 170:
            pos -= 85
            return (0, 255 - pos * 3, pos * 3)
        pos -= 170
        return (pos * 3, 0, 255 - pos * 3)

    def start_blink(self, color=(255, 0, 0), blinks_ms=2000, pause_ms=200, times=5):
        """Start a non-blocking blink sequence. If `times==0` blink repeats until `stop_blink()` is called.

        This schedules an internal uasyncio task; callers do not need to manage asyncio directly.
        """
        if self._blink_task is not None:
            return  # already running

        self.running = True
        self._mode = "blink"
        self._mode_params = {
            "color": color,
            "blinks_ms": blinks_ms,
            "pause_ms": pause_ms,
            "times": times,
        }
        self._last_color = color
        try:
            self._blink_task = asyncio.create_task(
                self._blink_loop(color=color, blinks_ms=blinks_ms, pause_ms=pause_ms, times=times)
            )
        except Exception:
            # unable to schedule; mark not running
            self.running = False
            self._blink_task = None

    def start_rainbow(self, pause_ms=50):
        """Start continuous rainbow cycle."""
        if self._blink_task is not None:
            try:
                self._blink_task.cancel()
            except Exception:
                pass
            self._blink_task = None
        self.running = True
        self._mode = "rainbow"
        self._mode_params = {"pause_ms": pause_ms}
        try:
            self._blink_task = asyncio.create_task(self._rainbow_loop(pause_ms=pause_ms))
        except Exception:
            self.running = False
            self._blink_task = None

    def stop_blink(self):
        """Stop any running blink task and turn LEDs off."""
        self.running = False
        if self._blink_task is not None:
            try:
                self._blink_task.cancel()
            except Exception:
                pass
            self._blink_task = None
        try:
            self.off()
        except Exception:
            pass
    
    def fill(self, color):
        #r,g,b = color
        #color = (g, r, b)
        """Fill all LEDs with a color"""
        for i in range(len(self.np)):
            self.np[i] = color
        self.np.write()
        self._last_color = color
        if not self.running:
            self._mode = "solid" if color != (0, 0, 0) else "off"
            self._mode_params = {"color": color}
    
    def off(self):
        """Turn off all LEDs"""
        self.fill((0, 0, 0))
        self.running = False
        self._mode = "off"
        self._mode_params = {}

    def _snapshot_mode(self):
        return {
            "mode": self._mode,
            "params": dict(self._mode_params or {}),
            "running": bool(self.running),
            "has_task": self._blink_task is not None,
            "last_color": self._last_color,
        }

    def _restore_mode(self, snapshot):
        mode = (snapshot or {}).get("mode", "off")
        params = (snapshot or {}).get("params", {}) or {}
        if mode == "rainbow":
            self.start_rainbow(pause_ms=params.get("pause_ms", 50))
            return
        if mode == "blink":
            self.start_blink(
                color=params.get("color", (255, 0, 0)),
                blinks_ms=params.get("blinks_ms", 2000),
                pause_ms=params.get("pause_ms", 200),
                times=params.get("times", 5),
            )
            return
        if mode == "solid":
            self.fill(params.get("color", snapshot.get("last_color", (0, 0, 0))))
            return
        self.off()

    async def flash_chat_alert(self, repeats=3, interval_ms=200):
        """
        Temporarily flash blue/green alert and restore prior LED mode.
        """
        if self._alert_running:
            return
        self._alert_running = True
        snapshot = self._snapshot_mode()
        try:
            if self._blink_task is not None:
                try:
                    self._blink_task.cancel()
                except Exception:
                    pass
                self._blink_task = None
                self.running = False
            for _ in range(repeats):
                self.fill((0, 0, 255))
                await asyncio.sleep(interval_ms / 1000)
                self.fill((0, 255, 0))
                await asyncio.sleep(interval_ms / 1000)
        finally:
            try:
                self._restore_mode(snapshot)
            except Exception:
                pass
            self._alert_running = False
