"""Exercises EPaperDisplay's SSD1680 command sequence and rasterizer
without real spidev/RPi.GPIO (Pi-only, not installed here) — fakes stand
in for the SPI bus and GPIO pins so the protocol logic itself is covered.
"""
from __future__ import annotations

import pytest

from firmware.hal.display.epaper import (
    _CMD_DISPLAY_UPDATE_CONTROL_2,
    _CMD_MASTER_ACTIVATION,
    _CMD_SW_RESET,
    _CMD_WRITE_RAM_BW,
    EPaperDisplay,
)
from firmware.hal.display.profiles import PROFILE_2_13
from firmware.hal.display.rasterizer import render, stride_for


class _FakeGPIO:
    HIGH = 1
    LOW = 0

    def __init__(self):
        self.calls: list[tuple[str, int, int]] = []
        self.busy = self.LOW  # BUSY deasserted so _wait_busy returns immediately

    def output(self, pin: int, value: int) -> None:
        self.calls.append(("output", pin, value))

    def input(self, pin: int) -> int:
        return self.busy


class _FakeSPI:
    def __init__(self):
        self.writes: list[list[int]] = []
        self.closed = False

    def writebytes(self, data: list[int]) -> None:
        self.writes.append(list(data))

    def close(self) -> None:
        self.closed = True


def _wired_display() -> tuple[EPaperDisplay, _FakeGPIO, _FakeSPI]:
    display = EPaperDisplay(profile=PROFILE_2_13)
    gpio, spi = _FakeGPIO(), _FakeSPI()
    display._gpio = gpio
    display._spi = spi
    return display, gpio, spi


def test_init_controller_sends_sw_reset_first():
    display, _, spi = _wired_display()
    display._init_controller()
    assert spi.writes[0] == [_CMD_SW_RESET]


def test_reset_pulses_rst_low_then_high():
    display, gpio, _ = _wired_display()
    display._reset()
    pin_values = [value for name, pin, value in gpio.calls if pin == display.rst_pin]
    assert pin_values == [gpio.HIGH, gpio.LOW, gpio.HIGH]


def test_spi_write_frame_sends_bitmap_then_activates():
    display, _, spi = _wired_display()
    bitmap = render(PROFILE_2_13, ["hello"])
    display._spi_write_frame(bitmap)

    commands = [call[0] for call in spi.writes]
    assert _CMD_WRITE_RAM_BW in commands
    assert commands.index(_CMD_WRITE_RAM_BW) < commands.index(_CMD_DISPLAY_UPDATE_CONTROL_2)
    assert commands.index(_CMD_DISPLAY_UPDATE_CONTROL_2) < commands.index(_CMD_MASTER_ACTIVATION)

    # The bitmap itself must show up verbatim in one of the data writes.
    assert any(bytes(w) == bitmap for w in spi.writes)


def test_wait_busy_times_out_instead_of_hanging():
    display, gpio, _ = _wired_display()
    gpio.busy = gpio.HIGH
    with pytest.raises(TimeoutError):
        display._wait_busy(timeout_s=0.05)


def test_sleep_closes_spi_and_is_idempotent():
    display, _, spi = _wired_display()
    display.sleep()
    assert spi.closed
    assert display._spi is None
    display.sleep()  # no-op, must not raise on a second call


def test_draw_lines_uses_ensure_hardware_then_writes_frame(monkeypatch):
    display, gpio, spi = _wired_display()
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)
    display.draw_lines(["JapyScope Remote", "by JapySoft"])
    assert _CMD_WRITE_RAM_BW in [call[0] for call in spi.writes]


def test_render_output_size_matches_profile():
    bitmap = render(PROFILE_2_13, ["Menu"])
    assert len(bitmap) == stride_for(PROFILE_2_13.width) * PROFILE_2_13.height


def test_render_never_raises_on_unmapped_or_accented_text():
    # Slovak strings from firmware/ui/i18n.py — must degrade, not crash.
    render(PROFILE_2_13, ["Zarovnanie", "Zaparkovať / Odparkovať", "Podsvietenie"])
    render(PROFILE_2_13, ["\U0001f600 emoji stays a box glyph"])


def test_render_invert_row_flips_the_whole_row_band_not_just_glyphs():
    plain = bytearray(render(PROFILE_2_13, ["Home", "Menu"]))
    inverted = bytearray(render(PROFILE_2_13, ["Home", "Menu"], invert_row=0))

    stride = stride_for(PROFILE_2_13.width)
    row_height = PROFILE_2_13.height // PROFILE_2_13.visible_rows
    row0 = slice(0, row_height * stride)
    row1 = slice(row_height * stride, 2 * row_height * stride)

    assert bytes(b ^ 0xFF for b in plain[row0]) == bytes(inverted[row0])
    assert plain[row1] == inverted[row1]  # untouched rows stay identical
