"""Exercises EPaperDisplay's SSD1680 command sequence and rasterizer
without real spidev/RPi.GPIO (Pi-only, not installed here) — fakes stand
in for the SPI bus and GPIO pins so the protocol logic itself is covered.
"""
from __future__ import annotations

import pytest

from firmware.hal.display.epaper import (
    _CMD_DISPLAY_OPTION,
    _CMD_DISPLAY_UPDATE_CONTROL_2,
    _CMD_DRIVER_OUTPUT_CONTROL,
    _CMD_DATA_ENTRY_MODE,
    _CMD_BORDER_WAVEFORM,
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
    _PARTIAL_BORDER_WAVEFORM,
    _PARTIAL_DISPLAY_OPTION,
    FULL_UPDATE_VOLTAGES_2_13,
    FULL_UPDATE_WAVEFORM_2_13,
    PARTIAL_UPDATE_WAVEFORM_2_13,
    EPaperDisplay,
    partial_update_mode,
    spi_speed_hz,
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


def test_every_spi_transfer_is_framed_by_cs_driven_as_gpio():
    # The kernel's CE0 never asserted on the bring-up Pi, so the driver
    # drives CS itself: LOW for each transfer, HIGH again after it.
    display, gpio, spi = _wired_display()
    levels_during_writes = []
    original = spi.writebytes

    def recording_writebytes(data):
        cs_levels = [value for name, pin, value in gpio.calls if pin == display.cs_pin]
        levels_during_writes.append(cs_levels[-1])
        original(data)

    spi.writebytes = recording_writebytes
    display._write_command(0x3C, bytes([0x05]))
    assert levels_during_writes == [gpio.LOW, gpio.LOW]
    cs_levels = [value for name, pin, value in gpio.calls if pin == display.cs_pin]
    assert cs_levels == [gpio.LOW, gpio.HIGH, gpio.LOW, gpio.HIGH]


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
    # _CMD_DISPLAY_UPDATE_CONTROL_2's own byte value (0x22) coincides with
    # EOPT's data byte in FULL_UPDATE_VOLTAGES_2_13, now also written here
    # (the full-LUT-reload path) — take the *last* occurrence, the real
    # activation, not EOPT's incidental match earlier in the sequence.
    activate_index = len(commands) - 1 - commands[::-1].index(_CMD_DISPLAY_UPDATE_CONTROL_2)
    assert commands.index(_CMD_WRITE_RAM_BW) < activate_index < commands.index(_CMD_MASTER_ACTIVATION)

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
    # Last match, not first: a single-byte data value elsewhere in the
    # sequence (e.g. EOPT's byte happening to equal another command's own
    # code) can coincidentally equal [cmd] too. Every call site here wants
    # the real command's own data, which is always the latest such write.
    commands = spi.writes
    idx = len(commands) - 1 - next(i for i, w in enumerate(commands[::-1]) if w == [cmd])
    return commands[idx + 1]


def test_spi_speed_defaults_below_the_seeed_v2_limit_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv("JAPYSCOPE_EPAPER_SPI_HZ", raising=False)
    assert spi_speed_hz() == 100_000
    monkeypatch.setenv("JAPYSCOPE_EPAPER_SPI_HZ", "2000000")
    assert spi_speed_hz() == 2_000_000


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


def test_full_refresh_reloads_full_lut_and_border_after_a_partial_one(monkeypatch):
    # Confirmed on hardware: a full refresh issued after at least one
    # partial refresh still logged "full refresh" (the normal ~0.7s busy
    # wait), but visibly behaved like a partial one. Root cause:
    # _spi_write_frame() never reloads its own waveform — it just
    # activates with whatever LUT is currently resident in the SSD1680's
    # register, and every partial refresh overwrites that register (and
    # the border waveform) with its own values, never restoring them.
    display, gpio, spi = _wired_display()
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)
    display._init_controller()
    spi.writes.clear()

    display.draw_bitmap(render(PROFILE_2_13, ["x"]), partial=True)
    assert display._loaded_lut == "partial"

    spi.writes.clear()
    display._spi_write_frame(render(PROFILE_2_13, ["y"]))

    commands = [call[0] for call in spi.writes]
    assert commands.count(_CMD_WRITE_LUT) == 1
    assert bytes(spi.writes[commands.index(_CMD_WRITE_LUT) + 1]) == FULL_UPDATE_WAVEFORM_2_13
    border_index = commands.index(_CMD_BORDER_WAVEFORM)
    assert bytes(spi.writes[border_index + 1]) == bytes([0x05])
    assert display._loaded_lut == "full"
    # The reload must happen before the frame is activated, not after.
    assert border_index < commands.index(_CMD_WRITE_RAM_BW)


