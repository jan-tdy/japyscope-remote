"""Backlight backend for --simulate / hw_sim_backlight: just prints, no GPIO."""
from __future__ import annotations

from .base import BacklightHAL


class SimulatorBacklight(BacklightHAL):
    def set(self, r: int, g: int, b: int) -> None:
        print(f"(backlight R={r} G={g} B={b})")
