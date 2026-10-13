"""Text -> 1bpp frame buffer, shared by the real e-paper driver
(`epaper.py`) and its tests. Pure function, no SPI/GPIO — the split exists
so the rasterizer is exercisable without hardware, same reason
`SimulatorDisplay` exists.

Buffer convention: MSB-first, row-major, `ceil(width / 8)` bytes per row —
the addressing granularity SSD1680-family controllers use for their B/W
RAM (`epaper.py`'s `_spi_write_frame`). Bit=1 is white (no ink), bit=0 is
black — the common polarity for GoodDisplay/Waveshare SSD1680 modules;
reconfirm once the physical panel is in hand (see `docs/WIRING.md`).
"""
from __future__ import annotations

from typing import Optional

from .font5x7 import GLYPH_H, GLYPH_W, glyph_for
from .profiles import DisplayProfile

# Minimum on-screen gap (in raw font pixels, before scaling) between glyph
# cells and between text rows, so characters don't touch.
_COL_GAP = 1
_ROW_GAP = 2


def stride_for(width: int) -> int:
    return (width + 7) // 8


def rotate_90(buf: bytes, width: int, height: int, clockwise: bool = True) -> bytes:
    """Rotate a row-major 1bpp `width`x`height` buffer 90 degrees, producing
    a `height`x`width` buffer — needed when a profile's logical drawing
    canvas doesn't match its controller's native RAM source/gate axes (see
    `profiles.py`'s `native_width`/`native_height` and `epaper.py`'s
    `_to_native_orientation`). Every destination pixel maps from exactly one
    source pixel (rotation is a bijection over the full rectangle), so an
    unset destination bit is never left over from initialization — it's
    always the true rotated value of some source pixel.

    `clockwise` picks the rotation direction; which one matches the panel's
    physical mounting is the one thing here that can't be confirmed without
    the hardware in hand (see epaper.py's `_ROTATE_CLOCKWISE`) — flip it if
    the drawn frame comes out mirrored/rotated the wrong way.
    """
    src_stride = stride_for(width)
    dst_width, dst_height = height, width
    dst_stride = stride_for(dst_width)
    out = bytearray(dst_stride * dst_height)
    for y in range(height):
        row_start = y * src_stride
        for x in range(width):
            if not (buf[row_start + x // 8] >> (7 - (x % 8))) & 1:
                continue
            if clockwise:
                nx, ny = height - 1 - y, x
            else:
                nx, ny = y, width - 1 - x
            out[ny * dst_stride + nx // 8] |= 0x80 >> (nx % 8)
    return bytes(out)


def _set_black(buf: bytearray, stride: int, width: int, height: int, x: int, y: int) -> None:
    if 0 <= x < width and 0 <= y < height:
        buf[y * stride + x // 8] &= ~(0x80 >> (x % 8)) & 0xFF


def _invert_row_band(buf: bytearray, stride: int, y0: int, y1: int) -> None:
    for y in range(y0, y1):
        row_start = y * stride
        for xb in range(stride):
            buf[row_start + xb] ^= 0xFF


def _text_scale(row_height: int) -> int:
    """How many device pixels each font pixel becomes, so text fills the
    row band instead of looking tiny on a physical panel."""
    return max(1, min(4, row_height // (GLYPH_H + _ROW_GAP)))


def render(profile: DisplayProfile, lines: list[str], invert_row: Optional[int] = None) -> bytes:
    width, height = profile.width, profile.height
    stride = stride_for(width)
    # 0xFF = all-white background; glyph pixels below clear bits to black.
    buf = bytearray(b"\xff" * (stride * height))

    visible_rows = profile.visible_rows
    row_height = height // visible_rows if visible_rows else height
    scale = _text_scale(row_height)
    char_h = GLYPH_H * scale
    char_advance = (GLYPH_W + _COL_GAP) * scale

    for row_idx, line in enumerate(lines[:visible_rows]):
        y0 = row_idx * row_height + max(0, (row_height - char_h) // 2)
        x = 0
        for ch in line:
            if x + char_advance - _COL_GAP * scale > width:
                break
            glyph = glyph_for(ch)
            for gy in range(GLYPH_H):
                row_bits = glyph[gy]
                for gx in range(GLYPH_W):
                    if not (row_bits >> (GLYPH_W - 1 - gx)) & 1:
                        continue
                    px0 = x + gx * scale
                    py0 = y0 + gy * scale
                    for dy in range(scale):
                        for dx in range(scale):
                            _set_black(buf, stride, width, height, px0 + dx, py0 + dy)
            x += char_advance

        if row_idx == invert_row:
            band_end = min(height, (row_idx + 1) * row_height)
            _invert_row_band(buf, stride, row_idx * row_height, band_end)

    return bytes(buf)
