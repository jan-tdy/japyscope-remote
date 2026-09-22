import os
import tempfile

from firmware.main import HARDWARE_COMPONENTS, resolve_simulation_flags
from shared.db import SettingsRepo, connect, init_db


def make_settings():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = connect(path); init_db(conn)
    return SettingsRepo(conn), conn, path


def test_simulate_all_forces_every_component():
    settings, conn, path = make_settings()
    try:
        flags = resolve_simulation_flags(True, settings)
        assert flags == {name: True for name in HARDWARE_COMPONENTS}
    finally: conn.close(); os.unlink(path)


def test_defaults_are_all_real_when_not_simulating():
    settings, conn, path = make_settings()
    try:
        flags = resolve_simulation_flags(False, settings)
        assert flags == {name: False for name in HARDWARE_COMPONENTS}
    finally: conn.close(); os.unlink(path)


def test_per_component_overrides_are_independent():
    settings, conn, path = make_settings()
    try:
        settings.set("hw_sim_encoder", "1")
        settings.set("hw_sim_mount", "1")
        flags = resolve_simulation_flags(False, settings)
        assert flags == {
            "keypad": False, "encoder": True,
            "display": False, "backlight": False,
            "mount": True, "joystick": False,
        }
    finally: conn.close(); os.unlink(path)
