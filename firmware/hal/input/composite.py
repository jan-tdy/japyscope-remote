"""Merges an independent keypad source and encoder source into the single
InputHAL stream firmware/ui/ consumes — lets each be real or simulated on
its own during hardware bring-up (see shared.db's hw_sim_keypad/
hw_sim_encoder), rather than only supporting an all-or-nothing --simulate.
"""
from __future__ import annotations

from typing import Optional

from .base import InputHAL
from .keys import is_encoder_key, is_keypad_key


class CompositeInput(InputHAL):
    def __init__(self, keypad_source: InputHAL, encoder_source: InputHAL):
        self._keypad_source = keypad_source
        self._encoder_source = encoder_source
        # Common case (both real or both simulated with the same backend
        # instance, e.g. one shared SimulatorInput acting as both roles):
        # poll it once, unfiltered, instead of splitting one timeout budget
        # across two calls to the same object.
        self._same_source = keypad_source is encoder_source

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        if self._same_source:
            return self._keypad_source.poll(timeout)
        half = max(timeout / 2, 0.01)
        key = self._keypad_source.poll(half)
        if key is not None and is_keypad_key(key):
            return key
        key = self._encoder_source.poll(half)
        if key is not None and is_encoder_key(key):
            return key
        return None

    def close(self) -> None:
        self._keypad_source.close()
        if not self._same_source:
            self._encoder_source.close()
