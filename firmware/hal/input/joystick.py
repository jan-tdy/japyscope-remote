"""Real hardware input backend: an external KY-023-style dual-axis analog
joystick module (VRx/VRy + SW push button). See docs/WIRING.md — it's an
external module on its own cable, not enclosure-mounted, and genuinely
optional (see shared.db's joystick_enabled): firmware/main.py only builds
this backend at all when the accessory is actually connected, unlike the
keypad/encoder which are always present.

The Pi Zero W has no native analog input, so VRx/VRy are read through an
ADS1115 I2C ADC instead of straight GPIO (SW is a plain digital GPIO input,
same idea as the encoder's push button in encoder.py).

The joystick's Y-axis and push button reuse ENC_UP/ENC_DOWN/ENC_PUSH
directly — see keys.py — making it a drop-in alternative to the KY-040
rotary encoder for menu navigation. Only the X-axis is unique to it
(JOY_LEFT/JOY_RIGHT), used for manual N/S/E/W jogging (see
firmware/ui/controller.py's ALIGN_JOG/TRACK handling).

Pin numbers, the I2C address, and axis polarity below are placeholders —
cross-check/update against docs/WIRING.md, the single source of truth, once
wiring is finalized. As with encoder.py's quadrature decoding, converting
continuous X/Y readings into discrete direction events (with a dead zone
and hold-to-repeat, since jogging means holding the stick over rather than
a single detent click) is a standard technique implemented for real here,
even though it hasn't been exercised against physical hardware yet.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from .base import InputHAL
from .keys import ENC_DOWN, ENC_PUSH, ENC_UP, JOY_LEFT, JOY_RIGHT

JOY_SW_PIN = 27
JOY_I2C_BUS = 1
JOY_I2C_ADDRESS = 0x48  # ADS1115 default (ADDR pin tied to GND)
JOY_X_CHANNEL = 0  # ADS1115 single-ended input wired to VRx (left/right)
JOY_Y_CHANNEL = 1  # ADS1115 single-ended input wired to VRy (up/down)

_SCAN_INTERVAL_S = 0.02
_DEBOUNCE_S = 0.05
# How often a direction re-fires while the stick is held over, for smooth
# jogging rather than one nudge per press — tune once real hardware exists.
_REPEAT_INTERVAL_S = 0.15
_CENTER = 32768  # mid-scale of the ADS1115's 16-bit conversion register
_DEAD_ZONE = 6000  # +/- around center treated as "centered" (rest-position noise margin)

# ADS1115 config register bit fields (see datasheet Table 8) — cross-check
# against the real chip before trusting these once hardware exists.
_ADS1115_CONFIG_REG = 0x01
_ADS1115_CONVERSION_REG = 0x00
_ADS1115_MUX_SINGLE_ENDED = {0: 0x4000, 1: 0x5000, 2: 0x6000, 3: 0x7000}
_ADS1115_OS_SINGLE_START = 0x8000
_ADS1115_PGA_4_096V = 0x0200
_ADS1115_MODE_SINGLE_SHOT = 0x0100
_ADS1115_DR_128SPS = 0x0080
_ADS1115_COMP_DISABLE = 0x0003


class _Ads1115:
    """Minimal single-ended reader for the ADS1115 I2C ADC — just enough to
    poll two channels for this module, no gain/rate configuration beyond
    v0's fixed needs. `bus` is any object exposing smbus2's
    write_i2c_block_data/read_i2c_block_data (injected so this is testable
    without real hardware)."""

    def __init__(self, bus, address: int = JOY_I2C_ADDRESS):
        self._bus = bus
        self._address = address

    def read_channel(self, channel: int) -> int:
        config = (
            _ADS1115_OS_SINGLE_START
            | _ADS1115_MUX_SINGLE_ENDED[channel]
            | _ADS1115_PGA_4_096V
            | _ADS1115_MODE_SINGLE_SHOT
            | _ADS1115_DR_128SPS
            | _ADS1115_COMP_DISABLE
        )
        self._bus.write_i2c_block_data(self._address, _ADS1115_CONFIG_REG, [config >> 8, config & 0xFF])
        time.sleep(0.001)  # give the single-shot conversion (~7.8ms at 128SPS) a head start
        high, low = self._bus.read_i2c_block_data(self._address, _ADS1115_CONVERSION_REG, 2)
        return (high << 8) | low


def _direction_from_axes(dx: int, dy: int) -> Optional[str]:
    """Reduce a continuous (dx, dy) deflection from center to a single
    cardinal direction code, or None while centered or pushed diagonally.
    Diagonal slewing is deliberately not supported — the mount only jogs
    N/S/E/W one at a time (see docs/CODES.md), so a push clearly off both
    axes at once is treated as no input rather than guessed at, rather than
    silently snapping to whichever axis is larger.

    Axis polarity (which physical direction increases the ADC reading)
    depends on how VRx/VRy end up wired — flip the comparisons below if
    up/down or left/right come out backwards once hardware exists, same as
    the encoder's CLK/DT swap note in encoder.py.
    """
    x_active = abs(dx) >= _DEAD_ZONE
    y_active = abs(dy) >= _DEAD_ZONE
    if x_active and y_active:
        return None
    if x_active:
        return JOY_RIGHT if dx > 0 else JOY_LEFT
    if y_active:
        return ENC_DOWN if dy > 0 else ENC_UP
    return None


class JoystickInput(InputHAL):
    def __init__(self):
        import RPi.GPIO as GPIO  # noqa: N814
        import smbus2  # noqa: PLC0415

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(JOY_SW_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._bus = smbus2.SMBus(JOY_I2C_BUS)
        self._adc = _Ads1115(self._bus)

        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._last_key_time: dict[str, float] = {}
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _emit(self, key: str, min_gap: float) -> None:
        now = time.monotonic()
        if now - self._last_key_time.get(key, 0.0) < min_gap:
            return
        self._last_key_time[key] = now
        self._queue.put(key)

    def _scan_axes(self) -> None:
        x = self._adc.read_channel(JOY_X_CHANNEL)
        y = self._adc.read_channel(JOY_Y_CHANNEL)
        direction = _direction_from_axes(x - _CENTER, y - _CENTER)
        if direction is not None:
            self._emit(direction, _REPEAT_INTERVAL_S)

    def _scan_button(self) -> None:
        if self._gpio.input(JOY_SW_PIN) == self._gpio.LOW:
            self._emit(ENC_PUSH, _DEBOUNCE_S)

    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            self._scan_axes()
            self._scan_button()
            time.sleep(_SCAN_INTERVAL_S)

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        self._gpio.cleanup()
        self._bus.close()
