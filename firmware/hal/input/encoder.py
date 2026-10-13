"""Real hardware input backend: the KY-040 rotary encoder only, on
Raspberry Pi Zero W GPIO. See keypad.py for the matrix keypad, wired up
independently (see shared.db's hw_sim_keypad/hw_sim_encoder settings).

Pin numbers below are placeholders — cross-check/update against
docs/WIRING.md, the single source of truth, once wiring is finalized.

Confirmed on physical hardware (Pi Zero W, after rewiring): a naive "emit
a step on every CLK edge" decoder double-counts, since one detent/click of
a KY-040 toggles CLK twice (high->low->high) — once per detent is wanted,
not twice. Decoding instead walks the full 2-bit (CLK, DT) Gray-code cycle
(00 -> 01 -> 11 -> 10 -> 00, or its reverse) and only emits a step once a
full 4-transition cycle completes, which is also what makes this immune to
contact bounce: a bounce just rocks back and forth between two adjacent
Gray-code states and nets to zero instead of free-running the accumulator.
Which direction (CW vs CCW) maps to ENC_UP vs ENC_DOWN is the one thing
that can't be confirmed without the physical panel in hand — flip
_CYCLE_FORWARD_IS_UP if a clockwise turn decreases instead of increases.

The push switch is debounced by requiring the raw level to stay unchanged
for `_DEBOUNCE_S` before it's trusted (instead of trusting any single
sample), and only emits once per press (on the stable low -> stable high
edge) rather than repeating every scan while held. This also rejects the
false "pressed" triggered by nothing more than a hand nearing the board —
a floating/weakly-pulled SW line picks that up as a brief induced dip,
which the old single-sample check accepted immediately but which never
holds the pin low long enough to pass this stability check. If this still
misfires with a hand nearby even after this fix, it means the line is
genuinely floating in the wiring (the Pi's internal pull-up is weak), and
wants a physical pull-up resistor (~10k ohm) or a small (~100nF) decoupling
capacitor between SW and GND — see docs/WIRING.md.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from .base import InputHAL
from .keys import ENC_DOWN, ENC_PUSH, ENC_UP

ENC_CLK_PIN = 16
ENC_DT_PIN = 12
ENC_SW_PIN = 7

_SCAN_INTERVAL_S = 0.02
_DEBOUNCE_S = 0.05

# Position of each 2-bit (CLK << 1 | DT) reading within one full Gray-code
# rotation cycle. Walking forward through this cycle (00 -> 01 -> 11 -> 10)
# is one direction of rotation; walking backward is the other. A reading
# that isn't one of these four (impossible on real hardware — CLK and DT
# can't both change between two consecutive 20ms-apart samples) can't
# happen here since the dict covers all 4 two-bit values.
_GRAY_CYCLE_POSITION = {0b00: 0, 0b01: 1, 0b11: 2, 0b10: 3}
_STEPS_PER_DETENT = 4
_CYCLE_FORWARD_IS_UP = True


class EncoderInput(InputHAL):
    def __init__(self):
        import RPi.GPIO as GPIO  # noqa: N814

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(ENC_CLK_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(ENC_DT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(ENC_SW_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._last_state = (GPIO.input(ENC_CLK_PIN) << 1) | GPIO.input(ENC_DT_PIN)
        self._detent_accum = 0
        self._sw_raw = GPIO.input(ENC_SW_PIN)
        self._sw_changed_at = time.monotonic()
        self._sw_pressed = False
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _scan_rotation(self) -> None:
        GPIO = self._gpio
        state = (GPIO.input(ENC_CLK_PIN) << 1) | GPIO.input(ENC_DT_PIN)
        if state == self._last_state:
            return
        prev_pos = _GRAY_CYCLE_POSITION[self._last_state]
        curr_pos = _GRAY_CYCLE_POSITION[state]
        self._last_state = state
        step = (curr_pos - prev_pos) % 4
        if step == 1:
            self._detent_accum += 1
        elif step == 3:
            self._detent_accum -= 1
        # step == 0 can't happen (state changed); step == 2 would mean both
        # CLK and DT flipped between samples, which a bounce can't do —
        # ignore it as noise rather than guess a direction.

        if self._detent_accum >= _STEPS_PER_DETENT:
            self._detent_accum = 0
            self._queue.put(ENC_UP if _CYCLE_FORWARD_IS_UP else ENC_DOWN)
        elif self._detent_accum <= -_STEPS_PER_DETENT:
            self._detent_accum = 0
            self._queue.put(ENC_DOWN if _CYCLE_FORWARD_IS_UP else ENC_UP)

    def _scan_switch(self) -> None:
        GPIO = self._gpio
        now = time.monotonic()
        level = GPIO.input(ENC_SW_PIN)
        if level != self._sw_raw:
            self._sw_raw = level
            self._sw_changed_at = now
            return
        if now - self._sw_changed_at < _DEBOUNCE_S:
            return
        if level == GPIO.LOW and not self._sw_pressed:
            self._sw_pressed = True
            self._queue.put(ENC_PUSH)
        elif level == GPIO.HIGH:
            self._sw_pressed = False

    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            self._scan_rotation()
            self._scan_switch()
            time.sleep(_SCAN_INTERVAL_S)

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        self._gpio.cleanup()
