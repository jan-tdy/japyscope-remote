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

Each key's raw level must stay unchanged for `_DEBOUNCE_S` before it's
trusted, and a key only emits once per press (on the stable not-pressed ->
pressed edge), not again on every scan while held — see encoder.py's
docstring for why a single-sample check (the previous approach here) reads
a brief noise glitch as a genuine press, which gets worse the longer a key
is physically held (each 20ms scan re-armed by the old time-based-only
debounce could fire again).

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
        # Per-key raw level + when it last changed, so a reading only counts
        # once it has held steady for _DEBOUNCE_S (see module docstring).
        now = time.monotonic()
        self._raw_pressed: dict[str, bool] = {key: False for row in KEY_LAYOUT for key in row}
        self._changed_at: dict[str, float] = {key: now for row in KEY_LAYOUT for key in row}
        self._active: dict[str, bool] = {key: False for row in KEY_LAYOUT for key in row}
        self._thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._thread.start()

    def _update_key(self, key: str, pressed: bool, now: float) -> None:
        if pressed != self._raw_pressed[key]:
            self._raw_pressed[key] = pressed
            self._changed_at[key] = now
            return
        if now - self._changed_at[key] < _DEBOUNCE_S:
            return
        if pressed and not self._active[key]:
            self._active[key] = True
            self._queue.put(key)
        elif not pressed:
            self._active[key] = False

    def _scan_matrix(self) -> None:
        GPIO = self._gpio
        now = time.monotonic()
        for row_idx, row_pin in enumerate(ROW_PINS):
            GPIO.output(row_pin, GPIO.LOW)
            for col_idx, col_pin in enumerate(COL_PINS):
                key = KEY_LAYOUT[row_idx][col_idx]
                self._update_key(key, GPIO.input(col_pin) == GPIO.LOW, now)
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
