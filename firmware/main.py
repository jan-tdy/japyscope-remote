"""JapyScope controller entry point."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Optional

from firmware.hal.backlight import make_backlight
from firmware.hal.display import make_display
from firmware.hal.input import make_input
from firmware.indi.client import IndiClient, MountStatus
from firmware.indi.manager import DEFAULT_DRIVER_BINARY, IndiServerManager
from firmware.ui import ControllerUI
from shared.db import DEFAULT_DB_PATH, HARDWARE_COMPONENTS, SettingsRepo, db_session


def _show_fatal_error(display, code: str, detail: str) -> None:
    """Best-effort: paint a maintainer code (docs/CODES.md) straight to the
    e-ink panel on a fatal failure, bypassing the DB-backed ControllerUI
    entirely. Deliberately still attempted when the failure IS the SD card
    going read-only: the panel's SPI writes are hardware I/O, independent
    of the filesystem, so this keeps working exactly when the DB doesn't —
    and e-ink holds the image with no power, so the code stays legible on
    an unattended device (Piconcillo) even through a crash-restart loop,
    until someone can reach it. Swallows its own failures: this only ever
    runs while already handling a worse one, and must never raise a new
    traceback over it."""
    if display is None:
        return
    try:
        display.draw_lines([code, detail[:24], "Check journalctl", "docs/TROUBLESHOOTING.md"])
    except Exception:
        logging.getLogger(__name__).exception("Could not paint %s to the display", code)


def _poweroff() -> None:
    """Real power-off (install.sh grants the `japyscope` user passwordless
    sudo for exactly this). `systemctl poweroff` only *queues* the shutdown
    and returns almost immediately (the actual teardown, including this
    process, happens moments later) — so unlike a true fire-and-forget
    action, there IS something worth confirming here: that `sudo` actually
    accepted and queued it. A bounded wait (not a real poweroff's full
    duration) catches e.g. a missing/stale sudoers grant immediately,
    instead of silently leaving the device sitting on the SHUTDOWN screen
    forever. Raises subprocess.SubprocessError (caught by
    ControllerUI._shutdown()'s existing handler, logged as SYS-990) on a
    nonzero exit or if it doesn't even start within the timeout."""
    subprocess.run(["/usr/bin/sudo", "systemctl", "poweroff"], check=True, timeout=10)


def resolve_simulation_flags(simulate_all: bool, settings: SettingsRepo) -> dict[str, bool]:
    if simulate_all:
        return {name: True for name in HARDWARE_COMPONENTS}
    return {name: settings.get(f"hw_sim_{name}", "0") == "1" for name in HARDWARE_COMPONENTS}


class SimulatedIndiClient:
    """No-motion INDI stand-in used only by ``--simulate``."""

    def __init__(self):
        self.status = MountStatus(True, "05h34m32s", "+22°00′52″", 47.3, 132.8, False, False, False)

    def connect(self) -> None: pass
    def disconnect(self) -> None: pass
    def sync(self, ra: str, dec: str) -> None: self.status.aligned = True; self.status.ra = ra; self.status.dec = dec
    def sync_alt_az(self, alt_deg: float, az_deg: float, latitude_deg: float, longitude_deg: float) -> None:
        self.status.aligned = True; self.status.alt = alt_deg; self.status.az = az_deg
    def goto(self, ra: str, dec: str) -> None: self.status.ra = ra; self.status.dec = dec; self.status.tracking = True
    def set_park_position(self, alt_deg: float, az_deg: float) -> None:
        self.status.alt = alt_deg; self.status.az = az_deg
    def park(self) -> None: self.status.parked = True
    def unpark(self) -> None: self.status.parked = False
    def abort(self) -> None: self.status.tracking = False
    def get_status(self) -> MountStatus: return self.status

    def jog(self, direction: str, speed: int) -> None:
        step = 0.01 * speed  # degrees per nudge — arbitrary, just visibly responsive at every SPEEDS tier
        if direction == "N": self.status.alt = min(90.0, self.status.alt + step)
        elif direction == "S": self.status.alt = max(-90.0, self.status.alt - step)
        elif direction == "E": self.status.az = (self.status.az + step) % 360
        elif direction == "W": self.status.az = (self.status.az - step) % 360

    def stop_jog(self, direction: str) -> None: pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JapyScope Remote hand controller")
    parser.add_argument("--simulate", action="store_true", help="use terminal display/input and no real INDI process")
    parser.add_argument("--db", help=f"SQLite path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--driver", default=DEFAULT_DRIVER_BINARY, help="INDI mount driver executable")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("JAPYSCOPE_LOG_LEVEL", "INFO"),
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Overridable via JAPYSCOPE_LOG_LEVEL (e.g. in /etc/japyscope/environment) without "
        "editing the systemd unit — set DEBUG to see per-transition encoder diagnostics "
        "(firmware.hal.input.encoder) or e-paper refresh phase timing (firmware.hal.display.epaper).",
    )
    return parser


