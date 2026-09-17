"""Real hardware input backend: the 3x4 matrix keypad only (stock SparkFun
COM-14662, stickers only — see docs/WIRING.md for physical key legend), on
Raspberry Pi Zero W GPIO. The KY-040 rotary encoder is a separate device on
separate pins — see encoder.py — since the two are wired up independently
during bring-up (see shared.db's hw_sim_keypad/hw_sim_encoder settings).

Pin numbers below are placeholders — cross-check/update against
docs/WIRING.md, the single source of truth, once wiring is finalized.
Matrix scanning is a standard technique and doesn't depend on that
confirmation, so it's implemented for real (not stubbed) even though this
has not been tested against physical hardware yet.

Note: RPi.GPIO's setmode()/cleanup() are process-global. If both this class
and encoder.py's EncoderInput are constructed together (both real), each
calls GPIO.setmode(GPIO.BCM) — harmless, same mode both times — but
GPIO.cleanup() with no arguments resets every channel, not just this
instance's own pins. Not a practical problem today since both are always
closed together at shutdown, but worth knowing before changing that.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from .base import InputHAL
from .keys import BKSP, FN2

# 3x4 matrix: rows/cols in BCM numbering — confirm against docs/WIRING.md.
ROW_PINS = [5, 6, 13, 19]
COL_PINS = [26, 20, 21]
# Physical legend (see docs/CODES.md / mockup Key Map): row-major, 3 cols x 4 rows.
KEY_LAYOUT = [
    ["1", "2", "3"],
    ["4", "5", "6"],
    ["7", "8", "9"],
    [FN2, "0", BKSP],
]

_SCAN_INTERVAL_S = 0.02
_DEBOUNCE_S = 0.05


class KeypadInput(InputHAL):
    def __init__(self):
        import RPi.GPIO as GPIO  # noqa: N814

        self._gpio = GPIO
        GPIO.setmode(GPIO.BCM)
        for pin in ROW_PINS:
            GPIO.setup(pin, GPIO.OUT)
            GPIO.output(pin, GPIO.HIGH)
        for pin in COL_PINS:
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._last_key_time: dict[str, float] = {}
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _debounced_emit(self, key: str) -> None:
        now = time.monotonic()
        if now - self._last_key_time.get(key, 0.0) < _DEBOUNCE_S:
            return
        self._last_key_time[key] = now
        self._queue.put(key)

    def _scan_matrix(self) -> None:
        GPIO = self._gpio
        for row_pin in ROW_PINS:
            GPIO.output(row_pin, GPIO.LOW)
            for col_idx, col_pin in enumerate(COL_PINS):
                if GPIO.input(col_pin) == GPIO.LOW:
                    row_idx = ROW_PINS.index(row_pin)
                    self._debounced_emit(KEY_LAYOUT[row_idx][col_idx])
            GPIO.output(row_pin, GPIO.HIGH)

    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            self._scan_matrix()
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
