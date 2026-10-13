from typing import Optional

from .base import InputHAL
from .composite import CompositeInput


def make_input(
    keypad_simulated: bool,
    encoder_simulated: bool,
    joystick_simulated: Optional[bool] = None,
) -> InputHAL:
    """Build the keypad, encoder, and (optionally) joystick sources
    independently, so any of them can be real GPIO/I2C while the others are
    still keyboard-simulated during bring-up (see shared.db's
    hw_sim_keypad/hw_sim_encoder/hw_sim_joystick).

    joystick_simulated is None when the external joystick accessory isn't
    enabled at all (see shared.db's joystick_enabled) — no joystick source
    is built at all in that case, exactly as if this function had never
    heard of one. True/False behave like the other two roles: keyboard-
    simulated vs. real hardware (firmware/hal/input/joystick.py).

    Any roles that end up simulated together share a single SimulatorInput
    instance (one raw-stdin reader), regardless of how many of the three
    that is, instead of spawning multiple readers competing for the same
    terminal.
    """
    simulated_roles = keypad_simulated, encoder_simulated, joystick_simulated is True
    shared_simulator: Optional[InputHAL] = None
    if any(simulated_roles):
        from .simulator import SimulatorInput

        shared_simulator = SimulatorInput()

    if keypad_simulated:
        keypad_source: InputHAL = shared_simulator
    else:
        from .keypad import KeypadInput

        keypad_source = KeypadInput()

    if encoder_simulated:
        encoder_source: InputHAL = shared_simulator
    else:
        from .encoder import EncoderInput

        encoder_source = EncoderInput()

    joystick_source: Optional[InputHAL] = None
    if joystick_simulated is True:
        joystick_source = shared_simulator
    elif joystick_simulated is False:
        from .joystick import JoystickInput

        joystick_source = JoystickInput()

    return CompositeInput(keypad_source, encoder_source, joystick_source)


__all__ = ["InputHAL", "CompositeInput", "make_input"]
