"""Real hardware input backend: the KY-040 rotary encoder only, on
Raspberry Pi Zero W GPIO. See keypad.py for the matrix keypad, wired up
independently (see shared.db's hw_sim_keypad/hw_sim_encoder settings).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from typing import Optional

from .base import InputHAL, key_tap, key_up
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
