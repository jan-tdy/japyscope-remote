"""Real hardware input backend: the KY-040 rotary encoder only, on
Raspberry Pi Zero W GPIO. See keypad.py for the matrix keypad, wired up
independently (see shared.db's hw_sim_keypad/hw_sim_encoder settings).

Pin numbers below are placeholders — cross-check/update against
docs/WIRING.md, the single source of truth, once wiring is finalized.

Confirmed on physical hardware (Pi Zero W, after rewiring): a naive "emit
a step on every CLK edge" decoder double-counts, since one detent/click of
a KY-040 toggles CLK twice (high->low->high) — once per detent is wanted,
not twice. Decoding instead walks the full 2-bit (CLK, DT) Gray-code cycle
(00 -> 01 -> 11 -> 10 -> 00, or its reverse), only counting a genuine,
validated transition (never a bare CLK wiggle with no matching DT change).

A first cut required 4 accumulated transitions per step (the textbook
"one full Gray-code cycle = one detent" rule) and turned out to need it:
confirmed on hardware as "turning the knob does nothing at all" — at the
time, with no stability debounce yet on rotation, a single stray reverse-
direction transition (contact bounce, a scan that's briefly too slow to
catch an intermediate state) actively canceled real progress rather than
just failing to add to it, since the accumulator never reset except at
the threshold — on real, noisy wiring the count could sit stuck near zero
indefinitely. Lowered to 2 (the common "half-step" compromise) to work
around that.

Once rotation got its own stability debounce (below) to reject that same
noise directly, the 2-per-detent compromise became actively wrong instead
of just a workaround: this particular KY-040 rests at the 0b11 state
between clicks and reliably produces the full 4-transition Gray cycle per
physical detent once noise is filtered, so counting every 2 transitions
as a step emits *two* menu moves per single physical click — confirmed
on hardware as "one click does nothing, two clicks moves way too much"
(an odd number of clicks leaves a stray half-counted transition sitting
in the accumulator; an even number emits double). Raised back to 4 (one
full cycle = one step) now that debounce, not this threshold, is what
rejects noise. Tunable via JAPYSCOPE_ENCODER_STEPS_PER_DETENT without a
firmware change if 4 isn't right for this particular encoder/wiring (try
2 if clicks are being missed outright, which would mean this encoder
*doesn't* reliably complete all 4 transitions after all).
Which direction (CW vs CCW) maps to ENC_UP vs ENC_DOWN is the one thing
that can't be confirmed without the physical panel in hand — flip
_CYCLE_FORWARD_IS_UP if a clockwise turn decreases instead of increases.

Still reported after the above: wildly inconsistent behavior, sometimes
nothing for a real turn, sometimes ~10 steps for 2 real ones. That pattern
— not just occasional bounce, but sometimes registering far more than
physically happened — points at genuine electrical noise on CLK/DT (the
same class of problem as the SW line's floating-pin issue below), not just
mechanical contact bounce: a validated Gray-code transition still fires
immediately off a single noisy sample, and enough random toggling can by
chance produce several valid-looking forward transitions in a row, which
is indistinguishable from real rotation to a decoder with no concept of
time. Rotation now gets the same stability debounce the switch already
had: a reading must stay the same for `JAPYSCOPE_ENCODER_STABLE_SAMPLES`
consecutive scans (about 10ms per step at the 5ms scan rate) before it's
trusted, filtering a brief noise glitch while staying well under the
tens-of-milliseconds a real detent takes.

Was briefly raised to 4 (~20ms) over "menu selection skipping 2 items for
1 step" — but that was reported while JAPYSCOPE_ENCODER_STEPS_PER_DETENT
was still stuck at 2, which (see above) was *itself* emitting two menu
moves per click at the time; the debounce value was never the problem
that symptom pointed at. With steps-per-detent fixed, DEBUG logging
(JAPYSCOPE_LOG_LEVEL=DEBUG) on real hardware caught 4 is actively too
high: of 5 consecutive physical clicks, 4 logged a direct 0b11<->0b00
jump (`step=+0`, discarded as an impossible same-scan double-bit flip)
and only 1 walked the full real 0b11->0b10->0b00->0b01->0b11 cycle and
registered. A ~20ms debounce requirement is *bridging over* the brief
real intermediate states on most clicks — by the time 4 consecutive
identical samples confirm a reading, the actual quadrature state has
already moved on, so only the before/after rest states ever get seen, 2
bits apart, which looks exactly like forbidden noise and gets thrown
away entirely. Lowered back to 2 (~10ms) to catch those states again;
raise it only if `step=+0` log lines keep appearing at 2 as well (push
toward 3-4 cautiously, expecting clicks to start getting dropped again
past the point this hardware's real transitions fit the window), lower
it to 1 if clicks are still being swallowed at 2. Both directions are one
`JAPYSCOPE_ENCODER_STABLE_SAMPLES` change in /etc/japyscope/environment
and a service restart, no firmware rebuild. This is a software mitigation
for what's ultimately a wiring/signal-quality and/or scan-rate problem,
not a full fix — the SW line's pull-up/decoupling-capacitor note below
applies equally to CLK/DT, and `_SCAN_INTERVAL_S` below is the other knob
if lowering this one isn't enough on its own (a narrower scan interval
raises the odds of ever sampling a brief intermediate state at all,
independent of how many consecutive samples are then required).

Separately, not a bug: rotating "up" from the first menu item (or "down"
from the last) wraps around to the other end — e.g. Time Sync (item 1) up
one notch lands on About (the last item), same as any circular menu.
That's `firmware/ui/controller.py`'s `_move()`, unrelated to this file.

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

import logging
import os
import queue
import threading
import time
from typing import Optional

from .base import InputHAL, key_tap
from .keys import ENC_DOWN, ENC_PUSH, ENC_UP

logger = logging.getLogger(__name__)

ENC_CLK_PIN = 16
ENC_DT_PIN = 12
ENC_SW_PIN = 7

# Fast enough that two genuine Gray-code transitions in quick succession
# (a real detent, on a none-too-clean breadboard signal) are very unlikely
# to both land in the same gap between scans — a slower rate here was the
# likely other half of "turning does nothing" (see module docstring).
_SCAN_INTERVAL_S = 0.005
_DEBOUNCE_S = 0.05

# Position of each 2-bit (CLK << 1 | DT) reading within one full Gray-code
# rotation cycle. Walking forward through this cycle (00 -> 01 -> 11 -> 10)
# is one direction of rotation; walking backward is the other. A reading
# that isn't one of these four (impossible on real hardware — CLK and DT
# can't both change between two consecutive samples) can't happen here
# since the dict covers all 4 two-bit values.
_GRAY_CYCLE_POSITION = {0b00: 0, 0b01: 1, 0b11: 2, 0b10: 3}


def _steps_per_detent() -> int:
    value = os.environ.get("JAPYSCOPE_ENCODER_STEPS_PER_DETENT", "")
    return int(value) if value.strip() else 4


def _stable_samples() -> int:
    value = os.environ.get("JAPYSCOPE_ENCODER_STABLE_SAMPLES", "")
    return max(1, int(value)) if value.strip() else 2


_STEPS_PER_DETENT = _steps_per_detent()
_STABLE_SAMPLES = _stable_samples()
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
        self._pending_state = self._last_state
        self._pending_count = _STABLE_SAMPLES
        self._detent_accum = 0
        self._sw_raw = GPIO.input(ENC_SW_PIN)
        self._sw_changed_at = time.monotonic()
        self._sw_pressed = False
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _scan_rotation(self) -> None:
        GPIO = self._gpio
        raw = (GPIO.input(ENC_CLK_PIN) << 1) | GPIO.input(ENC_DT_PIN)
        if raw != self._pending_state:
            self._pending_state = raw
            self._pending_count = 1
        elif self._pending_count < _STABLE_SAMPLES:
            self._pending_count += 1
        if self._pending_count < _STABLE_SAMPLES:
            return
        state = self._pending_state
        if state == self._last_state:
            return
        prev_state = self._last_state
        prev_pos = _GRAY_CYCLE_POSITION[prev_state]
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
        logger.debug(
            "encoder transition %s->%s step=%+d accum=%d/%d",
            f"{prev_state:02b}", f"{state:02b}", {1: 1, 3: -1}.get(step, 0),
            self._detent_accum, _STEPS_PER_DETENT,
        )

        if self._detent_accum >= _STEPS_PER_DETENT:
            self._detent_accum = 0
            emitted = ENC_UP if _CYCLE_FORWARD_IS_UP else ENC_DOWN
            logger.debug("encoder emits %s", emitted)
            self._queue.put(key_tap(emitted))
        elif self._detent_accum <= -_STEPS_PER_DETENT:
            self._detent_accum = 0
            emitted = ENC_DOWN if _CYCLE_FORWARD_IS_UP else ENC_UP
            logger.debug("encoder emits %s", emitted)
            self._queue.put(key_tap(emitted))

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
            if self._sw_pressed:
                self._queue.put(key_up(ENC_PUSH))
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
