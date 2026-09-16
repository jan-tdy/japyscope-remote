from firmware.hal.display.profiles import PROFILE_2_13, PROFILE_4_26, get_active_profile
from firmware.hal.display.simulator import SimulatorDisplay


def test_default_profile_is_2_13(monkeypatch):
    monkeypatch.delenv("JAPYSCOPE_DISPLAY_PROFILE", raising=False)
    assert get_active_profile() == PROFILE_2_13


def test_profile_selectable_via_env(monkeypatch):
    monkeypatch.setenv("JAPYSCOPE_DISPLAY_PROFILE", "4.26in")
    assert get_active_profile() == PROFILE_4_26


def test_simulator_display_does_not_crash_on_empty_and_full_screens(capsys):
    display = SimulatorDisplay(profile=PROFILE_2_13)
    display.clear()
    display.draw_lines(["JapyScope Remote", "Not aligned", "> Menu", "> Catalog"])
    display.set_backlight(1, 0, 2)
    out = capsys.readouterr().out
    assert "JapyScope Remote" in out
    assert "backlight" in out
