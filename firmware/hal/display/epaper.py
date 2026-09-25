"""Real e-ink driver backend (SPI), targeting the SSD1680-family controller
`profiles.py` confirms for the 2.13" panel (also covers the 4.26"/SSD1677
profile — SSD1677 is command-compatible with SSD1680 for the subset used
here). Full-refresh only: `DisplayHAL.draw_lines` replaces the whole screen
each call (see base.py), which is exactly what a full refresh does, so
there's no need for the panel's partial-refresh custom waveform LUT — that
part genuinely is vendor/part-number specific and stays out of scope until
the exact part is ordered and its datasheet is in hand (partial refresh
would only be worth adding later as a menu/list scroll optimization).

Not runnable without the actual panel: reset timing and RAM bit polarity
below follow the SSD1680 datasheet's typical values (used near-identically
across Waveshare/GoodDisplay 2.13" modules), but haven't been checked
against a soldered board — verify against docs/WIRING.md once hardware
exists. Kept import-safe (spidev/RPi.GPIO imported lazily) so the rest of
the firmware can be developed and tested with --simulate on any machine.
"""
from __future__ import annotations

import time
from typing import Optional

from .base import DisplayHAL
from .rasterizer import render as render_text_to_bitmap

# SSD1680 command bytes used here (subset — see datasheet ch. 8).
_CMD_SW_RESET = 0x12
_CMD_DRIVER_OUTPUT_CONTROL = 0x01
_CMD_DATA_ENTRY_MODE = 0x11
_CMD_SET_RAM_X_ADDRESS = 0x44
_CMD_SET_RAM_Y_ADDRESS = 0x45
_CMD_BORDER_WAVEFORM = 0x3C
_CMD_TEMP_SENSOR_CONTROL = 0x18
_CMD_DISPLAY_UPDATE_CONTROL = 0x21
_CMD_SET_RAM_X_COUNTER = 0x4E
_CMD_SET_RAM_Y_COUNTER = 0x4F
_CMD_WRITE_RAM_BW = 0x24
_CMD_DISPLAY_UPDATE_CONTROL_2 = 0x22
_CMD_MASTER_ACTIVATION = 0x20
_CMD_DEEP_SLEEP = 0x10

# spidev's SPI_IOC_WR_MAX xfer size on the Pi is 4096 bytes by default;
# chunk defensively rather than assume /sys/module/spidev/parameters/bufsiz.
_SPI_CHUNK = 4096


