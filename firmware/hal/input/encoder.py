"""Real hardware input backend: the KY-040 rotary encoder only, on
Raspberry Pi Zero W GPIO. See keypad.py for the matrix keypad, wired up
independently (see shared.db's hw_sim_keypad/hw_sim_encoder settings).

Pin numbers below are placeholders — cross-check/update against
docs/WIRING.md, the single source of truth, once wiring is finalized.
Quadrature decoding is a standard technique and doesn't depend on that
confirmation, so it's implemented for real (not stubbed) even though this
has not been tested against physical hardware yet.
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
        self._last_clk = GPIO.input(ENC_CLK_PIN)
        self._last_key_time: dict[str, float] = {}
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _debounced_emit(self, key: str) -> None:
        now = time.monotonic()
        if now - self._last_key_time.get(key, 0.0) < _DEBOUNCE_S:
            return
        self._last_key_time[key] = now
        self._queue.put(key)

    def _scan_encoder(self) -> None:
        GPIO = self._gpio
        clk = GPIO.input(ENC_CLK_PIN)
        if clk != self._last_clk:
            direction = ENC_DOWN if GPIO.input(ENC_DT_PIN) != clk else ENC_UP
            self._debounced_emit(direction)
        self._last_clk = clk
        if GPIO.input(ENC_SW_PIN) == GPIO.LOW:
            self._debounced_emit(ENC_PUSH)

    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            self._scan_encoder()
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
