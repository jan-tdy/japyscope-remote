"""Real e-ink driver backend (SPI), targeting the SSD1680-family controller
`profiles.py` confirms for the 2.13" panel (also covers the 4.26"/SSD1677
profile — SSD1677 is command-compatible with SSD1680 for the subset used
here). `DisplayHAL.draw_lines`/`draw_bitmap` take an optional `partial=True`
for a fast refresh (see `_spi_write_frame_partial`) instead of the slow,
electromechanical full refresh that was the only option before; see
`firmware/ui/controller.py` for when each is used.

The 2.13" panel on Seeed's XIAO ePaper driver board has no usable
full-refresh waveform in its OTP: a refresh with 0x22=0xF7 ("load LUT from
OTP") ends within a few milliseconds and never moves a pixel. Like
Waveshare's epd2in13_V3 driver and ESPHome's `2.13inv3` model (confirmed
working on this exact board), the driver loads the waveform and drive
voltages into registers at init and refreshes with 0x22=0xC7. Profiles
without an entry in `_REGISTER_WAVEFORMS` keep the OTP refresh.

Still unconfirmed on hardware: which way `_ROTATE_CLOCKWISE` should turn the
logical canvas to reach the 2.13" profile's native portrait RAM axes
(profiles.py). Kept import-safe (spidev/RPi.GPIO imported lazily) so the
rest of the firmware can be developed and tested with --simulate on any
machine.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

from .base import DisplayHAL
from .rasterizer import render as render_text_to_bitmap
from .rasterizer import rotate_90, stride_for

logger = logging.getLogger(__name__)

# Which way rotate_90() turns the logical canvas to reach a profile's native
# RAM axes (see profiles.py's native_width/native_height). The one thing
# that can't be confirmed without the physical panel in hand — flip this if
# the drawn frame comes out mirrored/rotated the wrong way once wired up.
_ROTATE_CLOCKWISE = True

# Seeed's early ePaper Driver Board V2 batch (MOA250113001) only passes SPI
# cleanly between ~20 and ~200 kHz; faster, the panel receives corrupted
# bytes (Seeed forum, "ePaper Driver Board for Seeed Studio XIAO"). 100 kHz
# works on every batch and still writes a full frame in well under a second.
# Override with JAPYSCOPE_EPAPER_SPI_HZ (e.g. in /etc/japyscope/environment).
DEFAULT_SPI_HZ = 100_000


def spi_speed_hz() -> int:
    value = os.environ.get("JAPYSCOPE_EPAPER_SPI_HZ", "")
    return int(value) if value.strip() else DEFAULT_SPI_HZ

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
_CMD_WRITE_RAM_RED = 0x26
_CMD_DISPLAY_UPDATE_CONTROL_2 = 0x22
_CMD_MASTER_ACTIVATION = 0x20
_CMD_DEEP_SLEEP = 0x10
_CMD_WRITE_LUT = 0x32
_CMD_END_OPTION = 0x3F
_CMD_GATE_VOLTAGE = 0x03
_CMD_SOURCE_VOLTAGE = 0x04
_CMD_WRITE_VCOM = 0x2C
_CMD_DISPLAY_OPTION = 0x37  # Waveshare's displayPartial(); undocumented under this name in the datasheet's command list

# 0x22 display-update sequences: display mode 1 with the waveform from OTP,
# or with the waveform already loaded into registers via 0x32.
_UPDATE_FULL_OTP_LUT = 0xF7
_UPDATE_FULL_REGISTER_LUT = 0xC7
# Partial refresh is two 0x22/0x20 activations: a "prime" pass with no new
# RAM content (just the new LUT/border/display-option settings taking
# effect against whatever's already in RAM), then the real one after the
# new frame is written — see _spi_write_frame_partial().
_UPDATE_PARTIAL_PRIME = 0xC0
_UPDATE_PARTIAL_QUALITY = 0x0F  # Waveshare also lists 0x0C ("fast", more ghosting) and 0xCF


def partial_update_mode() -> int:
    """The 0x22 byte for the real (non-prime) partial-refresh activation —
    0x0F by default, but reported as needing "a bit of tuning" on real
    hardware once partial refresh was actually visible. Override with
    JAPYSCOPE_EPAPER_PARTIAL_MODE (hex or decimal, e.g. "0x0C" or "12") to
    try Waveshare's other two documented partial modes without a firmware
    change: 0x0C ("fast", more ghosting, possibly also fixes whatever was
    wrong) or 0xCF."""
    value = os.environ.get("JAPYSCOPE_EPAPER_PARTIAL_MODE", "").strip()
    if not value:
        return _UPDATE_PARTIAL_QUALITY
    try:
        return int(value, 0)
    except ValueError:
        return _UPDATE_PARTIAL_QUALITY

# Waveshare epd2in13_V3.py `lut_full_update` (same bytes ESPHome's 2.13inv3
# loads): 153 bytes for 0x32 — 5x12 voltage selects, 12x7 phase timings,
# 6 frame-rate bytes, 3 XON bytes.
FULL_UPDATE_WAVEFORM_2_13 = bytes(
    [0x80, 0x4A, 0x40, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x40, 0x4A, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x80, 0x4A, 0x40, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x40, 0x4A, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x0] * 12
    + [0xF, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0xF, 0x0, 0x0, 0xF, 0x0, 0x0, 0x2]
    + [0xF, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x1, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x0] * (8 * 7)
    + [0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x0, 0x0, 0x0]
)
# The five bytes that follow the LUT in Waveshare's list:
# EOPT (0x3F), VGH (0x03), VSH1/VSH2/VSL (0x04), VCOM (0x2C).
FULL_UPDATE_VOLTAGES_2_13 = (0x22, 0x17, bytes([0x41, 0x00, 0x32]), 0x36)

# Waveshare epd2in13_V3.py `lut_partial_update` — same 153-byte shape as the
# full waveform above (same source), a different waveform picked for speed
# over quality: real SSD1680 hardware reportedly does a partial refresh in
# roughly a third the time of a full one, at the cost of some ghosting that
# accumulates over repeated partial refreshes — periodic full refreshes
# clear it (see firmware/ui/controller.py). Shares FULL_UPDATE_VOLTAGES_2_13
# (EOPT/VGH/source/VCOM) — confirmed identical between Waveshare's two LUT
# entries, not an assumption made here.
PARTIAL_UPDATE_WAVEFORM_2_13 = bytes(
    [0x0, 0x40, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x80, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x40, 0x40, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x0, 0x80, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x0] * 12
    + [0x14, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x1, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x1, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x0, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0]
    + [0x0] * (8 * 7)
    + [0x22, 0x22, 0x22, 0x22, 0x22, 0x22, 0x0, 0x0, 0x0]
)

# Partial-refresh-only register state (Waveshare's displayPartial): a 10-byte
# 0x37 "display option" payload and a different border waveform (0x80, vs
# 0x05 at init) — both confirmed against the same reference source as the
# waveform tables above, not derived/guessed.
_PARTIAL_DISPLAY_OPTION = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x40, 0x00, 0x00, 0x00, 0x00])
_PARTIAL_BORDER_WAVEFORM = 0x80

_REGISTER_WAVEFORMS = {
    "2.13in": (FULL_UPDATE_WAVEFORM_2_13, FULL_UPDATE_VOLTAGES_2_13),
}
_PARTIAL_REGISTER_WAVEFORMS = {
    "2.13in": (PARTIAL_UPDATE_WAVEFORM_2_13, FULL_UPDATE_VOLTAGES_2_13),
}

# spidev's SPI_IOC_WR_MAX xfer size on the Pi is 4096 bytes by default;
# chunk defensively rather than assume /sys/module/spidev/parameters/bufsiz.
_SPI_CHUNK = 4096


class EPaperDisplay(DisplayHAL):
    """SPI wiring (BCM numbering) — cross-check against docs/WIRING.md,
    which is the single source of truth once pins are finalized:
      - SPI0 MOSI/SCLK for DIN/CLK; CS on CE0's pin (BCM8), driven here
        as a plain GPIO (see _transfer())
      - a free GPIO for DC (data/command)
      - a free GPIO for RST
      - a free GPIO for BUSY (input)
    """

    def __init__(
        self, *args, dc_pin: int = 25, rst_pin: int = 17, busy_pin: int = 24, cs_pin: int = 8, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.cs_pin = cs_pin
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
        GPIO.setup(self.dc_pin, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.rst_pin, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.busy_pin, GPIO.IN)
        spi = spidev.SpiDev()
        spi.open(0, 0)
        spi.max_speed_hz = spi_speed_hz()
        spi.mode = 0
        # On the bring-up Pi, CE0 never went low during a spidev transfer
        # while SCK/MOSI toggled, so the panel was never selected. Drive CS
        # ourselves (as Waveshare's Pi driver does) instead of trusting the
        # kernel's chip select.
        try:
            spi.no_cs = True
        except OSError as exc:
            logger.warning("spidev refused no_cs (%s); driving CS alongside the kernel", exc)
        GPIO.setup(self.cs_pin, GPIO.OUT, initial=GPIO.HIGH)
        self._spi = spi
        self._bring_up()

    def _bring_up(self) -> None:
        """Reset + init the controller, undoing `self._spi` on failure (e.g.
        BUSY never clearing) so the next draw_lines() call retries hardware
        bring-up from scratch instead of _ensure_hardware() silently seeing
        a non-None `self._spi` and skipping setup forever."""
        try:
            self._reset()
            self._init_controller()
        except Exception:
            self._spi.close()
            self._spi = None
            raise
        else:
            logger.info(
                "%s bring-up complete (dc=BCM%d rst=BCM%d busy=BCM%d)",
                self.profile.controller, self.dc_pin, self.rst_pin, self.busy_pin,
            )

    # -- low-level SPI/GPIO helpers -----------------------------------

    def _transfer(self, data: list[int]) -> None:
        self._gpio.output(self.cs_pin, self._gpio.LOW)
        try:
            self._spi.writebytes(data)
        finally:
            self._gpio.output(self.cs_pin, self._gpio.HIGH)

    def _write_command(self, cmd: int, data: bytes = b"") -> None:
        self._gpio.output(self.dc_pin, self._gpio.LOW)
        self._transfer([cmd])
        if data:
            self._write_data(data)

    def _write_data(self, data: bytes) -> None:
        self._gpio.output(self.dc_pin, self._gpio.HIGH)
        for offset in range(0, len(data), _SPI_CHUNK):
            self._transfer(list(data[offset : offset + _SPI_CHUNK]))

    def _wait_busy(self, timeout_s: float = 5.0, phase: str = "reset/init", min_expected_s: float = 0.005) -> None:
        # Logged at INFO (not DEBUG) because it's the cheapest hardware-bring-up
        # diagnostic available without a scope. `min_expected_s` is phase-
        # specific: SW-reset/init BUSY is genuinely short (single-digit-to-
        # tens of ms on real SSD1680 hardware), but a *full refresh* (the
        # call from _spi_write_frame, after MASTER_ACTIVATION) is an
        # electromechanical process — real hardware holds BUSY for on the
        # order of a second or more while the panel visibly flashes, so
        # 300ms is already a generous floor. Clearing faster than the floor,
        # with the panel showing no visible activity, means BUSY (and likely
        # the rest of the SPI bus) isn't actually reaching the panel — a
        # wiring problem, not a code one; the SPI/GPIO calls here "succeed"
        # regardless of what's physically wired on the other end. See
        # docs/WIRING.md.
        start = time.monotonic()
        deadline = start + timeout_s
        while self._gpio.input(self.busy_pin) == self._gpio.HIGH:
            if time.monotonic() > deadline:
                raise TimeoutError(
                    f"{self.profile.controller} BUSY pin (BCM{self.busy_pin}) stuck high "
                    f"past {timeout_s}s during {phase} — check docs/WIRING.md wiring/pin numbers"
                )
            time.sleep(0.01)
        elapsed = time.monotonic() - start
        logger.info(
            "%s BUSY (BCM%d) cleared after %.3fs (%s)",
            self.profile.controller, self.busy_pin, elapsed, phase,
        )
        if elapsed < min_expected_s:
            logger.warning(
                "BUSY (BCM%d) cleared suspiciously fast for %s (%.3fs, expected at least %.3fs) — "
                "this near-instant clear usually means BUSY isn't actually wired to the panel "
                "(floating pin), which often means the rest of the SPI bus isn't either — check "
                "continuity against docs/WIRING.md",
                self.busy_pin, phase, elapsed, min_expected_s,
            )

    # -- panel bring-up -------------------------------------------------

    def _reset(self) -> None:
        # Seeed_GFX's SSD1680_Init.h timing for the XIAO ePaper driver board
        # (BOARD_SCREEN_COMBO 508): 10ms low, then 120ms high before the
        # controller is ready. Waveshare's shorter 20ms settle isn't enough
        # for every panel revision.
        self._gpio.output(self.rst_pin, self._gpio.LOW)
        time.sleep(0.01)
        self._gpio.output(self.rst_pin, self._gpio.HIGH)
        time.sleep(0.12)

    def _quick_reset(self) -> None:
        """Abbreviated reset pulse before a partial refresh (Waveshare's
        displayPartial) — a real hardware reset of the controller, just
        with a much shorter settle than _reset()'s; BUSY-gating the LUT
        write right after (_load_waveform(), via _wait_busy()) stands in
        for the longer fixed delay."""
        self._gpio.output(self.rst_pin, self._gpio.LOW)
        time.sleep(0.001)
        self._gpio.output(self.rst_pin, self._gpio.HIGH)

    def _init_controller(self) -> None:
        profile = self.profile
        self._wait_busy(phase="hw-reset")
        self._write_command(_CMD_SW_RESET)
        self._wait_busy(phase="sw-reset")

        # Native RAM axes, not the logical width/height — see profiles.py's
        # native_width/native_height and _to_native_orientation() below.
        # SSD1680's source axis maxes out at 176px, so the 2.13" profile's
        # 250px-wide logical canvas would silently exceed it if used here
        # directly (PR #25 review).
        gate_minus_1 = profile.native_height - 1
        self._write_command(
            _CMD_DRIVER_OUTPUT_CONTROL,
            bytes([gate_minus_1 & 0xFF, (gate_minus_1 >> 8) & 0xFF, 0x00]),
        )
        self._write_command(_CMD_DATA_ENTRY_MODE, bytes([0x03]))  # X then Y, both incrementing

        self._set_window()
        self._write_command(_CMD_BORDER_WAVEFORM, bytes([0x05]))
        self._write_command(_CMD_TEMP_SENSOR_CONTROL, bytes([0x80]))  # internal sensor
        self._write_command(_CMD_DISPLAY_UPDATE_CONTROL, bytes([0x00, 0x80]))
        self._set_cursor(0, 0)
        self._wait_busy(phase="init")
        self._load_register_waveform()

    def _load_register_waveform(self) -> None:
        waveform = _REGISTER_WAVEFORMS.get(self.profile.name)
        if waveform is None:
            return
        lut, (eopt, vgh, source, vcom) = waveform
        self._load_waveform(lut, eopt, vgh, source, vcom)

    def _load_waveform(self, lut: bytes, eopt: int, vgh: int, source: bytes, vcom: int) -> None:
        self._write_command(_CMD_WRITE_LUT, lut)
        self._write_command(_CMD_END_OPTION, bytes([eopt]))
        self._write_command(_CMD_GATE_VOLTAGE, bytes([vgh]))
        self._write_command(_CMD_SOURCE_VOLTAGE, source)
        self._write_command(_CMD_WRITE_VCOM, bytes([vcom]))

    def _set_window(self) -> None:
        """The RAM address window — native axes, full frame. Set once at
        init, and re-asserted by _spi_write_frame_partial() since the quick
        reset pulse before a partial refresh is a real hardware reset
        (Waveshare's displayPartial does the same defensive re-assert)."""
        profile = self.profile
        gate_minus_1 = profile.native_height - 1
        source_stride = stride_for(profile.native_width)
        self._write_command(_CMD_SET_RAM_X_ADDRESS, bytes([0x00, (source_stride - 1) & 0xFF]))
        self._write_command(
            _CMD_SET_RAM_Y_ADDRESS,
            bytes([0x00, 0x00, gate_minus_1 & 0xFF, (gate_minus_1 >> 8) & 0xFF]),
        )

    def _set_cursor(self, x_byte: int, y: int) -> None:
        self._write_command(_CMD_SET_RAM_X_COUNTER, bytes([x_byte & 0xFF]))
        self._write_command(_CMD_SET_RAM_Y_COUNTER, bytes([y & 0xFF, (y >> 8) & 0xFF]))

    # -- DisplayHAL interface --------------------------------------------

    def _render_text_to_bitmap(self, lines: list[str], invert_row: Optional[int] = None) -> bytes:
        return render_text_to_bitmap(self.profile, lines, invert_row)

    def draw_lines(self, lines: list[str], invert_row: Optional[int] = None, partial: bool = False) -> None:
        self._ensure_hardware()
        bitmap = self._render_text_to_bitmap(lines, invert_row)
        if partial and self._spi_write_frame_partial(bitmap):
            return
        self._spi_write_frame(bitmap)

    def draw_bitmap(self, bitmap: bytes, partial: bool = False) -> None:
        self._ensure_hardware()
        if partial and self._spi_write_frame_partial(bitmap):
            return
        self._spi_write_frame(bitmap)

    def _to_native_orientation(self, bitmap: bytes) -> bytes:
        """Rotate the logical width x height bitmap to match the
        controller's native RAM axes, when they differ (see profiles.py)."""
        profile = self.profile
        if (profile.native_width, profile.native_height) == (profile.width, profile.height):
            return bitmap
        if (profile.native_width, profile.native_height) == (profile.height, profile.width):
            return rotate_90(bitmap, profile.width, profile.height, clockwise=_ROTATE_CLOCKWISE)
        raise ValueError(
            f"{profile.name}: native {profile.native_width}x{profile.native_height} doesn't "
            f"match logical {profile.width}x{profile.height} directly or transposed"
        )

    def _spi_write_frame(self, bitmap: bytes) -> None:
        native = self._to_native_orientation(bitmap)
        # The controller picks each pixel's waveform from both RAMs; ESPHome's
        # 2.13inv3 fills the second one too rather than leave power-on garbage.
        for ram in (_CMD_WRITE_RAM_BW, _CMD_WRITE_RAM_RED):
            self._set_cursor(0, 0)
            self._write_command(ram, native)
        update = (
            _UPDATE_FULL_REGISTER_LUT if self.profile.name in _REGISTER_WAVEFORMS else _UPDATE_FULL_OTP_LUT
        )
        self._write_command(_CMD_DISPLAY_UPDATE_CONTROL_2, bytes([update]))
        self._write_command(_CMD_MASTER_ACTIVATION)
        # A real full refresh is electromechanical — on the order of a
        # second or more, not milliseconds; see _wait_busy()'s docstring.
        self._wait_busy(phase="full refresh", min_expected_s=0.3)

    def _spi_write_frame_partial(self, bitmap: bytes) -> bool:
        """Fast refresh (Waveshare epd2in13_V3.py's displayPartial, same
        reference source as the waveform tables): only defined for a
        profile with a partial register waveform — returns False and does
        nothing otherwise, so callers fall back to _spi_write_frame().
        Trades quality for speed (real SSD1680 hardware reportedly does
        this in roughly a third the time of a full refresh) — ghosting
        accumulates over repeated partial refreshes since this never
        rewrites the "red" RAM full refreshes use as the diff reference
        (see firmware/ui/controller.py for the periodic full refresh that
        clears it).

        A previous revision of this method re-sent DRIVER_OUTPUT_CONTROL
        and DATA_ENTRY_MODE right after _quick_reset(), on the theory that
        the hardware RST pulse clears those registers to power-on defaults.
        Reported on hardware as making every partial refresh behave like a
        full one (slow, visibly flashing) — removed again, since the
        reference displayPartial() this is ported from doesn't re-send
        them either and is the confirmed-working source for every other
        byte in this sequence; whatever made the original garbling report
        happen, it wasn't this."""
        waveform = _PARTIAL_REGISTER_WAVEFORMS.get(self.profile.name)
        if waveform is None:
            return False
        native = self._to_native_orientation(bitmap)
        lut, (eopt, vgh, source, vcom) = waveform

        self._quick_reset()
        self._load_waveform(lut, eopt, vgh, source, vcom)
        self._wait_busy(phase="partial LUT load")
        self._write_command(_CMD_DISPLAY_OPTION, _PARTIAL_DISPLAY_OPTION)
        self._write_command(_CMD_BORDER_WAVEFORM, bytes([_PARTIAL_BORDER_WAVEFORM]))
        self._write_command(_CMD_DISPLAY_UPDATE_CONTROL_2, bytes([_UPDATE_PARTIAL_PRIME]))
        self._write_command(_CMD_MASTER_ACTIVATION)
        self._wait_busy(phase="partial prime")

        self._set_window()
        self._set_cursor(0, 0)
        self._write_command(_CMD_WRITE_RAM_BW, native)
        self._write_command(_CMD_DISPLAY_UPDATE_CONTROL_2, bytes([partial_update_mode()]))
        self._write_command(_CMD_MASTER_ACTIVATION)
        self._wait_busy(phase="partial refresh", min_expected_s=0.05)
        return True

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
