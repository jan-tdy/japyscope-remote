"""Display backend for --simulate: no SPI, no e-ink. Prints the screen to
the terminal so the real firmware's state machine can be developed and
exercised on a laptop, well before hardware exists.
"""
from __future__ import annotations

import re
import shutil
from typing import Optional

from .base import DisplayHAL


class SimulatorDisplay(DisplayHAL):
    _SENSITIVE_LINE_PATTERNS = (
        (re.compile(r"^Password:\s*.*$"), "Password: [REDACTED]"),
        (re.compile(r"^Lat\s+.*$"), "Lat [REDACTED]"),
        (re.compile(r"^Lon\s+.*$"), "Lon [REDACTED]"),
    )

    def _sanitize_line(self, line: str) -> str:
        for pattern, replacement in self._SENSITIVE_LINE_PATTERNS:
            if pattern.match(line):
                return replacement
        return line

    # ANSI reverse video (SGR 7): swaps foreground/background for whatever's
    # printed between the codes — the closest a terminal can get to the
    # e-ink panel's real black-background/white-text inversion.
    _REVERSE_VIDEO = "\x1b[7m"
    _RESET_VIDEO = "\x1b[0m"

    def draw_lines(self, lines: list[str], invert_row: Optional[int] = None) -> None:
        width = min(shutil.get_terminal_size((80, 24)).columns, self.profile.width // 6 or 40)
        sanitized_lines = [self._sanitize_line(line) for line in lines[: self.visible_rows]]
        print("\n" + "=" * width)
        print(f"[{self.profile.name} {self.profile.width}x{self.profile.height}]")
        for index, line in enumerate(sanitized_lines):
            if index == invert_row:
                print(f"{self._REVERSE_VIDEO}{line}{self._RESET_VIDEO}")
            else:
                print(line)
        print("=" * width)
