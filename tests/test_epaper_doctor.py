"""Runs doctor.main() end to end against a fake Pi (RPi.GPIO + spidev) and a
fake SSD1680 that raises BUSY the way the real controller does, so the
diagnosis logic is exercised without hardware."""
from __future__ import annotations

import sys
import time
import types

import pytest

from firmware.hal.display import doctor
from firmware.hal.display.doctor import CS, DC, FLOATS, MOSI, RST, SCK, Findings, verdict

_REFRESH_S = 0.35


class _Panel:
    """SSD1680 as seen from the host pins: busy_until is when BUSY drops."""

    def __init__(self, gpio: "_FakeGPIO", reaches: set[int]):
        self.gpio = gpio
        self.reaches = reaches  # host lines actually wired to the panel
        self.busy_until = 0.0
        self.pending = None

    def level(self, pin: int) -> int:
        if pin not in self.reaches:
            return 0  # an unconnected panel input floats; SSD1680 has no pulls
        return self.gpio.out.get(pin, 0)

    def busy(self) -> int:
        return int(time.monotonic() < self.busy_until)

    def receive(self, byte: int) -> None:
        if self.level(RST) == 0 or CS not in self.reaches or SCK not in self.reaches or MOSI not in self.reaches:
            return
        is_command = self.level(DC) == 0
        if is_command and byte == 0x12:
            self.busy_until = time.monotonic() + 0.003
        elif is_command and byte == 0x20:
            self.busy_until = time.monotonic() + _REFRESH_S


class _FakeGPIO(types.ModuleType):
    BCM, IN, OUT, SPI = 11, 1, 0, 41
    PUD_OFF, PUD_DOWN, PUD_UP = 20, 21, 22
    HIGH, LOW = 1, 0

    def __init__(self, reaches: set[int], held: dict[int, int] | None = None):
        super().__init__("RPi.GPIO")
        self.out: dict[int, int] = {RST: 1}
        self.pull: dict[int, int] = {}
        self.mode: dict[int, int] = {SCK: self.SPI, MOSI: self.SPI, CS: self.OUT}
        self.held = held or {}  # pin -> level forced by something else (e.g. a XIAO)
        self.panel = _Panel(self, reaches)

    def setwarnings(self, flag): pass
    def setmode(self, mode): pass
    def cleanup(self, pins=None): pass

    def setup(self, pin, mode, pull_up_down=None, initial=None):
        self.mode[pin] = mode
        if pull_up_down is not None:
            self.pull[pin] = pull_up_down
        if mode == self.OUT:
            self.out[pin] = initial if initial is not None else 0
        else:
            self.out.pop(pin, None)

    def output(self, pin, value):
        self.out[pin] = value

    def gpio_function(self, pin):
        return self.mode.get(pin, self.IN)

    def input(self, pin):
        if pin in self.held:
            return self.held[pin]
        if pin == doctor.BUSY:
            if doctor.BUSY in self.panel.reaches and self.panel.level(RST):
                return self.panel.busy()
            return int(self.pull.get(pin) == self.PUD_UP)
        if pin in self.out:
            return self.out[pin]
        for other, level in self.out.items():  # bridged to a driven line
            if frozenset((pin, other)) in self.bridges:
                return level
        return int(self.pull.get(pin) == self.PUD_UP)

    bridges: set = set()


class _FakeSpiDev:
    def __init__(self, gpio: _FakeGPIO):
        self.gpio = gpio
        self.max_speed_hz = 0
        self.mode = 0

    def open(self, bus, dev): pass
    def close(self): pass

    def writebytes(self, data):
        for byte in data:
            self.gpio.panel.receive(byte)


def _run(monkeypatch, capsys, reaches, held=None, bridges=()):
    gpio = _FakeGPIO(set(reaches), held)
    gpio.bridges = {frozenset(pair) for pair in bridges}
    rpi = types.ModuleType("RPi")
    rpi.GPIO = gpio
    spidev = types.ModuleType("spidev")
    spidev.SpiDev = lambda: _FakeSpiDev(gpio)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "systemctl":
            return types.SimpleNamespace(stdout="inactive\n")
        pin, func = int(cmd[2]), cmd[3]
        gpio.mode[pin] = gpio.SPI if func == "a0" else gpio.OUT
        return types.SimpleNamespace(stdout="")

    monkeypatch.setitem(sys.modules, "RPi", rpi)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio)
    monkeypatch.setitem(sys.modules, "spidev", spidev)
    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    monkeypatch.setattr(doctor.shutil, "which", lambda tool: "/usr/bin/pinctrl" if tool == "pinctrl" else None)
    monkeypatch.setattr(doctor.os.path, "exists", lambda path: True)
    monkeypatch.setattr(doctor, "_Pads", _raise_no_devmem)
    doctor.main()
    return capsys.readouterr().out.split("VERDICT", 1)[1], gpio


def _raise_no_devmem():
    raise PermissionError("no /dev/mem in tests")


ALL = {RST, CS, DC, SCK, MOSI, doctor.BUSY}


def test_correct_wiring_refreshes_and_restores_spi_pins(monkeypatch, capsys):
    out, gpio = _run(monkeypatch, capsys, ALL)
    assert "Everything passed" in out
    assert gpio.mode[SCK] == gpio.mode[MOSI] == gpio.SPI and gpio.mode[CS] == gpio.OUT


def test_broken_mosi_is_blamed_on_the_spi_lines(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ALL - {MOSI})
    assert "never executes a command" in out


def test_broken_dc_is_detected(monkeypatch, capsys):
    # DC's panel input floats low (as if always "command"), so data bytes
    # get executed as commands.
    out, _ = _run(monkeypatch, capsys, ALL - {DC})
    assert "DC (pin 22) doesn't reach pad D3" in out


def test_broken_rst_is_detected(monkeypatch, capsys):
    gpio_reaches = ALL - {RST}
    monkeypatch.setattr(_Panel, "level", lambda self, pin: 1 if pin == RST else (
        self.gpio.out.get(pin, 0) if pin in self.reaches else 0))
    out, _ = _run(monkeypatch, capsys, gpio_reaches)
    assert "RST (pin 11) doesn't reach pad D0" in out


def test_floating_busy_is_reported(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ALL - {doctor.BUSY})
    assert "BUSY floats" in out
    assert "never executes" not in out


def test_line_held_by_a_xiao_left_in_the_socket(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ALL, held={DC: 1})
    assert "DC (Pi pin 22 -> pad D3) is held HIGH" in out and "XIAO" in out


def test_solder_bridge_between_lines(monkeypatch, capsys):
    out, _ = _run(monkeypatch, capsys, ALL, bridges=[(CS, SCK)])
    assert "are connected to each other" in out


def test_verdict_suggests_slow_edges_when_only_they_work():
    f = Findings(busy="held LOW", sw_reset_pulse_ms={100_000: 0.0}, slow_edges_pulse_ms={100_000: 2.5})
    assert any("slew-limited" in line for line in verdict(f))


@pytest.mark.parametrize("low,high,state", [(0, 1, FLOATS), (0, 0, "held LOW"), (1, 1, "held HIGH"), (1, 0, "changing")])
def test_classify(low, high, state):
    assert doctor.classify(low, high) == state
