from .base import DisplayHAL
from .profiles import PROFILE_2_13, PROFILE_4_26, DisplayProfile, get_active_profile


def make_display(simulate: bool) -> DisplayHAL:
    if simulate:
        from .simulator import SimulatorDisplay

        return SimulatorDisplay()
    from .epaper import EPaperDisplay

    return EPaperDisplay()


__all__ = [
    "DisplayHAL",
    "DisplayProfile",
    "PROFILE_2_13",
    "PROFILE_4_26",
    "get_active_profile",
    "make_display",
]
