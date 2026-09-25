"""Display size/controller presets.

The panel is confirmed as 2.13" (see docs/ARCHITECTURE.md — settled once the
enclosure CAD, sized around a 2.13" module, existed). Every part of the
firmware that draws to the screen must still go through a DisplayProfile
rather than assuming a resolution, so switching panels later stays a
one-line config change; 4.26" is kept available for that reason.

Select via the JAPYSCOPE_DISPLAY_PROFILE env var (defaults to "2.13in").
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DisplayProfile:
    name: str
    width: int
    height: int
    controller: str
    visible_rows: int  # how many text lines comfortably fit at the chosen font size
    # The controller's own RAM source-axis (X) / gate-axis (Y) pixel counts.
    # Equal to width/height when the firmware's logical canvas already
    # matches the panel's native orientation; swapped when it doesn't (see
    # PROFILE_2_13) — epaper.py rotates the rendered bitmap 90 degrees at
    # the SPI-write boundary in that case, since RAM addressing must stay
    # within the controller's real source/gate limits regardless of how the
    # firmware wants to draw.
    native_width: int
    native_height: int


# Common Waveshare/GoodDisplay 2.13" monochrome e-paper module (SSD1680-family
# controller) — the confirmed panel. Confirm the exact part number/controller
# once actually ordered against the enclosure's screen cutout. Its native RAM
# is portrait — 122 source-axis x 250 gate-axis pixels (SSD1680's source axis
# maxes out at 176, so the 250px-wide landscape canvas below cannot be
# written directly along X) — while the firmware draws a 250x122 landscape
# canvas so 4 lines of text read comfortably; epaper.py rotates between the
# two at the SPI-write boundary.
PROFILE_2_13 = DisplayProfile(
    name="2.13in", width=250, height=122, controller="SSD1680", visible_rows=4,
    native_width=122, native_height=250,
)

# The 4.26" panel shown in the original HTML mockup (Seeed/GoodDisplay
# GDEY0426T82, SSD1677 controller) — kept available in case EU stock
# situation changes. Native landscape already (no rotation needed): SSD1677
# supports up to 960 source-axis / 680 gate-axis pixels, comfortably
# covering 800x480 directly.
PROFILE_4_26 = DisplayProfile(
    name="4.26in", width=800, height=480, controller="SSD1677", visible_rows=8,
    native_width=800, native_height=480,
)

PROFILES = {p.name: p for p in (PROFILE_2_13, PROFILE_4_26)}


def get_active_profile() -> DisplayProfile:
    name = os.environ.get("JAPYSCOPE_DISPLAY_PROFILE", PROFILE_2_13.name)
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown JAPYSCOPE_DISPLAY_PROFILE={name!r}, expected one of {list(PROFILES)}"
        ) from exc
