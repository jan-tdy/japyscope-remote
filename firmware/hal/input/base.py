"""Input HAL interface: a 3x4 matrix keypad + a KY-040 rotary encoder,
reduced to the single event stream firmware/ui/ consumes (see keys.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class InputHAL(ABC):
    @abstractmethod
    def poll(self, timeout: float = 0.1) -> Optional[str]:
        """Return the next key code (see keys.ALL_KEYS) within `timeout`
        seconds, or None if nothing was pressed."""

    def close(self) -> None:
        pass
