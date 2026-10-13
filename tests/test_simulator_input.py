"""SimulatorInput requires a real interactive terminal on stdin. Under a
systemd-managed service (stdin = /dev/null) it used to sit silently dead
forever whenever hw_sim_keypad/hw_sim_encoder picked it — no warning, no
error, just never producing a single event. These tests pin the fix: it
must now log SIM-001 so that failure mode is diagnosable from the logs.
"""
import logging
import os

from firmware.hal.input.simulator import SimulatorInput


def test_no_tty_logs_sim_001_and_never_produces_events(monkeypatch, caplog):
    devnull = os.fdopen(os.open(os.devnull, os.O_RDONLY), "r")
    monkeypatch.setattr("sys.stdin", devnull)
    with caplog.at_level(logging.WARNING):
        sim = SimulatorInput()
        try:
            assert sim.poll(timeout=0.3) is None
        finally:
            sim.close()
    assert any("SIM-001" in record.message for record in caplog.records)


def test_real_tty_does_not_log_sim_001(monkeypatch, caplog):
    import pty

    controller_fd, terminal_fd = pty.openpty()
    monkeypatch.setattr("sys.stdin", os.fdopen(terminal_fd, "r"))
    with caplog.at_level(logging.WARNING):
        sim = SimulatorInput()
        try:
            os.write(controller_fd, b"\r")
            assert sim.poll(timeout=1.0) == "ENC_PUSH"
        finally:
            sim.close()
            os.close(controller_fd)
    assert not any("SIM-001" in record.message for record in caplog.records)
