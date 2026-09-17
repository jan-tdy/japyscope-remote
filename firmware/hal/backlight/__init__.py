from .base import BacklightHAL


def make_backlight(simulated: bool) -> BacklightHAL:
    if simulated:
        from .simulator import SimulatorBacklight

        return SimulatorBacklight()
    from .real import RealBacklight

    return RealBacklight()


__all__ = ["BacklightHAL", "make_backlight"]
