"""Input HAL interface: a 3x4 matrix keypad + a KY-040 rotary encoder,
reduced to the single event stream firmware/ui/ consumes (see keys.py).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

KEY_UP_PREFIX = "KEY_UP:"
KEY_TAP_PREFIX = "KEY_TAP:"


def key_up(key: str) -> str:
    """Encode release of a physical key in the poll() event stream."""
    return KEY_UP_PREFIX + key


def released_key(event: str) -> Optional[str]:
    return event[len(KEY_UP_PREFIX):] if event.startswith(KEY_UP_PREFIX) else None


def key_tap(key: str) -> str:
    """Encode a momentary detent event in the poll() event stream."""
    return KEY_TAP_PREFIX + key


def tapped_key(event: str) -> Optional[str]:
    return event[len(KEY_TAP_PREFIX):] if event.startswith(KEY_TAP_PREFIX) else None


class InputHAL(ABC):
    @abstractmethod
    def poll(self, timeout: float = 0.1) -> Optional[str]:
        """Return the next key code (see keys.ALL_KEYS) within `timeout`
        seconds, or None if no event arrived. Backends may return
        ``key_up(code)`` when a previously pressed physical key is released."""

    def close(self) -> None:
        pass
