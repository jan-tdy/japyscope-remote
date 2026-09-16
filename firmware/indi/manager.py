"""Owns the indiserver subprocess (Ekos-style): the firmware app starts it,
health-checks it, restarts it on crash, and stops it on shutdown. The Web UI
never talks to INDI directly (no mount control in the Web UI, per the
mockup/plan) — it only reads state the firmware app writes to
shared.db.StateRepo.

Bullseye's armhf ``indi-bin`` package contains the default driver executable
used here. Its live property names still need validation against the mount.
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_INDISERVER_BIN = "indiserver"
DEFAULT_DRIVER_BINARY = "indi_skywatcherAltAzMount"
DEFAULT_PORT = 7624
RESTART_BACKOFF_S = 3.0
HEALTH_CHECK_INTERVAL_S = 5.0


class IndiServerManager:
    def __init__(
        self,
        driver_binary: str = DEFAULT_DRIVER_BINARY,
        indiserver_bin: str = DEFAULT_INDISERVER_BIN,
        port: int = DEFAULT_PORT,
        command: Optional[list[str]] = None,
    ):
        self.driver_binary = driver_binary
        self.indiserver_bin = indiserver_bin
        self.port = port
        # Overridable for tests, which swap in a harmless long-running
        # command instead of a real indiserver + mount driver.
        self._command = command or [self.indiserver_bin, "-v", "-p", str(self.port), self.driver_binary]
        self._process: Optional[subprocess.Popen] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            logger.info("Starting indiserver with driver %s", self.driver_binary)
            self._process = subprocess.Popen(
                self._command,
                stderr=subprocess.STDOUT,
            )
        if self._watchdog_thread is None:
            self._stop.clear()
            self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self._watchdog_thread.start()

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop(self) -> None:
        # Signal the watchdog first and always join it below — regardless of
        # whether a process happens to be running right now — so a stale
        # watchdog can never keep running (and spawning replacements)
        # alongside a later start()'s fresh one.
        self._stop.set()
        with self._lock:
            if self._process is not None:
                logger.info("Stopping indiserver")
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
                self._process = None
        if self._watchdog_thread is not None:
            self._watchdog_thread.join()
            self._watchdog_thread = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def _watchdog_loop(self) -> None:
        while not self._stop.wait(HEALTH_CHECK_INTERVAL_S):
            if self.is_running():
                continue
            logger.warning("indiserver exited unexpectedly, restarting")
            if self._stop.wait(RESTART_BACKOFF_S):
                return
            with self._lock:
                if self._stop.is_set():
                    return
                if self._process is not None and self._process.poll() is None:
                    continue  # a concurrent start()/restart() already replaced it
                self._process = subprocess.Popen(
                    self._command,
                    stderr=subprocess.STDOUT,
                )
