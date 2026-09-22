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
# External joystick module (see firmware/hal/input/joystick.py, optional —
# shared.db's joystick_enabled). Its Y-axis and push button are a drop-in
# alternative to the KY-040 rotary encoder and reuse ENC_UP/ENC_DOWN/
# ENC_PUSH directly (see JOYSTICK_KEYS below) rather than getting their own
# codes; only its X-axis needs new codes, since no other device has one.
JOY_LEFT = "JOY_LEFT"
JOY_RIGHT = "JOY_RIGHT"

ALL_KEYS = [*DIGITS, BKSP, FN2, ENC_UP, ENC_DOWN, ENC_PUSH, JOY_LEFT, JOY_RIGHT]

# Which physical device produces each code — used by CompositeInput to route
# events correctly when the keypad, encoder, and joystick are independently
# real/simulated (see docs/WIRING.md: they're wired up separately, at
# different points in bring-up).
KEYPAD_KEYS = frozenset({*DIGITS, BKSP, FN2})
ENCODER_KEYS = frozenset({ENC_UP, ENC_DOWN, ENC_PUSH})
JOYSTICK_KEYS = ENCODER_KEYS | frozenset({JOY_LEFT, JOY_RIGHT})


def is_keypad_key(key: str) -> bool:
    return key in KEYPAD_KEYS


def is_encoder_key(key: str) -> bool:
    return key in ENCODER_KEYS


def is_joystick_key(key: str) -> bool:
    return key in JOYSTICK_KEYS
