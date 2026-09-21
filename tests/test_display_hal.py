import pytest

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
    out = capsys.readouterr().out
    assert "JapyScope Remote" in out


def test_simulator_display_redacts_sensitive_lines_before_printing(capsys):
    display = SimulatorDisplay(profile=PROFILE_2_13)

    display.draw_lines(
        [
            "Connection settings",
            "Password: telescope-secret",
            "Lat 48.1486 N",
            "Lon 17.1077 E",
        ]
    )

    output_lines = capsys.readouterr().out.splitlines()
    assert "Connection settings" in output_lines
    assert "Password: [REDACTED]" in output_lines
    assert "Lat [REDACTED]" in output_lines
    assert "Lon [REDACTED]" in output_lines
    assert "Password: telescope-secret" not in output_lines
    assert "Lat 48.1486 N" not in output_lines
    assert "Lon 17.1077 E" not in output_lines


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Password:", "Password: [REDACTED]"),
        ("Password:    spaced secret", "Password: [REDACTED]"),
        ("Lat\t48.1486 N", "Lat [REDACTED]"),
        ("Lon    17.1077 E", "Lon [REDACTED]"),
    ],
)
def test_simulator_display_redacts_sensitive_format_variants(line, expected):
    display = SimulatorDisplay(profile=PROFILE_2_13)

    assert display._sanitize_line(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "password: intentionally lowercase",
        "Password reminder",
        "Latitude unavailable",
        "Longitude unavailable",
        "Lat",
        "Lon",
        "Latest catalog update",
        "Lonely target",
    ],
)
def test_simulator_display_preserves_non_sensitive_lookalikes(line):
    display = SimulatorDisplay(profile=PROFILE_2_13)

    assert display._sanitize_line(line) == line
