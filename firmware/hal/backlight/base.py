"""Backlight HAL interface — separate from DisplayHAL because the custom
JapySoft RGB edge-lighting is physically independent wiring (its own GPIO
pins, not the display's SPI bus) that can be wired up on its own schedule
during bring-up. See shared.db's hw_sim_display/hw_sim_backlight settings.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BacklightHAL(ABC):
    @abstractmethod
    def set(self, r: int, g: int, b: int) -> None:
        """r/g/b are levels 0..2 (Off/Med/High), matching the mockup's
        Backlight menu — real HW mixes these via edge-mounted RGB LEDs."""
