"""Key codes shared by every input backend and by firmware/ui/. These match
the codes already used throughout the HTML mockup 1:1, so porting mockup
screen logic to Python is a direct translation.
"""
from __future__ import annotations

DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
BKSP = "BKSP"
FN2 = "FN2"
ENC_UP = "ENC_UP"
ENC_DOWN = "ENC_DOWN"
ENC_PUSH = "ENC_PUSH"

ALL_KEYS = [*DIGITS, BKSP, FN2, ENC_UP, ENC_DOWN, ENC_PUSH]
