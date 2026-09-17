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
    def draw_lines(self, lines: list[str]) -> None:
        """Replace the whole screen with these text lines (partial-refresh
        e-ink, so this is the only drawing primitive v0 needs — no
        incremental diffing)."""

    def clear(self) -> None:
        self.draw_lines([])
