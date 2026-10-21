"""INDI client for the Sky-Watcher Alt-Az mount, talking to the
``indi_skywatcherAltAzMount`` driver (running under ``indiserver``, see
``firmware/indi/manager.py``) via the ``indi_setprop``/``indi_getprop``
command-line tools (part of the same ``indi-bin`` package as
``indiserver`` itself) rather than the ``PyIndi`` Python bindings --
discrete, one-shot commands (sync once, goto once, park once, a single
jog nudge) don't need a persistent event-driven client connection, and
this avoids depending on PyIndi's async property-discovery callbacks and
its API differences across versions. ``pyindi-client`` is still installed
(see ``install.sh``/``requirements-pyindi.lock``) but nothing in this
module uses it.

Every device/property/element name below is verified against the
driver's actual upstream source (``indilib/indi``,
``drivers/telescope/skywatcherAPIMount.cpp`` -- what the
``indi_skywatcherAltAzMount`` binary is built from -- plus the base
``INDI::Telescope``/``INDI::Connection::TCP`` classes it inherits from),
not guessed from naming convention:

- Device name: ``"Skywatcher Alt-Az"`` (``getDefaultName()``).
- ``EQUATORIAL_EOD_COORD`` (number): ``RA`` (decimal hours, 0-24),
  ``DEC`` (decimal degrees, -90..90).
- ``ON_COORD_SET`` (switch): ``SYNC`` to sync, ``TRACK`` to goto-and-
  then-track -- select this *before* sending new
  ``EQUATORIAL_EOD_COORD`` values; the driver reads which one is on
  when it receives them (``Telescope::ISNewNumber``, ``libs/indibase/
  inditelescope.cpp``). ``goto()`` deliberately selects ``TRACK``, not
  ``SLEW``: ``skywatcherAPIMount.cpp``'s own status-polling loop only
  starts tracking once the slew finishes *if* ``TRACK`` was selected --
  ``SLEW`` slews and then goes idle, which would silently leave the
  mount not tracking despite this project's UI calling that screen
  "TRACK".
- ``EQUATORIAL_EOD_COORD`` is epoch-of-date ("EOD"/JNow), not J2000 --
  this project's catalogs and alignment stars are J2000, so
  ``_ra_dec_to_indi()`` precesses them first (``shared/astro.py``'s
  ``precess_j2000_to_date()``); skipping this would mispoint by a
  fraction of a degree and grows every year.
- ``TELESCOPE_ABORT_MOTION`` (switch): ``ABORT``.
- ``TELESCOPE_PARK`` (switch): ``PARK``/``UNPARK``.
- ``TELESCOPE_MOTION_NS``/``TELESCOPE_MOTION_WE`` (switches):
  ``MOTION_NORTH``/``MOTION_SOUTH``, ``MOTION_WEST``/``MOTION_EAST``.
- ``TELESCOPE_SLEW_RATE`` (switch): numbered preset elements
  ``1x`` through ``9x``; the driver renames its final (800x) element
  to ``SLEW_MAX``. The UI exposes presets 1-8 and the maximum as preset 9.
- ``CONNECTION``/``CONNECTION_MODE``/``DEVICE_ADDRESS``: standard INDI
  properties, already used by ``firmware/ui/controller.py``'s
  ``_connect_mount_wifi()``.

Still worth a live sanity check against real hardware
(``indi_getprop -h localhost "Skywatcher Alt-Az.*"``) since a future
driver version could rename something -- but this is sourced, not
guessed.
"""
from __future__ import annotations

import logging
import socket
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Optional, Protocol

from shared import astro

logger = logging.getLogger(__name__)

class _SettingsLike(Protocol):
    def get(self, key: str, default: Optional[str] = None) -> Optional[str]: ...


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


def _format_ra(hours: float) -> str:
    hours %= 24
    h = int(hours)
    minutes = (hours - h) * 60
    m = int(minutes)
    s = (minutes - m) * 60
    return f"{h:02d}h{m:02d}m{s:04.1f}s"


