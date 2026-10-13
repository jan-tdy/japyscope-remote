"""Hands-off e-paper diagnosis for the Pi-driven Seeed 2.13" board: no
multimeter, no key presses, one verdict at the end.

    sudo systemctl stop japyscope-app
    cd /opt/japyscope/current
    sudo .venv/bin/python -m firmware.hal.display.doctor
    sudo reboot

The only sensors are the Pi's own pins and the panel's BUSY output (the
board has no pull resistors on any signal, per its EPAPER_IO_V20
schematic):

- A Pi-driven line with nothing but the panel's high-impedance input on it
  follows the Pi's internal pull resistor. One that doesn't is shorted to
  3V3/GND/BUSY, or something else drives it (e.g. a XIAO left in the socket).
- Driving one such line while the others float finds solder bridges.
- The SSD1680 holds BUSY high for a few ms while it executes SW reset
  (0x12), so a BUSY pulse right after sending 0x12 proves CS, SCK, MOSI and
  DC all reach it; the same byte sent as data (DC high), or while RST holds
  the controller in reset, must not pulse.
- A full refresh with the register waveform holds BUSY for ~2 s.
"""
from __future__ import annotations

import mmap
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from .epaper import FULL_UPDATE_VOLTAGES_2_13, FULL_UPDATE_WAVEFORM_2_13

RST, CS, DC, BUSY, SCK, MOSI = 17, 8, 25, 24, 11, 10
NAMES = {
    RST: "RST (Pi pin 11 -> pad D0)",
    CS: "CS (Pi pin 24 -> pad D1)",
    BUSY: "BUSY (Pi pin 18 -> pad D2)",
    DC: "DC (Pi pin 22 -> pad D3)",
    SCK: "SCK (Pi pin 23 -> pad D8)",
    MOSI: "MOSI (Pi pin 19 -> pad D10)",
}
SPI_PINS = (CS, SCK, MOSI)
SPEEDS_HZ = (20_000, 100_000, 1_000_000, 4_000_000)
SOURCE_BYTES, GATES = 16, 250
FRAME_BYTES = SOURCE_BYTES * GATES
FLOATS = "floats"
MIN_REFRESH_S = 0.3

# BCM2835 PADS block, GPIO 0-27 bank: [2:0] drive 2..16 mA, [3] hysteresis,
# [4] 1 = slew rate NOT limited, [31:24] must be written as 0x5A.
_PADS_OFFSET = 0x100000
_PADS_GPIO_0_27 = 0x2C
_PADS_PASSWORD = 0x5A000000
_PADS_SLOW_EDGES = 0x08  # 2 mA, hysteresis on, slew rate limited


@dataclass
class Findings:
    spi_pins_restored: bool = True
    lines: dict = field(default_factory=dict)  # pin -> FLOATS / "held LOW" / "held HIGH" / "changing"
    bridges: list = field(default_factory=list)  # [(pin_a, pin_b)]
    busy: str = ""  # BUSY probe with the panel out of reset
    hw_reset_pulse_ms: Optional[float] = None
    sw_reset_pulse_ms: dict = field(default_factory=dict)  # SPI Hz -> BUSY high ms after 0x12
    slow_edges_pulse_ms: dict = field(default_factory=dict)  # same, with slew-limited pads
    slow_edges_error: str = ""
    dc_as_data_pulse_ms: Optional[float] = None
    in_reset_pulse_ms: Optional[float] = None
    refresh_s: list = field(default_factory=list)


def classify(low_pull: int, high_pull: int) -> str:
    return {(0, 1): FLOATS, (0, 0): "held LOW", (1, 1): "held HIGH"}.get((low_pull, high_pull), "changing")


