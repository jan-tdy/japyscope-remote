"""Display HAL interface. Every screen in firmware/ui/ renders through this,
never through a concrete driver — so --simulate can swap in a backend with
no SPI/e-ink hardware present.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .profiles import DisplayProfile, get_active_profile


class DisplayHAL(ABC):
    def __init__(self, profile: Optional[DisplayProfile] = None):
        self.profile = profile or get_active_profile()

    @property
    def visible_rows(self) -> int:
        return self.profile.visible_rows

    @abstractmethod
    def draw_lines(self, lines: list[str], invert_row: Optional[int] = None) -> None:
        """Replace the whole screen with these text lines (full-refresh
        e-ink — see firmware/hal/display/epaper.py — so this is the only
        *text* drawing primitive the menu UI needs; firmware/ui/controller.py
        throttles how often it actually calls this while scrolling, since a
        real refresh is slow and visibly flashes). `invert_row`, if given,
        is the index into `lines` of the one row an "Invert" interface theme
        (`firmware/ui/themes.py`) wants shown as black background / white
        text instead of the panel's normal white background / black text."""

    def draw_bitmap(self, bitmap: bytes) -> None:
        """Replace the whole screen with a raw 1bpp bitmap already in this
        profile's logical width x height, row-major MSB-first layout (see
        rasterizer.py's module docstring for the exact convention) — for
        artwork that isn't text, e.g. firmware/splash.py's boot logo
        (firmware/hal/display/boot_logo.py). Optional: backends that only
        ever draw text (there are none today, but `draw_lines`-only mocks
        in tests are expected) can leave this raising NotImplementedError."""
        raise NotImplementedError(f"{type(self).__name__} does not support draw_bitmap()")

    def clear(self) -> None:
        self.draw_lines([])
