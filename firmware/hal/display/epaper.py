"""Real e-ink driver backend (SPI). Not runnable without the actual panel —
this is deliberately a thin, structured stub: fill in `_spi_write_frame`
once hardware exists and the exact panel/controller (see profiles.py) is
confirmed. Kept import-safe (spidev/RPi.GPIO imported lazily) so the rest of
the firmware can be developed and tested with --simulate on any machine.
"""
from __future__ import annotations

from .base import DisplayHAL


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

    def _reset(self) -> None:
        raise NotImplementedError(
            "Panel reset/init sequence depends on the exact controller "
            f"({self.profile.controller}) datasheet — fill in once the panel is ordered."
        )

    def _init_controller(self) -> None:
        raise NotImplementedError("See _reset().")

    def _render_text_to_bitmap(self, lines: list[str]) -> bytes:
        """Render `lines` (Pillow, monospace font sized to fit
        self.profile.visible_rows) into a 1bpp bitmap sized for
        self.profile.width x self.profile.height."""
        from PIL import Image, ImageDraw  # noqa: PLC0415

        img = Image.new("1", (self.profile.width, self.profile.height), 1)
        draw = ImageDraw.Draw(img)
        line_height = self.profile.height // max(self.profile.visible_rows, 1)
        for i, line in enumerate(lines[: self.profile.visible_rows]):
            draw.text((4, i * line_height), line, fill=0)
        return img.tobytes()

    def draw_lines(self, lines: list[str]) -> None:
        self._ensure_hardware()
        bitmap = self._render_text_to_bitmap(lines)
        self._spi_write_frame(bitmap)

    def _spi_write_frame(self, bitmap: bytes) -> None:
        raise NotImplementedError(
            "Full-frame partial-refresh write sequence — implement against "
            f"the {self.profile.controller} datasheet once hardware exists."
        )

    def set_backlight(self, r: int, g: int, b: int) -> None:
        raise NotImplementedError(
            "Custom JapySoft RGB edge-lighting — switching mechanism still "
            "TBD per project memory; wire up once the LED driver circuit is decided."
        )