def verdict(f: Findings) -> list[str]:
    """Most fundamental problem first; everything after it may be a symptom."""
    out = []
    if not f.spi_pins_restored:
        out.append("SPI pins (BCM8/10/11) are not in SPI mode and could not be restored — reboot and rerun.")
    for pin, state in f.lines.items():
        if state != FLOATS:
            out.append(
                f"{NAMES[pin]} is {state} although only the panel's input should be on it: "
                "it's shorted to 3V3/GND/BUSY/RST or something else drives it. Is the XIAO still "
                "in the socket? Otherwise look for a solder bridge on that pad or on the Pi header."
            )
    for a, b in f.bridges:
        out.append(f"{NAMES[a]} and {NAMES[b]} are connected to each other — solder bridge or swapped wire.")
    if f.busy == FLOATS:
        out.append(
            "BUSY floats with the panel out of reset: the BUSY wire doesn't reach pad D2, or the panel "
            "isn't powered/connected (FPC ribbon latch, 3V3 on CN2-5, GND on CN2-6)."
        )
    elif f.busy and f.busy != "held LOW":
        out.append(f"BUSY is {f.busy} with the panel idle; it should be held LOW.")
    pulsed = {hz: ms for hz, ms in f.sw_reset_pulse_ms.items() if ms > 0}
    slow_pulsed = {hz: ms for hz, ms in f.slow_edges_pulse_ms.items() if ms > 0}
    # With BUSY floating it can't show a pulse, so SPI can't be judged.
    if f.sw_reset_pulse_ms and not pulsed and f.busy != FLOATS:
        if slow_pulsed:
            out.append(
                "Commands only reach the panel with slew-limited GPIO edges: the long wires ring "
                "and double-clock SCK. Fix: enable slow edges in the driver, or shorten the wires "
                "/ add ~47-100 ohm in series with SCK and MOSI at the Pi."
            )
        elif f.busy == "held LOW":
            out.append(
                "The panel is alive (drives BUSY) but never executes a command at any SPI speed: "
                "one of CS (pin 24 -> D1), SCK (pin 23 -> D8), MOSI (pin 19 -> D10) or DC "
                "(pin 22 -> D3) doesn't reach its pad."
            )
        else:
            out.append("No command ever reached the panel.")
    if pulsed and f.dc_as_data_pulse_ms and f.dc_as_data_pulse_ms > 0:
        out.append("The panel treats data as commands: DC (pin 22) doesn't reach pad D3.")
    if pulsed and f.in_reset_pulse_ms and f.in_reset_pulse_ms > 0:
        out.append("The panel executes commands while RST is held low: RST (pin 11) doesn't reach pad D0.")
    if pulsed and f.refresh_s and min(f.refresh_s) < MIN_REFRESH_S:
        out.append(
            "Commands arrive, but the full refresh ends too early — the controller likely browns out "
            "when the booster starts: use short, thick 3V3/GND wires straight to CN2-5/CN2-6."
        )
    if not out:
        if f.refresh_s:
            out.append("Everything passed: the panel refreshed from the Pi. Start the app.")
        else:
            out.append("No fault found, but the refresh test didn't run.")
    return out


def _pin_tool() -> Optional[str]:
    return shutil.which("pinctrl") or shutil.which("raspi-gpio")


def _capture_busy(GPIO, window_s: float) -> float:
    """Poll BUSY as fast as Python allows for window_s; return ms it was high."""
    start = last = time.perf_counter()
    high_s = 0.0
    level = GPIO.input(BUSY)
    while last - start < window_s:
        now = time.perf_counter()
        if level:
            high_s += now - last
        level = GPIO.input(BUSY)
        last = now
    return round(high_s * 1000, 2)