class EPaperDisplay(DisplayHAL):
    """SPI wiring (BCM numbering) — cross-check against docs/WIRING.md,
    which is the single source of truth once pins are finalized:
      - SPI0 MOSI/SCLK/CE0 for DIN/CLK/CS
      - a free GPIO for DC (data/command)
      - a free GPIO for RST
      - a free GPIO for BUSY (input)
    """

    def __init__(self, *args, dc_pin: int = 25, rst_pin: int = 17, busy_pin: int = 24, **kwargs):
        super().__init__(*args, **kwargs)
        self.dc_pin = dc_pin
        self.rst_pin = rst_pin
        self.busy_pin = busy_pin
        self._spi = None
        self._gpio = None

    def _ensure_hardware(self) -> None:
        if self._spi is not None:
            return
        import spidev  # noqa: PLC0415 (intentionally lazy — see module docstring)
        import RPi.GPIO as GPIO  # noqa: N814,PLC0415

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.dc_pin, GPIO.OUT)
        GPIO.setup(self.rst_pin, GPIO.OUT)
        GPIO.setup(self.busy_pin, GPIO.IN)
        self._spi = spidev.SpiDev()
        self._spi.open(0, 0)
        self._spi.max_speed_hz = 4_000_000
        self._reset()
        self._init_controller()

    # -- low-level SPI/GPIO helpers -----------------------------------

    def _write_command(self, cmd: int, data: bytes = b"") -> None:
        self._gpio.output(self.dc_pin, self._gpio.LOW)
        self._spi.writebytes([cmd])
        if data:
            self._write_data(data)

    def _write_data(self, data: bytes) -> None:
        self._gpio.output(self.dc_pin, self._gpio.HIGH)
        for offset in range(0, len(data), _SPI_CHUNK):
            self._spi.writebytes(list(data[offset : offset + _SPI_CHUNK]))

    def _wait_busy(self, timeout_s: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_s
        while self._gpio.input(self.busy_pin) == self._gpio.HIGH:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{self.profile.controller} BUSY pin (BCM{self.busy_pin}) stuck high "
                    f"past {timeout_s}s — check docs/WIRING.md wiring/pin numbers"
                )
            time.sleep(0.01)

    # -- panel bring-up -------------------------------------------------

    def _reset(self) -> None:
        # Typical SSD1680 hardware-reset pulse; near-identical across the
        # Waveshare/GoodDisplay reference drivers this panel family uses.
        self._gpio.output(self.rst_pin, self._gpio.HIGH)
        time.sleep(0.02)
        self._gpio.output(self.rst_pin, self._gpio.LOW)
        time.sleep(0.002)
        self._gpio.output(self.rst_pin, self._gpio.HIGH)
        time.sleep(0.02)

    def _init_controller(self) -> None:
        profile = self.profile
        self._write_command(_CMD_SW_RESET)
        self._wait_busy()

        height_minus_1 = profile.height - 1
        self._write_command(
            _CMD_DRIVER_OUTPUT_CONTROL,
            bytes([height_minus_1 & 0xFF, (height_minus_1 >> 8) & 0xFF, 0x00]),
        )
        self._write_command(_CMD_DATA_ENTRY_MODE, bytes([0x03]))  # X then Y, both incrementing

        stride = (profile.width + 7) // 8
        self._write_command(_CMD_SET_RAM_X_ADDRESS, bytes([0x00, (stride - 1) & 0xFF]))
        self._write_command(
            _CMD_SET_RAM_Y_ADDRESS,
            bytes([0x00, 0x00, height_minus_1 & 0xFF, (height_minus_1 >> 8) & 0xFF]),
        )
        self._write_command(_CMD_BORDER_WAVEFORM, bytes([0x05]))
        self._write_command(_CMD_TEMP_SENSOR_CONTROL, bytes([0x80]))  # internal sensor
        self._write_command(_CMD_DISPLAY_UPDATE_CONTROL, bytes([0x00, 0x80]))
        self._set_cursor(0, 0)
        self._wait_busy()

    def _set_cursor(self, x_byte: int, y: int) -> None:
        self._write_command(_CMD_SET_RAM_X_COUNTER, bytes([x_byte & 0xFF]))
        self._write_command(_CMD_SET_RAM_Y_COUNTER, bytes([y & 0xFF, (y >> 8) & 0xFF]))

    # -- DisplayHAL interface --------------------------------------------

    def _render_text_to_bitmap(self, lines: list[str], invert_row: Optional[int] = None) -> bytes:
        return render_text_to_bitmap(self.profile, lines, invert_row)

    def draw_lines(self, lines: list[str], invert_row: Optional[int] = None) -> None:
        self._ensure_hardware()
        bitmap = self._render_text_to_bitmap(lines, invert_row)
        self._spi_write_frame(bitmap)

    def _spi_write_frame(self, bitmap: bytes) -> None:
        self._set_cursor(0, 0)
        self._write_command(_CMD_WRITE_RAM_BW, bitmap)
        # 0xF7: full refresh using the controller's OTP LUT — no
        # panel-specific waveform table needed (see module docstring).
        self._write_command(_CMD_DISPLAY_UPDATE_CONTROL_2, bytes([0xF7]))
        self._write_command(_CMD_MASTER_ACTIVATION)
        self._wait_busy()

    def sleep(self) -> None:
        """Deep-sleep the panel (SSD1680 datasheet 0x10) — call when the
        controller is idle for a while (e.g. shutdown) so it isn't left
        driving the panel indefinitely. The next draw_lines() call
        re-initializes via _ensure_hardware()/_reset(), same as first use."""
        if self._spi is None:
            return
        self._write_command(_CMD_DEEP_SLEEP, bytes([0x01]))
        self._spi.close()
        self._spi = None
