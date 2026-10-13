"""Display backend for --simulate: no SPI, no e-ink. Prints the screen to
the terminal so the real firmware's state machine can be developed and
exercised on a laptop, well before hardware exists.
"""
from __future__ import annotations

import re
import shutil
from typing import Optional

from .base import DisplayHAL
from .rasterizer import stride_for


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
                # Pad to the full row width so the reverse video reads as a
                # bar across the row, not just an inverted word.
                print(f"{self._REVERSE_VIDEO}{line.ljust(width)}{self._RESET_VIDEO}")
            else:
                print(line)
        print("=" * width)

    def draw_bitmap(self, bitmap: bytes) -> None:
        # Downsampled ASCII-art preview, nearest-neighbor per terminal cell
        # (rows get half the columns' sample density — terminal character
        # cells are roughly twice as tall as wide) — not pixel-perfect, just
        # enough for a developer running --simulate to confirm artwork
        # (e.g. boot_logo.py) landed roughly where intended.
        src_width, src_height = self.profile.width, self.profile.height
        stride = stride_for(src_width)
        cols = min(shutil.get_terminal_size((80, 24)).columns, src_width)
        rows = max(1, round(src_height * (cols / src_width) / 2))
        print("\n" + "=" * cols)
        print(f"[{self.profile.name} {src_width}x{src_height} bitmap]")
        for row in range(rows):
            src_y = min(src_height - 1, row * src_height // rows)
            chars = []
            for col in range(cols):
                src_x = min(src_width - 1, col * src_width // cols)
                is_white = (bitmap[src_y * stride + src_x // 8] >> (7 - (src_x % 8))) & 1
                chars.append(" " if is_white else "█")
            print("".join(chars))
        print("=" * cols)
