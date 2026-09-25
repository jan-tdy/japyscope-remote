"""Exercises EPaperDisplay's SSD1680 command sequence and rasterizer
without real spidev/RPi.GPIO (Pi-only, not installed here) — fakes stand
in for the SPI bus and GPIO pins so the protocol logic itself is covered.
"""
from __future__ import annotations

import pytest

from firmware.hal.display.epaper import (
    _CMD_DISPLAY_UPDATE_CONTROL_2,
    _CMD_DRIVER_OUTPUT_CONTROL,
    _CMD_MASTER_ACTIVATION,
    _CMD_SET_RAM_X_ADDRESS,
    _CMD_SET_RAM_Y_ADDRESS,
    _CMD_END_OPTION,
    _CMD_GATE_VOLTAGE,
    _CMD_SOURCE_VOLTAGE,
    _CMD_SW_RESET,
    _CMD_WRITE_LUT,
    _CMD_WRITE_RAM_BW,
    _CMD_WRITE_VCOM,
    FULL_UPDATE_VOLTAGES_2_13,
    FULL_UPDATE_WAVEFORM_2_13,
    EPaperDisplay,
)
from firmware.hal.display.profiles import PROFILE_2_13, PROFILE_4_26
from firmware.hal.display.rasterizer import render, rotate_90, stride_for


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
    assert pin_values == [gpio.LOW, gpio.HIGH]


def test_spi_write_frame_sends_bitmap_then_activates():
    display, _, spi = _wired_display()
    bitmap = render(PROFILE_2_13, ["hello"])
    display._spi_write_frame(bitmap)

    commands = [call[0] for call in spi.writes]
    assert _CMD_WRITE_RAM_BW in commands
    assert commands.index(_CMD_WRITE_RAM_BW) < commands.index(_CMD_DISPLAY_UPDATE_CONTROL_2)
    assert commands.index(_CMD_DISPLAY_UPDATE_CONTROL_2) < commands.index(_CMD_MASTER_ACTIVATION)

    # PROFILE_2_13's native RAM is portrait (122x250), transposed from its
    # 250x122 logical canvas — the write must carry the *rotated* bitmap,
    # not the raw logical one (PR #25 review: writing it unrotated exceeds
    # the SSD1680's 176px source-axis limit).
    expected = rotate_90(bitmap, PROFILE_2_13.width, PROFILE_2_13.height, clockwise=True)
    assert any(bytes(w) == expected for w in spi.writes)
    assert not any(bytes(w) == bitmap for w in spi.writes)


def test_spi_write_frame_fills_both_rams_with_the_same_frame():
    display, _, spi = _wired_display()
    bitmap = render(PROFILE_2_13, ["hello"])
    display._spi_write_frame(bitmap)
    expected = list(rotate_90(bitmap, PROFILE_2_13.width, PROFILE_2_13.height, clockwise=True))
    for ram in (0x24, 0x26):
        assert _data_after(spi, ram) == expected


def test_spi_write_frame_passes_through_unrotated_when_native_matches_logical():
    display = EPaperDisplay(profile=PROFILE_4_26)  # native == logical, no rotation
    gpio, spi = _FakeGPIO(), _FakeSPI()
    display._gpio, display._spi = gpio, spi
    bitmap = render(PROFILE_4_26, ["hello"])
    display._spi_write_frame(bitmap)

    # 4.26"'s frame (48000 bytes) is bigger than one SPI chunk, so it's
    # split across several writebytes() calls — reassemble them in order,
    # starting right after the RAM-write command byte.
    commands = spi.writes
    start = commands.index([_CMD_WRITE_RAM_BW]) + 1
    reconstructed = bytearray()
    i = start
    while len(reconstructed) < len(bitmap):
        reconstructed.extend(commands[i])
        i += 1
    assert bytes(reconstructed) == bitmap


def _data_after(spi: _FakeSPI, cmd: int) -> list[int]:
    commands = spi.writes
    idx = next(i for i, w in enumerate(commands) if w == [cmd])
    return commands[idx + 1]


def test_full_update_waveform_is_a_complete_ssd1680_lut():
    assert len(FULL_UPDATE_WAVEFORM_2_13) == 153


