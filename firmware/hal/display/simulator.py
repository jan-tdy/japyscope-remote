"""Display backend for --simulate: no SPI, no e-ink. Prints the screen to
the terminal so the real firmware's state machine can be developed and
exercised on a laptop, well before hardware exists.
"""
from __future__ import annotations

import shutil

from .base import DisplayHAL


class SimulatorDisplay(DisplayHAL):
    def draw_lines(self, lines: list[str]) -> None:
        width = min(shutil.get_terminal_size((80, 24)).columns, self.profile.width // 6 or 40)
        print("\n" + "=" * width)
        print(f"[{self.profile.name} {self.profile.width}x{self.profile.height}]")
        for line in lines[: self.visible_rows]:
            print(line)
        print("=" * width)
