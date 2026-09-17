import pytest

from firmware.hal.backlight import make_backlight
from firmware.hal.backlight.simulator import SimulatorBacklight
from firmware.hal.backlight.real import RealBacklight


def test_simulator_backlight_prints(capsys):
    backlight = SimulatorBacklight()
    backlight.set(2, 1, 0)
    out = capsys.readouterr().out
    assert "backlight" in out and "R=2" in out


def test_make_backlight_simulated_returns_simulator():
    assert isinstance(make_backlight(True), SimulatorBacklight)


def test_make_backlight_real_returns_real_stub():
    assert isinstance(make_backlight(False), RealBacklight)


def test_real_backlight_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        RealBacklight().set(1, 1, 1)