def test_init_loads_register_waveform_for_2_13():
    display, _, spi = _wired_display()
    display._init_controller()

    # Compared as one ordered slice: 0x03 also appears earlier as the data
    # byte of DATA_ENTRY_MODE, so looking commands up individually is ambiguous.
    start = spi.writes.index([_CMD_WRITE_LUT])
    eopt, vgh, source, vcom = FULL_UPDATE_VOLTAGES_2_13
    assert spi.writes[start:] == [
        [_CMD_WRITE_LUT], list(FULL_UPDATE_WAVEFORM_2_13),
        [_CMD_END_OPTION], [eopt],
        [_CMD_GATE_VOLTAGE], [vgh],
        [_CMD_SOURCE_VOLTAGE], list(source),
        [_CMD_WRITE_VCOM], [vcom],
    ]


def test_refresh_uses_register_waveform_on_2_13_and_otp_elsewhere():
    display, _, spi = _wired_display()
    display._spi_write_frame(render(PROFILE_2_13, ["x"]))
    assert _data_after(spi, _CMD_DISPLAY_UPDATE_CONTROL_2) == [0xC7]

    other = EPaperDisplay(profile=PROFILE_4_26)
    other._gpio, other._spi = _FakeGPIO(), _FakeSPI()
    other._init_controller()
    assert [_CMD_WRITE_LUT] not in other._spi.writes
    other._spi_write_frame(render(PROFILE_4_26, ["x"]))
    assert _data_after(other._spi, _CMD_DISPLAY_UPDATE_CONTROL_2) == [0xF7]


def test_init_controller_uses_native_ram_axes_not_logical():
    # PROFILE_2_13: logical 250x122 canvas, native RAM 122 (source) x 250 (gate).
    display, _, spi = _wired_display()
    display._init_controller()

    # source axis (X) end byte: stride_for(native_width=122) - 1 = 15
    assert _data_after(spi, _CMD_SET_RAM_X_ADDRESS) == [0x00, 15]
    # gate axis (Y) end: native_height=250 -> 249 = 0x00F9, little-endian
    assert _data_after(spi, _CMD_SET_RAM_Y_ADDRESS) == [0x00, 0x00, 0xF9, 0x00]
    # driver output control MUX = native_height - 1 = 249
    assert _data_after(spi, _CMD_DRIVER_OUTPUT_CONTROL) == [0xF9, 0x00, 0x00]


def test_wait_busy_times_out_instead_of_hanging():
    display, gpio, _ = _wired_display()
    gpio.busy = gpio.HIGH
    with pytest.raises(TimeoutError):
        display._wait_busy(timeout_s=0.05)


def test_bring_up_clears_spi_on_init_failure_so_next_draw_retries():
    # Previously, a BUSY timeout during _init_controller left self._spi set,
    # so _ensure_hardware()'s `if self._spi is not None: return` would skip
    # reset/init forever on every later draw_lines() call (PR #25 review).
    display, gpio, spi = _wired_display()
    gpio.busy = gpio.HIGH  # _wait_busy() inside _init_controller times out
    with pytest.raises(TimeoutError):
        display._bring_up()
    assert display._spi is None
    assert spi.closed


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


def _zero_row_stride_padding(buf: bytes, width: int, height: int) -> bytes:
    """Rows whose width isn't a multiple of 8 carry a few don't-care
    padding bits past the real pixel count (never addressed by the
    controller, since RAM writes are sized off the real width/height) —
    mask them out before comparing two buffers pixel-for-pixel."""
    stride = stride_for(width)
    valid_bits = width % 8
    if not valid_bits:
        return buf
    out = bytearray(buf)
    mask = (0xFF << (8 - valid_bits)) & 0xFF
    for y in range(height):
        out[y * stride + stride - 1] &= mask
    return bytes(out)


def test_rotate_90_swaps_dimensions_and_round_trips():
    width, height = PROFILE_2_13.width, PROFILE_2_13.height
    original = render(PROFILE_2_13, ["Menu", "> Catalog"])

    rotated = rotate_90(original, width, height, clockwise=True)
    assert len(rotated) == stride_for(height) * width

    back = rotate_90(rotated, height, width, clockwise=False)
    assert _zero_row_stride_padding(back, width, height) == _zero_row_stride_padding(
        original, width, height
    )


def test_render_invert_row_flips_the_whole_row_band_not_just_glyphs():
    plain = bytearray(render(PROFILE_2_13, ["Home", "Menu"]))
    inverted = bytearray(render(PROFILE_2_13, ["Home", "Menu"], invert_row=0))

    stride = stride_for(PROFILE_2_13.width)
    row_height = PROFILE_2_13.height // PROFILE_2_13.visible_rows
    row0 = slice(0, row_height * stride)
    row1 = slice(row_height * stride, 2 * row_height * stride)

    assert bytes(b ^ 0xFF for b in plain[row0]) == bytes(inverted[row0])
    assert plain[row1] == inverted[row1]  # untouched rows stay identical