def _format_dec(degrees: float) -> str:
    sign = "+" if degrees >= 0 else "-"
    degrees = abs(degrees)
    d = int(degrees)
    minutes = (degrees - d) * 60
    m = int(minutes)
    s = (minutes - m) * 60
    return f"{sign}{d:02d}°{m:02d}′{s:04.1f}″"


_JOG_PROPERTIES = {
    "N": ("TELESCOPE_MOTION_NS", "MOTION_NORTH"),
    "S": ("TELESCOPE_MOTION_NS", "MOTION_SOUTH"),
    "E": ("TELESCOPE_MOTION_WE", "MOTION_EAST"),
    "W": ("TELESCOPE_MOTION_WE", "MOTION_WEST"),
}

# UI presets are ordinal positions in the driver's switch vector. The
# final driver element is renamed from its numbered name to SLEW_MAX.
_SLEW_RATE_ELEMENTS = {
    **{preset: f"{preset}x" for preset in range(1, 9)},
    9: "SLEW_MAX",
}


class IndiClient:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 7624,
        device: str = "Skywatcher Alt-Az",
        settings: Optional[_SettingsLike] = None,
        clock: Callable[[], float] = time.time,
    ):
        self.host = host
        self.port = port
        self.device = device
        # Used only to turn the mount's RA/Dec into an alt/az for display
        # (the driver exposes no horizontal-coordinate property at all --
        # confirmed against its source) via shared/astro.py, the same
        # module ControllerUI already uses for catalog objects. Optional:
        # without it, get_status() just reports alt=az=0.0.
        self.settings = settings
        # Overridable for tests (deterministic precession/alt-az output);
        # real callers never need to pass this.
        self.clock = clock
        self._aligned = False

    def connect(self) -> None:
        # A plain TCP reachability check -- indi_setprop/indi_getprop
        # (used by every other method here) open and close their own
        # short-lived connection per call, so there's no persistent
        # client connection to hold open; this just confirms indiserver
        # is actually listening before firmware/main.py's connect_indi()
        # stops retrying.
        try:
            with socket.create_connection((self.host, self.port), timeout=3):
                pass
        except OSError as exc:
            raise ConnectionError(f"Could not connect to indiserver at {self.host}:{self.port}") from exc

    def disconnect(self) -> None:
        pass

    def _setprop(self, spec: str) -> None:
        try:
            subprocess.run(
                ["indi_setprop", "-h", self.host, "-p", str(self.port), f"{self.device}.{spec}"],
                capture_output=True, text=True, check=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectionError(f"indi_setprop {self.device}.{spec} failed: {exc}") from exc

    def _getprop(self, spec: str) -> str:
        try:
            result = subprocess.run(
                ["indi_getprop", "-1", "-h", self.host, "-p", str(self.port), f"{self.device}.{spec}"],
                capture_output=True, text=True, check=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectionError(f"indi_getprop {self.device}.{spec} failed: {exc}") from exc
        return result.stdout.strip()

    def get_status(self) -> Optional[MountStatus]:
        """Read the mount's current status. Returns None if not connected
        yet (e.g. indiserver just started and the driver hasn't reported in),
        or if any property read fails."""
        try:
            ra_hours = float(self._getprop("EQUATORIAL_EOD_COORD.RA"))
            dec_deg = float(self._getprop("EQUATORIAL_EOD_COORD.DEC"))
            connected = self._getprop("CONNECTION.CONNECT") == "On"
            tracking = self._getprop("TELESCOPE_TRACK_STATE.TRACK_ON") == "On"
            parked = self._getprop("TELESCOPE_PARK.PARK") == "On"
        except (ConnectionError, ValueError) as exc:
            logger.debug("INDI status read failed: %s", exc)
            return None

        alt = az = 0.0
        if self.settings is not None:
            try:
                latitude = float(self.settings.get("latitude", "0.0"))
                longitude = float(self.settings.get("longitude", "0.0"))
                now = self.clock()
                ra_deg = ra_hours * 15.0
                alt = astro.altitude_degrees(ra_deg, dec_deg, latitude, longitude, now)
                az = astro.azimuth_degrees(ra_deg, dec_deg, latitude, longitude, now)
            except (TypeError, ValueError) as exc:
                logger.debug("could not compute alt/az from INDI RA/Dec: %s", exc)

        return MountStatus(
            connected=connected, ra=_format_ra(ra_hours), dec=_format_dec(dec_deg),
            alt=alt, az=az, tracking=tracking, aligned=self._aligned, parked=parked,
        )

    def _ra_dec_to_indi(self, ra: str, dec: str) -> tuple[float, float]:
        """INDI's EQUATORIAL_EOD_COORD wants RA in decimal hours (0-24)
        and Dec in decimal degrees (-90..90), precessed to the equinox
        of date (not J2000, which is what this project's catalogs and
        alignment stars are stored in -- see the module docstring).
        ra/dec strings (sexagesimal with h/m/s or colons, or decimal
        degrees from an online SmartSearch/Sesame result) are parsed the
        same way shared/astro.py already does for catalog altitude."""
        ra_deg = astro.ra_to_degrees(ra)
        dec_deg = astro.dec_to_degrees(dec)
        if ra_deg is None or dec_deg is None:
            raise ConnectionError(f"could not parse RA/Dec for INDI: {ra!r}/{dec!r}")
        ra_deg, dec_deg = astro.precess_j2000_to_date(ra_deg, dec_deg, self.clock())
        return ra_deg / 15.0, dec_deg

    def sync(self, ra: str, dec: str) -> None:
        """INDI Sync: tell the mount 'you are currently pointed at ra/dec'
        without moving — used for the startup park-confirmation flow (see
        docs/ARCHITECTURE.md: 'No' -> sync) and manual alignment."""
        ra_hours, dec_deg = self._ra_dec_to_indi(ra, dec)
        self._setprop("ON_COORD_SET.SYNC=On")
        self._setprop(f"EQUATORIAL_EOD_COORD.RA={ra_hours:.6f};DEC={dec_deg:.6f}")
        self._aligned = True

    def goto(self, ra: str, dec: str) -> None:
        """TRACK, not SLEW -- see the module docstring: SLEW would leave
        the mount idle (not tracking) once it arrives."""
        ra_hours, dec_deg = self._ra_dec_to_indi(ra, dec)
        self._setprop("ON_COORD_SET.TRACK=On")
        self._setprop(f"EQUATORIAL_EOD_COORD.RA={ra_hours:.6f};DEC={dec_deg:.6f}")

    def abort(self) -> None:
        self._setprop("TELESCOPE_ABORT_MOTION.ABORT=On")

    def park(self) -> None:
        """Only issues the park command -- on real hardware the driver's
        Park() starts an asynchronous slew to the park position, so this
        returns long before the mount has actually finished moving.
        Callers must poll get_status().parked for real completion rather
        than assuming success (see ControllerUI._poll_parking())."""
        self._setprop("TELESCOPE_PARK.PARK=On")

    def unpark(self) -> None:
        self._setprop("TELESCOPE_PARK.UNPARK=On")

    def jog(self, direction: str, speed: int) -> None:
        """Start continuous motion in one SynScan direction until stop_jog()."""
        jog_property = _JOG_PROPERTIES.get(direction)
        if jog_property is None:
            raise ConnectionError(f"unknown jog direction: {direction!r}")
        rate_element = _SLEW_RATE_ELEMENTS.get(speed)
        if rate_element is None:
            raise ConnectionError(f"unknown jog speed preset: {speed!r}")
        axis_property, on_element = jog_property
        self._setprop(f"TELESCOPE_SLEW_RATE.{rate_element}=On")
        self._setprop(f"{axis_property}.{on_element}=On")

    def stop_jog(self, direction: str) -> None:
        jog_property = _JOG_PROPERTIES.get(direction)
        if jog_property is None:
            raise ConnectionError(f"unknown jog direction: {direction!r}")
        axis_property, on_element = jog_property
        self._setprop(f"{axis_property}.{on_element}=Off")