def connect_indi(client: IndiClient, timeout: float = 15.0) -> None:
    """Wait for the just-spawned indiserver socket instead of racing it."""
    deadline = time.monotonic() + timeout
    last_error: Optional[ConnectionError] = None
    while time.monotonic() < deadline:
        try:
            client.connect()
            return
        except ConnectionError as exc:
            last_error = exc
            time.sleep(0.5)
    raise ConnectionError("indiserver did not accept a connection in time") from last_error


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    db_path = args.db or (str(Path.cwd() / "japyscope-sim.db") if args.simulate else DEFAULT_DB_PATH)
    ui = None
    display = None
    input_hal = indi = manager = None

    def stop(_signum=None, _frame=None) -> None:
        if ui is not None:
            ui.running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with db_session(db_path) as conn:
            settings = SettingsRepo(conn)
            flags = resolve_simulation_flags(args.simulate, settings)
            display = make_display(flags["display"])
            joystick_enabled = args.simulate or settings.get("joystick_enabled", "0") == "1"
            joystick_simulated = flags["joystick"] if joystick_enabled else None
            input_hal = make_input(flags["keypad"], flags["encoder"], joystick_simulated)
            backlight = make_backlight(flags["backlight"])
            manager = None if flags["mount"] else IndiServerManager(driver_binary=args.driver)
            indi = SimulatedIndiClient() if flags["mount"] else IndiClient(settings=settings)
            if manager is not None:
                manager.start()
                connect_indi(indi)
            ui = ControllerUI(
                display, input_hal, indi, conn, backlight=backlight, indi_manager=manager,
                power_control=None if args.simulate else _poweroff,
            )
            ui.run()
        return 0
    except (FileNotFoundError, ConnectionError) as exc:
        logging.getLogger(__name__).error("INDI-001/INDI-002 startup failed: %s", exc)
        return 1
    except (sqlite3.OperationalError, sqlite3.DatabaseError, OSError) as exc:
        # SYS-980 (docs/CODES.md): an OS/storage-level failure (confirmed
        # during real bring-up: a weak power supply or bad SD card can send
        # the filesystem read-only mid-run — see docs/TROUBLESHOOTING.md)
        # crashed the whole app. Broad on purpose — this is a last-resort
        # catch-all, not a specific diagnosis — so the real detail goes to
        # the journal and only a short, honest "something at the OS level
        # broke, go look" goes on the panel.
        logging.getLogger(__name__).error("SYS-980 OS/storage-level failure: %s", exc)
        _show_fatal_error(display, "SYS-980", str(exc))
        return 1
    except Exception as exc:
        # Catch-all for anything the two specific branches above don't name
        # (a bug in the UI/INDI code itself, not a startup or OS/storage
        # failure) — confirmed on hardware as a silent crash with nothing on
        # the panel to show for it. Deliberately the widest possible except:
        # this is the last line of defense, and an unattended device
        # (Piconcillo) left on a blank/stale screen after a crash is worse
        # than a wrong-but-honest code telling the owner to go check the
        # journal.
        logging.getLogger(__name__).exception("SYS-970 unhandled crash: %s", exc)
        _show_fatal_error(display, "SYS-970", str(exc))
        return 1
    finally:
        stop_motion = getattr(ui, "stop_motion", None)
        if stop_motion is not None:
            stop_motion()
        if input_hal is not None:
            input_hal.close()
        if indi is not None:
            indi.disconnect()
        if manager is not None:
            manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
