import subprocess

import pytest

from firmware.indi import client as client_module
from firmware.indi.client import IndiClient
from shared import astro


def make_client(**kwargs):
    return IndiClient(host="localhost", port=7624, device="Skywatcher Alt-Az", **kwargs)


def test_connect_succeeds_when_indiserver_reachable(monkeypatch):
    class FakeConn:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(client_module.socket, "create_connection", lambda *a, **kw: FakeConn())
    make_client().connect()  # must not raise


def test_connect_raises_connection_error_when_refused(monkeypatch):
    def fail(*a, **kw): raise OSError("refused")
    monkeypatch.setattr(client_module.socket, "create_connection", fail)
    with pytest.raises(ConnectionError):
        make_client().connect()


def test_sync_sets_coord_mode_then_sends_converted_ra_dec(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    epoch = 1700000000.0  # fixed clock -- precession depends on the current date
    c = make_client(clock=lambda: epoch)
    c.sync("16h41m41s", "+36°28′")
    assert calls[0] == ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.ON_COORD_SET.SYNC=On"]
    ra_deg = (16 + 41 / 60 + 41 / 3600) * 15
    dec_deg = 36 + 28 / 60
    ra_hours, dec_deg = astro.precess_j2000_to_date(ra_deg, dec_deg, epoch)
    ra_hours /= 15
    assert calls[1] == [
        "indi_setprop", "-h", "localhost", "-p", "7624",
        f"Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.RA={ra_hours:.6f};DEC={dec_deg:.6f}",
    ]
    assert c._aligned is True


def test_goto_sets_track_mode_then_sends_converted_ra_dec(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    epoch = 1700000000.0
    c = make_client(clock=lambda: epoch)
    c.goto("250.42", "-6.6667")  # decimal-degree RA (Sesame-style) + decimal Dec
    # TRACK, not SLEW: per skywatcherAPIMount.cpp's status-polling loop,
    # selecting SLEW mode leaves the mount idle (not tracking) once it
    # arrives -- TRACK is what keeps it tracking after the goto completes.
    assert calls[0][-1] == "Skywatcher Alt-Az.ON_COORD_SET.TRACK=On"
    ra_hours, dec_deg = astro.precess_j2000_to_date(250.42, -6.6667, epoch)
    ra_hours /= 15
    assert calls[1][-1] == f"Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.RA={ra_hours:.6f};DEC={dec_deg:.6f}"


def test_sync_raises_on_unparseable_coordinates():
    c = make_client()
    with pytest.raises(ConnectionError):
        c.sync("not a coordinate", "also not one")


def test_park_sends_telescope_park_on(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    make_client().park()
    assert calls == [["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_PARK.PARK=On"]]


def test_unpark_sends_telescope_park_unpark_on(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    make_client().unpark()
    assert calls == [["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_PARK.UNPARK=On"]]


def test_abort_sends_telescope_abort_motion_on(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    make_client().abort()
    assert calls == [["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_ABORT_MOTION.ABORT=On"]]


@pytest.mark.parametrize("speed,rate_element", [
    *((speed, f"{speed}x") for speed in range(1, 9)),
    (9, "SLEW_MAX"),
])
def test_jog_maps_each_preset_to_its_driver_element(monkeypatch, speed, rate_element):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    client = make_client()
    client.jog("N", speed)
    client.stop_jog("N")
    assert calls == [
        ["indi_setprop", "-h", "localhost", "-p", "7624", f"Skywatcher Alt-Az.TELESCOPE_SLEW_RATE.{rate_element}=On"],
        ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_MOTION_NS.MOTION_NORTH=On"],
        ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_MOTION_NS.MOTION_NORTH=Off"],
    ]


def test_jog_directions_map_to_the_right_axis_and_element(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd[-1]) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    c = make_client()
    for direction, expected in [
        ("N", "TELESCOPE_MOTION_NS.MOTION_NORTH"),
        ("S", "TELESCOPE_MOTION_NS.MOTION_SOUTH"),
        ("E", "TELESCOPE_MOTION_WE.MOTION_EAST"),
        ("W", "TELESCOPE_MOTION_WE.MOTION_WEST"),
    ]:
        calls.clear()
        c.jog(direction, 1)
        c.stop_jog(direction)
        assert calls[1] == f"Skywatcher Alt-Az.{expected}=On"
        assert calls[2] == f"Skywatcher Alt-Az.{expected}=Off"


def test_jog_rejects_unknown_direction():
    with pytest.raises(ConnectionError):
        make_client().jog("NE", 1)


def test_get_status_reads_properties_and_computes_alt_az(monkeypatch):
    responses = {
        "Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.RA": "16.694667",
        "Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.DEC": "36.466667",
        "Skywatcher Alt-Az.CONNECTION.CONNECT": "On",
        "Skywatcher Alt-Az.TELESCOPE_TRACK_STATE.TRACK_ON": "On",
        "Skywatcher Alt-Az.TELESCOPE_PARK.PARK": "Off",
    }

    def fake_run(cmd, **kw):
        spec = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, stdout=responses[spec] + "\n")

    monkeypatch.setattr(client_module.subprocess, "run", fake_run)

    class Settings:
        def get(self, key, default=None):
            return {"latitude": "48.15", "longitude": "17.11"}.get(key, default)

    c = make_client(settings=Settings())
    status = c.get_status()
    assert status is not None
    assert status.connected is True
    assert status.tracking is True
    assert status.parked is False
    assert status.ra.startswith("16h41m")
    assert status.dec.startswith("+36")
    assert -90.0 <= status.alt <= 90.0
    assert 0.0 <= status.az < 360.0


def test_get_status_returns_none_on_read_failure(monkeypatch):
    def fail(cmd, **kw):
        raise subprocess.CalledProcessError(1, cmd, stderr="No such device\n")
    monkeypatch.setattr(client_module.subprocess, "run", fail)
    assert make_client().get_status() is None


def test_get_status_without_settings_reports_zero_alt_az(monkeypatch):
    responses = {
        "Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.RA": "12.0",
        "Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.DEC": "0.0",
        "Skywatcher Alt-Az.CONNECTION.CONNECT": "Off",
        "Skywatcher Alt-Az.TELESCOPE_TRACK_STATE.TRACK_ON": "Off",
        "Skywatcher Alt-Az.TELESCOPE_PARK.PARK": "On",
    }

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=responses[cmd[-1]] + "\n")

    monkeypatch.setattr(client_module.subprocess, "run", fake_run)
    status = make_client().get_status()
    assert status is not None
    assert status.alt == 0.0 and status.az == 0.0
    assert status.parked is True


def test_sync_alt_az_sets_coord_mode_then_sends_eod_ra_dec_without_double_precessing(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    epoch = 1700000000.0
    c = make_client(clock=lambda: epoch)
    c.sync_alt_az(45.0, 180.0, 48.0, 17.0)
    assert calls[0] == ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.ON_COORD_SET.SYNC=On"]
    ra_deg, dec_deg = astro.ra_dec_from_alt_az(45.0, 180.0, 48.0, 17.0, epoch)
    assert calls[1] == [
        "indi_setprop", "-h", "localhost", "-p", "7624",
        f"Skywatcher Alt-Az.EQUATORIAL_EOD_COORD.RA={ra_deg / 15.0:.6f};DEC={dec_deg:.6f}",
    ]
    assert c._aligned is True


def test_set_park_position_sends_az_then_alt(monkeypatch):
    calls = []
    monkeypatch.setattr(
        client_module.subprocess, "run",
        lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
    )
    c = make_client()
    c.set_park_position(30.0, 200.0)
    assert calls == [
        ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_PARK_POSITION.PARK_AZ=200.000000"],
        ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.TELESCOPE_PARK_POSITION.PARK_ALT=30.000000"],
    ]
