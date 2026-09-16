"""Keyboard-driven input backend for --simulate, mirroring the HTML mockup's
own keyboard shortcuts exactly: 1-9/0 = digits, Enter = encoder push,
Up/Down = encoder rotate, Backspace = BKSP, F = FN2.

Uses a background thread reading raw (cbreak) stdin so keys are consumed the
instant they're pressed, no Enter-to-submit line buffering — same feel as a
real keypad.
"""
from __future__ import annotations

import queue
import select
import sys
import termios
import threading
import tty
from typing import Optional

from .base import InputHAL
from .keys import BKSP, DIGITS, ENC_DOWN, ENC_PUSH, FN2

_ESCAPE_UP = "\x1b[A"
_ESCAPE_DOWN = "\x1b[B"
_POLL_TIMEOUT_S = 0.2
_ESCAPE_FOLLOWUP_TIMEOUT_S = 0.01


class SimulatorInput(InputHAL):
    def __init__(self):
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._fd = sys.stdin.fileno()
        self._old_settings = None
        try:
            self._old_settings = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except (termios.error, ValueError):
            self._old_settings = None  # not a real TTY (e.g. piped input in tests)
        self._thread.start()

    def _read_loop(self) -> None:
        # Poll with a timeout instead of a blocking read() so close() can
        # signal _stop and have this thread actually notice and exit,
        # rather than sitting blocked until one more key is pressed.
        while not self._stop.is_set():
            ready, _, _ = select.select([self._fd], [], [], _POLL_TIMEOUT_S)
            if not ready:
                continue
            ch = sys.stdin.read(1)
            if not ch:
                return
            if ch == "\x1b":
                # Only consume the rest of an arrow-key sequence if it's
                # actually arriving as a burst — a lone Escape press must
                # not block waiting for two bytes that will never come.
                more_ready, _, _ = select.select([self._fd], [], [], _ESCAPE_FOLLOWUP_TIMEOUT_S)
                if more_ready:
                    ch += sys.stdin.read(2)
            key = self._translate(ch)
            if key is not None:
                self._queue.put(key)

    @staticmethod
    def _translate(ch: str) -> Optional[str]:
        if ch in DIGITS:
            return ch
        if ch in ("\r", "\n"):
            return ENC_PUSH
        if ch in ("\x7f", "\x08"):
            return BKSP
        if ch in ("f", "F"):
            return FN2
        if ch == _ESCAPE_UP:
            return "ENC_UP"
        if ch == _ESCAPE_DOWN:
            return ENC_DOWN
        return None

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        try:
            key = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        return key

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=_POLL_TIMEOUT_S * 2)
        if self._old_settings is not None:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old_settings)
