from .base import InputHAL
from .composite import CompositeInput


def make_input(keypad_simulated: bool, encoder_simulated: bool) -> InputHAL:
    """Build the keypad and encoder sources independently, so one can be
    real GPIO while the other is still keyboard-simulated during bring-up
    (see shared.db's hw_sim_keypad/hw_sim_encoder). When both are the same
    kind, a single SimulatorInput is shared for both roles instead of
    spawning two terminal readers on the same stdin."""
    if keypad_simulated and encoder_simulated:
        from .simulator import SimulatorInput

        shared = SimulatorInput()
        return CompositeInput(shared, shared)

    if keypad_simulated:
        from .simulator import SimulatorInput

        keypad_source: InputHAL = SimulatorInput()
    else:
        from .keypad import KeypadInput

        keypad_source = KeypadInput()

    if encoder_simulated:
        from .simulator import SimulatorInput

        encoder_source: InputHAL = SimulatorInput()
    else:
        from .encoder import EncoderInput

        encoder_source = EncoderInput()

    return CompositeInput(keypad_source, encoder_source)


__all__ = ["InputHAL", "CompositeInput", "make_input"]
