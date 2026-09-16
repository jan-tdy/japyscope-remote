"""Display HAL interface. Every screen in firmware/ui/ renders through this,
never through a concrete driver — so --simulate can swap in a backend with
no SPI/e-ink hardware present.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .profiles import DisplayProfile, get_active_profile


class DisplayHAL(ABC):
    def __init__(self, profile: DisplayProfile | None = None):
        self.profile = profile or get_active_profile()

    @property
    def visible_rows(self) -> int:
        return self.profile.visible_rows

    @abstractmethod
    def draw_lines(self, lines: list[str]) -> None:
        """Replace the whole screen with these text lines (partial-refresh
        e-ink, so this is the only drawing primitive v0 needs — no
        incremental diffing)."""

    @abstractmethod
    def set_backlight(self, r: int, g: int, b: int) -> None:
        """r/g/b are levels 0..2 (Off/Med/High), matching the mockup's
        Backlight menu — real HW mixes these via edge-mounted RGB LEDs."""

    def clear(self) -> None:
        self.draw_lines([])
