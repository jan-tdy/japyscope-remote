"""Text -> 1bpp frame buffer, shared by the real e-paper driver
(`epaper.py`) and its tests. No SPI/GPIO here — the split exists so the
rasterizer is exercisable without hardware, same reason `SimulatorDisplay`
exists.

Text is rendered with a real TTF font (Pillow + the bundled Roboto —
`fonts/Roboto-Regular.ttf`, Apache-2.0, see `fonts/LICENSE-Roboto.txt`)
instead of a hand-built dot-matrix bitmap font: a 5x7 grid blown up by an
integer block scale (this module's previous approach) reads as a crude
"calculator display" look and has no room to render Slovak diacritics
without folding them to their base Latin letter first. Pillow rasterizes
the real glyph outlines (anti-aliased) at whatever pixel size we ask for,
which this module then thresholds down to the 1bpp e-ink can actually
show — some edge pixels necessarily round one way or the other at this
resolution, but the letterforms read far more naturally than dot-matrix
blocks, and Roboto's glyph set covers Slovak natively (ť ľ č š ž ý á í é
ä ô and friends), so firmware/ui/i18n.py's "sk" strings no longer need any
accent-folding fallback.

Pillow is a real dependency now (requirements.txt) — Pillow 12 dropped
Python 3.9 (Raspberry Pi OS Bullseye's version), so a Pi still on Bullseye
needs to either upgrade to Bookworm/Trixie or pin an older
(3.9-compatible) Pillow itself; this project doesn't carry that pin. See
docs/TROUBLESHOOTING.md.

Buffer convention: MSB-first, row-major, `ceil(width / 8)` bytes per row —
the addressing granularity SSD1680-family controllers use for their B/W
RAM (`epaper.py`'s `_spi_write_frame`). Bit=1 is white (no ink), bit=0 is
black — the common polarity for GoodDisplay/Waveshare SSD1680 modules;
reconfirm once the physical panel is in hand (see `docs/WIRING.md`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from .profiles import DisplayProfile

_FONT_PATH = Path(__file__).parent / "fonts" / "Roboto-Regular.ttf"

# A glyph pixel at or below this gray level (0=black, 255=white) counts as
# ink once Pillow's anti-aliased render gets thresholded to 1bpp. The
# e-ink panel can't show gray, so this is the one knob for how "bold" text
# reads; the e-paper driver's own screenshot-confirmed bring-up is the
# closest thing to ground truth, not a formula.
_INK_THRESHOLD = 140

# Fixed pixel size for the per-row menu grid (render(), below) — picked
# (and confirmed against rendered screenshots after user feedback that the
# previous dot-matrix font's "giant" size and its 1.1x/2x shrink attempts
# were respectively unreadable-small and imperceptible) to read clearly at
# six rows on the 2.13" profile's 122px height.
MENU_FONT_PX = 14

_font_cache: dict[int, "ImageFont.FreeTypeFont"] = {}


def _font(px: int) -> "ImageFont.FreeTypeFont":
    try:
        return _font_cache[px]
    except KeyError:
        font = ImageFont.truetype(str(_FONT_PATH), px)
        _font_cache[px] = font
        return font


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


def text_size(text: str, font_px: int) -> tuple[int, int]:
    """The device-pixel (width, height) `text` occupies at `font_px`, as a
    real proportional font measures it — unlike the old dot-matrix grid,
    this genuinely depends on which characters are in `text`, not just how
    many. Shared by `render()` and anything composing a layout outside its
    per-row grid (e.g. `boot_logo.py`), so they size text identically."""
    if not text:
        return 0, 0
    left, top, right, bottom = _font(font_px).getbbox(text)
    return max(0, right - left), max(0, bottom - top)


def draw_text(buf: bytearray, stride: int, width: int, height: int, x: int, y: int, text: str, font_px: int) -> int:
    """Render `text` at `font_px` (anti-aliased, via Pillow) and stamp its
    ink into the shared 1bpp buffer with its top-left at device pixel
    (x, y), thresholding each glyph pixel at `_INK_THRESHOLD`. Returns the
    measured width (`text_size()[0]`), so callers can advance x without
    re-measuring."""
    w, h = text_size(text, font_px)
    if w <= 0 or h <= 0:
        return w
    font = _font(font_px)
    left, top, _, _ = font.getbbox(text)
    glyph_img = Image.new("L", (w, h), 255)
    ImageDraw.Draw(glyph_img).text((-left, -top), text, font=font, fill=0)
    glyph_px = glyph_img.load()
    for gy in range(h):
        for gx in range(w):
            if glyph_px[gx, gy] <= _INK_THRESHOLD:
                _set_black(buf, stride, width, height, x + gx, y + gy)
    return w


def render(profile: DisplayProfile, lines: list[str], invert_row: Optional[int] = None) -> bytes:
    width, height = profile.width, profile.height
    stride = stride_for(width)
    # 0xFF = all-white background; glyph pixels below clear bits to black.
    buf = bytearray(b"\xff" * (stride * height))

    visible_rows = profile.visible_rows
    row_height = height // visible_rows if visible_rows else height

    for row_idx, line in enumerate(lines[:visible_rows]):
        # Proportional text can't be truncated by a fixed per-character
        # cell like the old monospace grid — measure and drop characters
        # from the end until what's left actually fits. Menu labels are a
        # handful of words, so re-measuring per character is cheap.
        fitted = line
        while fitted and text_size(fitted, MENU_FONT_PX)[0] > width:
            fitted = fitted[:-1]
        w, h = text_size(fitted, MENU_FONT_PX)
        y0 = row_idx * row_height + max(0, (row_height - h) // 2)
        draw_text(buf, stride, width, height, 0, y0, fitted, MENU_FONT_PX)

        if row_idx == invert_row:
            band_end = min(height, (row_idx + 1) * row_height)
            _invert_row_band(buf, stride, row_idx * row_height, band_end)

    return bytes(buf)
