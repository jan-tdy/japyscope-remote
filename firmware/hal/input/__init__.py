from .base import InputHAL


def make_input(simulate: bool) -> InputHAL:
    if simulate:
        from .simulator import SimulatorInput

        return SimulatorInput()
    from .keypad import KeypadInput

    return KeypadInput()


__all__ = ["InputHAL", "make_input"]
