"""JapyScope controller entry point."""
from __future__ import annotations

import argparse
import logging
import signal
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
    def goto(self, ra: str, dec: str) -> None: self.status.ra = ra; self.status.dec = dec; self.status.tracking = True
    def park(self) -> None: self.status.parked = True
    def get_status(self) -> MountStatus: return self.status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JapyScope Remote hand controller")
    parser.add_argument("--simulate", action="store_true", help="use terminal display/input and no real INDI process")
    parser.add_argument("--db", help=f"SQLite path (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--driver", default=DEFAULT_DRIVER_BINARY, help="INDI mount driver executable")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
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
    input_hal = indi = manager = None

    def stop(_signum=None, _frame=None) -> None:
        if ui is not None:
            ui.running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with db_session(db_path) as conn:
            flags = resolve_simulation_flags(args.simulate, SettingsRepo(conn))
            display = make_display(flags["display"])
            input_hal = make_input(flags["keypad"], flags["encoder"])
            backlight = make_backlight(flags["backlight"])
            manager = None if flags["mount"] else IndiServerManager(driver_binary=args.driver)
            indi = SimulatedIndiClient() if flags["mount"] else IndiClient()
            if manager is not None:
                manager.start()
                connect_indi(indi)
            ui = ControllerUI(display, input_hal, indi, conn, backlight=backlight, indi_manager=manager)
            ui.run()
        return 0
    except (FileNotFoundError, ConnectionError) as exc:
        logging.getLogger(__name__).error("INDI-001/INDI-002 startup failed: %s", exc)
        return 1
    finally:
        if input_hal is not None:
            input_hal.close()
        if indi is not None:
            indi.disconnect()
        if manager is not None:
            manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
