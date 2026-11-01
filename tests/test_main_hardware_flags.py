import os
import sqlite3
import subprocess
import tempfile

import pytest

from firmware import main as main_module
from firmware.main import HARDWARE_COMPONENTS, _poweroff, build_parser, resolve_simulation_flags, run_telescope_flush_loop
from firmware.hal.display.profiles import PROFILE_2_13
from shared.db import SettingsRepo, TelescopeEventOutboxRepo, connect, init_db


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


class _ControllerUIThatRaisesSomethingUnforeseen:
    """Stands in for a bug in the UI/INDI code itself — anything that isn't
    a startup failure (INDI-001/002) or an OS/storage failure (SYS-980).
    Confirmed on hardware as a silent crash with nothing painted to the
    panel; SYS-970 is the generic catch-all added to fix that."""

    def __init__(self, *args, **kwargs):
        self.running = True

    def run(self):
        raise ValueError("boom")


def test_sys_970_painted_to_display_on_an_otherwise_unhandled_crash(monkeypatch, tmp_path):
    recorder = _RecordingDisplay()
    monkeypatch.setattr(main_module, "make_display", lambda simulate: recorder)
    monkeypatch.setattr(main_module, "ControllerUI", _ControllerUIThatRaisesSomethingUnforeseen)

    rc = main_module.main(["--simulate", "--db", str(tmp_path / "test.db")])

    assert rc == 1
    assert recorder.lines[0] == "SYS-970"


def test_poweroff_runs_sudo_systemctl_poweroff_with_a_bounded_wait(monkeypatch):
    calls = []
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: calls.append((a, kw)) or subprocess.CompletedProcess(a[0], 0)
    )

    _poweroff()

    (args,), kwargs = calls[0][0], calls[0][1]
    assert args == ["/usr/bin/sudo", "systemctl", "poweroff"]
    assert kwargs["check"] is True
    assert kwargs["timeout"] == 10


def test_poweroff_propagates_a_failed_sudo_as_a_subprocess_error(monkeypatch):
    # Confirmed gap: a Popen-based fire-and-forget call never surfaces a
    # missing/stale sudoers grant (sudo exits nonzero, but nothing checks
    # it) — the device would sit on the SHUTDOWN screen forever with
    # nothing actually powered off. subprocess.run(check=True) turns that
    # into a SubprocessError, which ControllerUI._shutdown() already
    # catches and logs as SYS-990.
    def _raise(*a, **kw):
        raise subprocess.CalledProcessError(1, a[0])

    monkeypatch.setattr(subprocess, "run", _raise)

    with pytest.raises(subprocess.SubprocessError):
        _poweroff()


class _StopAfterOneWait:
    """Duck-typed threading.Event stand-in: lets run_telescope_flush_loop's
    outer while-loop run exactly once (and its inner drain-until-empty loop
    run to completion) without a real thread or sleep."""

    def __init__(self):
        self._stopped = False

    def is_set(self):
        return self._stopped

    def wait(self, timeout=None):
        self._stopped = True
        return True


def test_run_telescope_flush_loop_drains_outbox_when_linked(monkeypatch):
    settings, conn, path = make_settings()
    settings.set("visual_astro_device_token", "tok-abc")
    outbox = TelescopeEventOutboxRepo(conn)
    outbox.enqueue("event-1", "V445Her", started_at=1000.0, ended_at=1100.0)
    outbox.enqueue("event-2", "AG Dra", started_at=1200.0, ended_at=1260.0)
    conn.close()

    import shared.visual_astro as visual_astro_module
    sent_event_ids = []

    def fake_ingest(self, device_token, events):
        assert device_token == "tok-abc"
        sent_event_ids.extend(e["event_id"] for e in events)
        return True

    monkeypatch.setattr(visual_astro_module.VisualAstroClient, "ingest", fake_ingest)

    run_telescope_flush_loop(path, _StopAfterOneWait())

    assert sorted(sent_event_ids) == ["event-1", "event-2"]
    conn = connect(path)
    assert TelescopeEventOutboxRepo(conn).count() == 0
    conn.close()
    os.unlink(path)


def test_run_telescope_flush_loop_skips_when_not_linked(monkeypatch):
    settings, conn, path = make_settings()
    outbox = TelescopeEventOutboxRepo(conn)
    outbox.enqueue("event-1", "V445Her", started_at=1000.0, ended_at=1100.0)
    conn.close()

    import shared.visual_astro as visual_astro_module

    def fail_ingest(self, device_token, events):
        raise AssertionError("must not call Visual Astro without a linked device token")

    monkeypatch.setattr(visual_astro_module.VisualAstroClient, "ingest", fail_ingest)

    run_telescope_flush_loop(path, _StopAfterOneWait())

    conn = connect(path)
    assert TelescopeEventOutboxRepo(conn).count() == 1
    conn.close()
    os.unlink(path)
