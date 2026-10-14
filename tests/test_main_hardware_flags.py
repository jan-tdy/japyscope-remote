import os
import sqlite3
import tempfile

from firmware import main as main_module
from firmware.main import HARDWARE_COMPONENTS, build_parser, resolve_simulation_flags
from firmware.hal.display.profiles import PROFILE_2_13
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


def test_log_level_defaults_to_info_overridable_via_env(monkeypatch):
    # JAPYSCOPE_LOG_LEVEL lets DEBUG (per-transition encoder diagnostics,
    # e-paper refresh phase timing) be enabled via /etc/japyscope/environment
    # without editing the systemd unit's ExecStart.
    monkeypatch.delenv("JAPYSCOPE_LOG_LEVEL", raising=False)
    assert build_parser().parse_args([]).log_level == "INFO"
    monkeypatch.setenv("JAPYSCOPE_LOG_LEVEL", "DEBUG")
    assert build_parser().parse_args([]).log_level == "DEBUG"


class _RecordingDisplay:
    profile = PROFILE_2_13
    visible_rows = PROFILE_2_13.visible_rows

    def __init__(self):
        self.lines = None

    def draw_lines(self, lines, invert_row=None, partial=False):
        self.lines = lines


class _ControllerUIThatRaises:
    """Stands in for ControllerUI: __init__ accepts whatever main() passes,
    run() immediately raises the failure under test — a fatal OS/storage
    error (SYS-980) is the one this test exercises, mirroring what was
    actually seen during bring-up: a write to the SQLite settings/state DB
    failing because the SD card had gone read-only mid-run."""

    def __init__(self, *args, **kwargs):
        self.running = True

    def run(self):
        raise sqlite3.OperationalError("attempt to write a readonly database")


def test_sys_980_painted_to_display_on_filesystem_failure(monkeypatch, tmp_path):
    recorder = _RecordingDisplay()
    monkeypatch.setattr(main_module, "make_display", lambda simulate: recorder)
    monkeypatch.setattr(main_module, "ControllerUI", _ControllerUIThatRaises)

    rc = main_module.main(["--simulate", "--db", str(tmp_path / "test.db")])

    assert rc == 1
    assert recorder.lines[0] == "SYS-980"


def test_sys_980_handler_swallows_a_broken_display_instead_of_masking_the_real_error(monkeypatch, tmp_path):
    class _BrokenDisplay(_RecordingDisplay):
        def draw_lines(self, lines, invert_row=None, partial=False):
            raise TimeoutError("BUSY pin stuck high")

    monkeypatch.setattr(main_module, "make_display", lambda simulate: _BrokenDisplay())
    monkeypatch.setattr(main_module, "ControllerUI", _ControllerUIThatRaises)

    # The SYS-980 paint attempt itself failing must not crash main() with a
    # *new* traceback on top of the original DB/filesystem failure.
    rc = main_module.main(["--simulate", "--db", str(tmp_path / "test.db")])
    assert rc == 1
