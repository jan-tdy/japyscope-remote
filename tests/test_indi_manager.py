import sys
import time

from firmware.indi.manager import IndiServerManager

# A harmless long-running stand-in for `indiserver <driver>` so lifecycle
# behavior (start/stop/restart/crash-recovery) can be tested without a real
# INDI install or mount hardware.
_FAKE_LONG_RUNNING = [sys.executable, "-c", "import time; time.sleep(30)"]
_FAKE_SHORT_LIVED = [sys.executable, "-c", "pass"]


def test_start_and_stop():
    mgr = IndiServerManager(command=_FAKE_LONG_RUNNING)
    mgr.start()
    try:
        assert mgr.is_running() is True
        assert mgr._process.stdout is None
    finally:
        mgr.stop()
    assert mgr.is_running() is False


def test_restart_replaces_process():
    mgr = IndiServerManager(command=_FAKE_LONG_RUNNING)
    mgr.start()
    first_pid = mgr._process.pid
    try:
        mgr.restart()
        assert mgr.is_running() is True
        assert mgr._process.pid != first_pid
    finally:
        mgr.stop()


def test_restart_bumps_restart_count():
    # ControllerUI._poll_indi_restart() watches this counter to know when
    # to replay the mount's WiFi/app CONNECTION.CONNECT and
    # GEOGRAPHIC_COORD/TIME_UTC setup on a freshly spawned driver --
    # start() must bump it every time it actually spawns a process.
    mgr = IndiServerManager(command=_FAKE_LONG_RUNNING)
    mgr.start()
    try:
        assert mgr.restart_count == 1
        mgr.restart()
        assert mgr.restart_count == 2
    finally:
        mgr.stop()


def test_watchdog_restarts_after_crash():
    mgr = IndiServerManager(command=_FAKE_SHORT_LIVED)
    mgr.start()
    try:
        # The watchdog loop checks every HEALTH_CHECK_INTERVAL_S (5s), then
        # waits RESTART_BACKOFF_S (3s) before respawning — give it comfortable
        # margin beyond that combined 8s before giving up.
        deadline = time.monotonic() + 13
        pids_seen = set()
        while time.monotonic() < deadline:
            if mgr._process is not None:
                pids_seen.add(mgr._process.pid)
            time.sleep(0.2)
        assert len(pids_seen) > 1, "expected the watchdog to have restarted the crashed process"
    finally:
        mgr.stop()
    # Each pid change above was a respawn (the first start() plus every
    # watchdog respawn after) -- restart_count must have kept pace, or
    # ControllerUI would never notice and would never replay mount setup.
    assert mgr.restart_count >= len(pids_seen)