def test_full_refresh_does_not_reload_lut_when_already_full():
    # The common case (no partial refresh happened since init, or since
    # the last full refresh) shouldn't pay the reload cost every time.
    display, _, spi = _wired_display()
    display._init_controller()
    assert display._loaded_lut == "full"
    spi.writes.clear()

    display._spi_write_frame(render(PROFILE_2_13, ["x"]))

    commands = [call[0] for call in spi.writes]
    assert _CMD_WRITE_LUT not in commands


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


def test_draw_bitmap_uses_ensure_hardware_then_writes_frame_as_is(monkeypatch):
    display, gpio, spi = _wired_display()
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)
    bitmap = render(PROFILE_2_13, ["x"])
    display.draw_bitmap(bitmap)
    assert _CMD_WRITE_RAM_BW in [call[0] for call in spi.writes]
    expected = rotate_90(bitmap, PROFILE_2_13.width, PROFILE_2_13.height, clockwise=True)
    assert any(bytes(w) == expected for w in spi.writes)


def test_partial_refresh_sends_partial_lut_then_quick_activate_then_final_write(monkeypatch):
    display, gpio, spi = _wired_display()
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)
    bitmap = render(PROFILE_2_13, ["x"])

    display.draw_bitmap(bitmap, partial=True)

    commands = [call[0] for call in spi.writes]
    assert commands.count(_CMD_WRITE_LUT) == 1
    assert bytes(spi.writes[commands.index(_CMD_WRITE_LUT) + 1]) == PARTIAL_UPDATE_WAVEFORM_2_13
    assert commands.count(_CMD_DISPLAY_OPTION) == 1
    assert bytes(spi.writes[commands.index(_CMD_DISPLAY_OPTION) + 1]) == _PARTIAL_DISPLAY_OPTION
    # Two 0x22/0x20 activations: a priming one (no new RAM write between the
    # LUT load and it) and the real one, after WRITE_RAM — never only one.
    activate_indices = [i for i, c in enumerate(commands) if c == _CMD_MASTER_ACTIVATION]
    assert len(activate_indices) == 2
    write_ram_index = commands.index(_CMD_WRITE_RAM_BW)
    assert activate_indices[0] < write_ram_index < activate_indices[1]
    expected = rotate_90(bitmap, PROFILE_2_13.width, PROFILE_2_13.height, clockwise=True)
    assert bytes(spi.writes[write_ram_index + 1]) == expected
    # Border waveform set twice: 0x05 at init (_wired_display()), 0x80 here.
    border_indices = [i for i, c in enumerate(commands) if c == _CMD_BORDER_WAVEFORM]
    assert bytes(spi.writes[border_indices[-1] + 1]) == bytes([_PARTIAL_BORDER_WAVEFORM])