def _wait_idle(GPIO, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while GPIO.input(BUSY) and time.monotonic() < deadline:
        time.sleep(0.001)


def _pulse_after(GPIO, send) -> float:
    """BUSY high time (ms) in the 50 ms after send(); -1 when BUSY was
    already high before, so a pulse can't be told apart (inconclusive)."""
    baseline = _capture_busy(GPIO, 0.02)
    if baseline > 0:
        return -1.0
    send()
    return _capture_busy(GPIO, 0.05)


def _print_verdict(f: Findings) -> None:
    print("\nVERDICT")
    print("\n".join(f"- {line}" for line in verdict(f)))


def _probe(GPIO, pin: int) -> str:
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    time.sleep(0.005)
    low = GPIO.input(pin)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(0.005)
    high = GPIO.input(pin)
    GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
    return classify(low, high)


def _find_bridges(GPIO, pins: list[int]) -> list[tuple[int, int]]:
    bridges: set[tuple[int, int]] = set()
    for a in pins:
        for level, pull in ((1, GPIO.PUD_DOWN), (0, GPIO.PUD_UP)):
            for b in pins:
                if b != a:
                    GPIO.setup(b, GPIO.IN, pull_up_down=pull)
            GPIO.setup(a, GPIO.OUT, initial=level)
            time.sleep(0.003)
            for b in pins:
                if b != a and GPIO.input(b) == level:
                    bridges.add(tuple(sorted((a, b))))
            GPIO.setup(a, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
    return sorted(bridges)


class _Pads:
    """Direct access to the GPIO 0-27 pad control register via /dev/mem."""

    def __init__(self):
        with open("/proc/device-tree/soc/ranges", "rb") as ranges:
            data = ranges.read(12)
        base = int.from_bytes(data[4:8], "big") or int.from_bytes(data[8:12], "big")
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        try:
            self._mem = mmap.mmap(fd, mmap.PAGESIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                                  offset=base + _PADS_OFFSET)
        finally:
            os.close(fd)
        self._regs = memoryview(self._mem).cast("I")
        self.original = self._regs[_PADS_GPIO_0_27 // 4] & 0xFF

    def set(self, value: int) -> None:
        self._regs[_PADS_GPIO_0_27 // 4] = _PADS_PASSWORD | (value & 0xFF)

    def close(self) -> None:
        self.set(self.original)
        self._regs.release()
        self._mem.close()


def _report(title: str, value) -> None:
    print(f"  {title:<44} {value}")


def main() -> int:
    import RPi.GPIO as GPIO  # noqa: N814
    import spidev

    f = Findings()
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)

    for unit in ("japyscope-app", "japyscope-splash"):
        state = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True).stdout.strip()
        if state in ("active", "activating"):
            print(f"{unit} is running and uses the same pins — stop it first: sudo systemctl stop {unit}")
            return 1
    if not os.path.exists("/dev/spidev0.0"):
        print("/dev/spidev0.0 missing — enable SPI (dtparam=spi=on in config.txt) and reboot.")
        return 1

    tool = _pin_tool()
    cs_was_output = GPIO.gpio_function(CS) == GPIO.OUT
    print("1) Lines: does anything other than the panel's inputs sit on them?")
    if not tool:
        print("  (pinctrl/raspi-gpio not found: CS, SCK, MOSI skipped, they must stay in SPI mode)")
    f.lines[RST] = _probe(GPIO, RST)
    _report(NAMES[RST], f.lines[RST])
    # The rest with the panel out of reset, so a line bridged to BUSY reads
    # as held LOW (the idle panel drives BUSY low) and one bridged to RST as
    # held HIGH.
    GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)
    time.sleep(0.15)
    line_pins = [DC] + (list(SPI_PINS) if tool else [])
    try:
        for pin in line_pins:
            f.lines[pin] = _probe(GPIO, pin)
            _report(NAMES[pin], f.lines[pin])
        floating = [pin for pin in line_pins if f.lines[pin] == FLOATS]
        f.bridges = _find_bridges(GPIO, floating)
        for a, b in f.bridges:
            _report("BRIDGE", f"{NAMES[a]} <-> {NAMES[b]}")
        if not f.bridges:
            _report("Bridges between lines", "none")
    finally:
        if tool:
            try:
                for pin in (SCK, MOSI):
                    subprocess.run([tool, "set", str(pin), "a0"], check=True, capture_output=True)
                cs_mode = ["op", "dh"] if cs_was_output else ["a0"]
                subprocess.run([tool, "set", str(CS), *cs_mode], check=True, capture_output=True)
            except (OSError, subprocess.CalledProcessError):
                f.spi_pins_restored = False
    if GPIO.gpio_function(SCK) != GPIO.SPI or GPIO.gpio_function(MOSI) != GPIO.SPI:
        f.spi_pins_restored = False
        _print_verdict(f)
        return 1

    GPIO.setup(DC, GPIO.OUT, initial=GPIO.LOW)

    print("2) Panel: BUSY and hardware reset")
    GPIO.output(RST, GPIO.LOW)
    time.sleep(0.01)
    GPIO.output(RST, GPIO.HIGH)
    GPIO.setup(BUSY, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    f.hw_reset_pulse_ms = _capture_busy(GPIO, 0.2)
    _report("BUSY high after hardware reset (ms)", f.hw_reset_pulse_ms)
    f.busy = _probe(GPIO, BUSY)
    _report("BUSY with the panel idle", f"{f.busy} (should be held LOW)")
    GPIO.setup(BUSY, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.mode = 0

    def command(byte: int, *data: int) -> None:
        GPIO.output(DC, GPIO.LOW)
        spi.writebytes([byte])
        if data:
            GPIO.output(DC, GPIO.HIGH)
            for offset in range(0, len(data), 4096):
                spi.writebytes(list(data[offset:offset + 4096]))

    def sw_reset_pulse(dc_level: int = 0) -> float:
        _wait_idle(GPIO)
        GPIO.output(DC, dc_level)
        return _pulse_after(GPIO, lambda: spi.writebytes([0x12]))

    try:
        print("3) SPI: does the panel execute SW reset (0x12)? BUSY must pulse high")
        for hz in SPEEDS_HZ:
            spi.max_speed_hz = hz
            f.sw_reset_pulse_ms[hz] = sw_reset_pulse()
            _report(f"{hz // 1000} kHz: BUSY high (ms)", f.sw_reset_pulse_ms[hz])

        working = [hz for hz, ms in f.sw_reset_pulse_ms.items() if ms > 0]
        if not working:
            print("   ...retrying with slow (slew-limited, 2 mA) GPIO edges")
            try:
                pads = _Pads()
            except OSError as exc:
                f.slow_edges_error = str(exc)
                _report("slow edges", f"skipped ({exc})")
            else:
                try:
                    pads.set(_PADS_SLOW_EDGES)
                    for hz in (100_000, 1_000_000):
                        spi.max_speed_hz = hz
                        f.slow_edges_pulse_ms[hz] = sw_reset_pulse()
                        _report(f"{hz // 1000} kHz slow edges: BUSY high (ms)", f.slow_edges_pulse_ms[hz])
                finally:
                    pads.close()
            _print_verdict(f)
            return 0

        spi.max_speed_hz = min(working, key=lambda hz: abs(hz - 100_000))
        print(f"4) DC and RST (at {spi.max_speed_hz // 1000} kHz)")
        f.dc_as_data_pulse_ms = sw_reset_pulse(dc_level=1)
        _report("0x12 sent as DATA: BUSY high (ms, want 0)", f.dc_as_data_pulse_ms)
        _wait_idle(GPIO)
        GPIO.output(RST, GPIO.LOW)
        time.sleep(0.01)
        GPIO.output(DC, GPIO.LOW)
        f.in_reset_pulse_ms = _pulse_after(GPIO, lambda: spi.writebytes([0x12]))
        GPIO.output(RST, GPIO.HIGH)
        time.sleep(0.12)
        _report("0x12 while RST low: BUSY high (ms, want 0)", f.in_reset_pulse_ms)

        print("5) Full refresh with the register waveform: black, then white (~2 s each)")
        command(0x12)
        _wait_idle(GPIO)
        command(0x01, GATES - 1, 0x00, 0x00)
        command(0x11, 0x03)
        command(0x44, 0x00, SOURCE_BYTES - 1)
        command(0x45, 0x00, 0x00, GATES - 1, 0x00)
        command(0x3C, 0x05)
        command(0x18, 0x80)
        command(0x21, 0x00, 0x80)
        eopt, vgh, source, vcom = FULL_UPDATE_VOLTAGES_2_13
        command(0x32, *FULL_UPDATE_WAVEFORM_2_13)
        command(0x3F, eopt)
        command(0x03, vgh)
        command(0x04, *source)
        command(0x2C, vcom)
        for name, fill in (("black", 0x00), ("white", 0xFF)):
            for ram in (0x24, 0x26):
                command(0x4E, 0x00)
                command(0x4F, 0x00, 0x00)
                command(ram, *([fill] * FRAME_BYTES))
            command(0x22, 0xC7)
            command(0x20)
            start = time.monotonic()
            time.sleep(0.001)
            _wait_idle(GPIO, timeout_s=10.0)
            f.refresh_s.append(round(time.monotonic() - start, 3))
            _report(f"refresh to {name}: BUSY high (s)", f.refresh_s[-1])
        command(0x10, 0x01)
    finally:
        spi.close()
        GPIO.cleanup([DC, RST, BUSY])

    _print_verdict(f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
