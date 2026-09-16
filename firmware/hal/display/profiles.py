"""Display size/controller presets.

The panel is NOT finalized (see docs/ARCHITECTURE.md) — leaning 2.13" but
nothing bought yet, 4.26" not ruled out. Every part of the firmware that
draws to the screen must go through a DisplayProfile rather than assuming a
resolution, so switching panels later is a one-line config change.

Select via the JAPYSCOPE_DISPLAY_PROFILE env var (defaults to "2.13").
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


# Common Waveshare/GoodDisplay 2.13" monochrome e-paper module (SSD1680-family
# controller). Confirm the exact panel/controller once actually ordered.
PROFILE_2_13 = DisplayProfile(
    name="2.13in", width=250, height=122, controller="SSD1680", visible_rows=4
)

# The 4.26" panel shown in the original HTML mockup (Seeed/GoodDisplay
# GDEY0426T82, SSD1677 controller) — kept available in case EU stock
# situation changes.
PROFILE_4_26 = DisplayProfile(
    name="4.26in", width=800, height=480, controller="SSD1677", visible_rows=8
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
