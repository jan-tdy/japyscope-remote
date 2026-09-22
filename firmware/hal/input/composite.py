"""Merges up to three independent input sources — keypad, KY-040 rotary
encoder, and an optional external joystick — into the single InputHAL
stream firmware/ui/ consumes. Lets each be real or simulated on its own
during hardware bring-up (see shared.db's hw_sim_keypad/hw_sim_encoder/
hw_sim_joystick), rather than only supporting an all-or-nothing --simulate.

joystick_source is optional (None) because, unlike the keypad and encoder,
the joystick is an external accessory that may not be connected at all (see
shared.db's joystick_enabled and firmware/hal/input/joystick.py) — when it's
None, this behaves exactly as it did before the joystick existed.
"""
from __future__ import annotations

from typing import Optional

from .base import InputHAL
from .keys import is_encoder_key, is_joystick_key, is_keypad_key


class CompositeInput(InputHAL):
    def __init__(
        self,
        keypad_source: InputHAL,
        encoder_source: InputHAL,
        joystick_source: Optional[InputHAL] = None,
    ):
        self._keypad_source = keypad_source
        self._encoder_source = encoder_source
        self._joystick_source = joystick_source
        # Predates the joystick and kept as its own attribute (rather than
        # inferred from _groups below) since tests introspect it directly.
        self._same_source = keypad_source is encoder_source

        # Group the declared roles by the actual object backing them, so a
        # source shared across roles (e.g. one SimulatorInput acting as
        # keypad+encoder+joystick together under --simulate) is polled once
        # per poll() call and accepted for any of its roles, instead of
        # splitting one timeout budget across duplicate polls of the same
        # object.
        roles = [(keypad_source, is_keypad_key), (encoder_source, is_encoder_key)]
        if joystick_source is not None:
            roles.append((joystick_source, is_joystick_key))
        self._groups: list[tuple[InputHAL, list]] = []
        for source, predicate in roles:
            for existing_source, predicates in self._groups:
                if existing_source is source:
                    predicates.append(predicate)
                    break
            else:
                self._groups.append((source, [predicate]))

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        if len(self._groups) == 1:
            return self._groups[0][0].poll(timeout)
        budget = max(timeout / len(self._groups), 0.01)
        for source, predicates in self._groups:
            key = source.poll(budget)
            if key is not None and any(predicate(key) for predicate in predicates):
                return key
        return None

    def close(self) -> None:
        for source, _ in self._groups:
            source.close()