def test_partial_refresh_does_not_resend_driver_output_control_or_entry_mode(monkeypatch):
    # A prior revision re-sent DRIVER_OUTPUT_CONTROL/DATA_ENTRY_MODE right
    # after the quick reset, on the theory that the hardware RST pulse
    # clears those registers. Reported on hardware as making every partial
    # refresh behave like a slow, flashing full refresh — removed again, to
    # match the reference displayPartial() this sequence is ported from,
    # which never re-sends either command between the reset and the LUT
    # load. Only the LUT write (once at init, immediately re-loaded here)
    # should appear before the first activation.
    display, gpio, spi = _wired_display()
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)

    display.draw_bitmap(render(PROFILE_2_13, ["x"]), partial=True)

    commands = [call[0] for call in spi.writes]
    reset_index = commands.index(_CMD_WRITE_LUT)  # the partial LUT load, right after the quick reset
    pre_lut_commands = commands[:reset_index]
    assert _CMD_DRIVER_OUTPUT_CONTROL not in pre_lut_commands
    assert _CMD_DATA_ENTRY_MODE not in pre_lut_commands


def test_partial_update_mode_defaults_to_quality_and_is_overridable(monkeypatch):
    monkeypatch.delenv("JAPYSCOPE_EPAPER_PARTIAL_MODE", raising=False)
    assert partial_update_mode() == 0x0F
    monkeypatch.setenv("JAPYSCOPE_EPAPER_PARTIAL_MODE", "0x0C")
    assert partial_update_mode() == 0x0C
    monkeypatch.setenv("JAPYSCOPE_EPAPER_PARTIAL_MODE", "not-a-number")
    assert partial_update_mode() == 0x0F  # invalid override falls back, doesn't crash


def test_partial_refresh_pulses_reset_before_the_partial_lut(monkeypatch):
    display, gpio, spi = _wired_display()
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)
    gpio.calls.clear()

    display.draw_bitmap(render(PROFILE_2_13, ["x"]), partial=True)

    rst_values = [value for name, pin, value in gpio.calls if pin == display.rst_pin]
    assert rst_values[:2] == [gpio.LOW, gpio.HIGH]


def test_partial_refresh_unsupported_profile_falls_back_to_full(monkeypatch):
    display = EPaperDisplay(profile=PROFILE_4_26)
    gpio, spi = _FakeGPIO(), _FakeSPI()
    display._gpio, display._spi = gpio, spi
    monkeypatch.setattr(display, "_ensure_hardware", lambda: None)
    bitmap = render(PROFILE_4_26, ["x"])

    display.draw_bitmap(bitmap, partial=True)

    commands = [call[0] for call in spi.writes]
    assert _CMD_DISPLAY_OPTION not in commands
    assert bytes(spi.writes[commands.index(_CMD_DISPLAY_UPDATE_CONTROL_2) + 1]) == bytes([0xF7])  # OTP full update


def test_spi_write_frame_partial_reports_whether_it_ran(monkeypatch):
    display, gpio, spi = _wired_display()
    assert display._spi_write_frame_partial(render(PROFILE_2_13, ["x"])) is True

    other = EPaperDisplay(profile=PROFILE_4_26)
    other._gpio, other._spi = _FakeGPIO(), _FakeSPI()
    assert other._spi_write_frame_partial(render(PROFILE_4_26, ["x"])) is False
    assert other._spi.writes == []  # genuinely did nothing, not a silent full refresh


def test_render_output_size_matches_profile():
    bitmap = render(PROFILE_2_13, ["Menu"])
    assert len(bitmap) == stride_for(PROFILE_2_13.width) * PROFILE_2_13.height


def test_render_never_raises_on_unmapped_or_accented_text():
    # Slovak strings from firmware/ui/i18n.py — Roboto covers these
    # diacritics natively now (unlike the old dot-matrix font, no folding
    # to a base Latin letter needed), but must still degrade, not crash,
    # on a glyph Roboto genuinely doesn't have (the emoji below).
    render(PROFILE_2_13, ["Zarovnanie", "Zaparkovať / Odparkovať", "Podsvietenie"])
    render(PROFILE_2_13, ["\U0001f600 emoji doesn't crash the renderer"])


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
