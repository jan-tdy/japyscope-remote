"""OLD REAL BACKLIGHT BACKEND. TODO: REDO FOR OLED
"""
from __future__ import annotations

from .base import BacklightHAL


class RealBacklight(BacklightHAL):
    def __init__(self):
        self._pwm = None

    def set(self, r: int, g: int, b: int) -> None:
        raise NotImplementedError(
            "Custom JapySoft RGB edge-lighting: plain GPIO drive, one 5mm "
            "LED + series resistor per channel (no MOSFET, no driver IC), "
            "Off/Med/High via software PWM. Exact GPIO pins not yet assigned "
            "— see docs/WIRING.md's Backlight section, update both once wired."
        )
