"""The JapyScope boot splash: an orbiting-planet mark over the "JapyScope"
wordmark and a small "JAPYSOFT" caption, composed as a 1bpp bitmap. The
orbit/planet/moon are plain pixel math (plotted directly, no image
library — a one-time ~250x122 boot image has no performance budget to
justify a fancier scanline-fill approach); the wordmark and caption are
rendered through `rasterizer.py`'s shared TTF text helpers (see its module
docstring for why text moved off the old dot-matrix font) so the logo's
type matches the menu screens'. Drawn once at boot by `firmware/splash.py`
via `DisplayHAL.draw_bitmap()`.

Picked from 4 black-and-white concepts drawn up as an artifact (orbit
wordmark, scope badge, telescope icon, dot-matrix "J") — this is variant 1.
Sized and positioned against the confirmed 2.13" 250x122 canvas
(`profiles.PROFILE_2_13`); re-check proportions if drawn against a very
different profile (e.g. 4.26"), since the constants below are absolute
pixels, not scaled from `profile.width`/`height`.
"""
from __future__ import annotations

import math

from .profiles import DisplayProfile
from .rasterizer import _set_black, draw_text, stride_for, text_size

_PLANET_RADIUS = 15
_ORBIT_RX = 36
_ORBIT_RY = 13
_ORBIT_TILT_DEG = -18
_ORBIT_BAND_PX = 2  # ring stroke thickness
_MOON_RADIUS = 4

_WORDMARK = "JapyScope"
_WORDMARK_FONT_PX = 24
_CAPTION = "JAPYSOFT"
_CAPTION_FONT_PX = 11
_ICON_TO_WORDMARK_GAP = 8
_WORDMARK_TO_CAPTION_GAP = 6


def _fill_circle(buf: bytearray, stride: int, width: int, height: int, cx: int, cy: int, r: int) -> None:
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                _set_black(buf, stride, width, height, cx + dx, cy + dy)


def _draw_orbit(buf: bytearray, stride: int, width: int, height: int, cx: int, cy: int) -> None:
    """A tilted ellipse (the orbit ring) plus a small dot riding it (the
    moon) — sampled parametrically one degree at a time and plotted
    pixel-by-pixel, rather than computed with a scanline fill, since a
    one-time ~128x74 boot image has no performance budget to justify the
    extra complexity. `_ORBIT_BAND_PX` nested ellipses a pixel apart give
    the ring enough stroke width to survive 1bpp rounding."""
    theta = math.radians(_ORBIT_TILT_DEG)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    for band in range(_ORBIT_BAND_PX):
        rx, ry = _ORBIT_RX - band, _ORBIT_RY - band
        for deg in range(360):
            angle = math.radians(deg)
            dx, dy = rx * math.cos(angle), ry * math.sin(angle)
            x = dx * cos_t - dy * sin_t
            y = dx * sin_t + dy * cos_t
            _set_black(buf, stride, width, height, cx + round(x), cy + round(y))
    moon_x = cx + _ORBIT_RX * cos_t
    moon_y = cy + _ORBIT_RX * sin_t
    _fill_circle(buf, stride, width, height, round(moon_x), round(moon_y), _MOON_RADIUS)


def _draw_centered_text(buf: bytearray, stride: int, width: int, height: int, y: int, text: str, font_px: int) -> None:
    w, _ = text_size(text, font_px)
    x = max(0, (width - w) // 2)
    draw_text(buf, stride, width, height, x, y, text, font_px)


def render(profile: DisplayProfile) -> bytes:
    width, height = profile.width, profile.height
    stride = stride_for(width)
    buf = bytearray(b"\xff" * (stride * height))

    cx = width // 2
    icon_cy = height * 2 // 7
    _draw_orbit(buf, stride, width, height, cx, icon_cy)
    _fill_circle(buf, stride, width, height, cx, icon_cy, _PLANET_RADIUS)

    _, wordmark_h = text_size(_WORDMARK, _WORDMARK_FONT_PX)
    wordmark_y = icon_cy + _PLANET_RADIUS + _ICON_TO_WORDMARK_GAP
    _draw_centered_text(buf, stride, width, height, wordmark_y, _WORDMARK, _WORDMARK_FONT_PX)

    caption_y = wordmark_y + wordmark_h + _WORDMARK_TO_CAPTION_GAP
    _draw_centered_text(buf, stride, width, height, caption_y, _CAPTION, _CAPTION_FONT_PX)

    return bytes(buf)
