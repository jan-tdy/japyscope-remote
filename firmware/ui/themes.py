"""Interface themes for the hand controller's monochrome e-ink display.

The panel is black/white only, so every theme is too — they differ only in
how the *selected* row of a list/menu screen is marked. An `invert` theme
asks the display to swap that one row to black background / white text
(honored today by `SimulatorDisplay`'s reverse video; the real e-paper
rasterizer will honor `invert_row` once it exists — see
`firmware/hal/display/epaper.py`). Non-invert themes mark the row with text
alone (an arrow prefix, or brackets around it) so they work even before that
rasterizer is implemented.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

DEFAULT_THEME = "arrow"


@dataclass(frozen=True)
class UITheme:
    key: str
    label: str
    marker: str  # prefix for the selected row, when not inverting
    unmarked: str  # prefix for non-selected rows (kept the same width as `marker`)
    invert: bool = False  # ask the display to render the row in reverse video
    wrap: Optional[tuple[str, str]] = None  # (before, after) wrapped around the selected row's text


THEMES: tuple[UITheme, ...] = (
    UITheme(key="arrow", label="Arrow (> marker)", marker="> ", unmarked="  "),
    UITheme(key="invert", label="Invert (black bar)", marker="", unmarked="", invert=True),
    UITheme(key="brackets", label="Brackets ([ ])", marker="", unmarked="  ", wrap=("[", "]")),
)


def get_theme(key: str) -> UITheme:
    for theme in THEMES:
        if theme.key == key:
            return theme
    return THEMES[0]
