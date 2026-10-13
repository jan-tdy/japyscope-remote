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
        """Replace the whole screen with these text lines (partial-refresh
        e-ink, so this is the only drawing primitive v0 needs — no
        incremental diffing). `invert_row`, if given, is the index into
        `lines` of the one row an "Invert" interface theme
        (`firmware/ui/themes.py`) wants shown as black background / white
        text instead of the panel's normal white background / black text."""

    def clear(self) -> None:
        self.draw_lines([])
