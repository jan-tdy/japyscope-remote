"""Thin INDI client wrapper around PyIndi-client (LGPL — see
docs/ARCHITECTURE.md licensing note; used as a runtime dependency, not
linked into this MIT-licensed codebase). Import is lazy so nothing outside
this module requires pyindi-client to be installed — --simulate and the
Web UI never import this.

Deliberately minimal for v0: the handful of operations the mockup's screens
actually need (status readout, sync, goto, park). Extend as real hardware
bring-up (Fáza 1beta) reveals what's missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MountStatus:
    connected: bool
    ra: str
    dec: str
    alt: float
    az: float
    tracking: bool
    aligned: bool
    parked: bool


class IndiClient:
    def __init__(self, host: str = "localhost", port: int = 7624):
        self.host = host
        self.port = port
        self._client = None

    def connect(self) -> None:
        import PyIndi  # noqa: PLC0415

        class _Client(PyIndi.BaseClient):
            pass

        self._client = _Client()
        self._client.setServer(self.host, self.port)
        if not self._client.connectServer():
            raise ConnectionError(f"Could not connect to indiserver at {self.host}:{self.port}")

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.disconnectServer()
            self._client = None

    def get_status(self) -> Optional[MountStatus]:
        """Read the mount's current status. Returns None if not connected
        yet (e.g. indiserver just started and the driver hasn't reported in)."""
        raise NotImplementedError(
            "Wire up against the actual Sky-Watcher Alt-Az driver's INDI "
            "properties once hardware exists — property names/format need "
            "confirming against a live driver session."
        )

    def sync(self, ra: str, dec: str) -> None:
        """INDI Sync: tell the mount 'you are currently pointed at ra/dec'
        without moving — used for the startup park-confirmation flow (see
        docs/ARCHITECTURE.md: 'No' -> sync) and manual alignment."""
        raise NotImplementedError("See get_status() — same reason.")

    def goto(self, ra: str, dec: str) -> None:
        raise NotImplementedError("See get_status() — same reason.")

    def park(self) -> None:
        raise NotImplementedError("See get_status() — same reason.")
