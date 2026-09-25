"""Standalone SSD1680 bring-up check, independent of EPaperDisplay.

Stop japyscope-app first so nothing else holds the GPIO/SPI pins, then:

    sudo systemctl stop japyscope-app
    cd /opt/japyscope/current
    sudo .venv/bin/python -m firmware.hal.display.selftest

A literal port of Seeed_GFX's SSD1680 sequence (SSD1680_Init.h /
SSD1680_Defines.h) with no rasterizer, rotation or DisplayHAL involved:
paints the whole panel black, then white. If the panel doesn't flash here
either, the fault is in the wiring/board, not in the firmware driver.
"""
from __future__ import annotations

import sys
import time

DC, RST, BUSY = 25, 17, 24
SOURCE_BYTES, GATES = 16, 250  # 2.13" native RAM: 122 (padded to 128) x 250
FRAME_BYTES = SOURCE_BYTES * GATES


def main() -> int:
    import RPi.GPIO as GPIO  # noqa: N814
    import spidev

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(DC, GPIO.OUT, initial=GPIO.HIGH)
    # initial=HIGH: RPi.GPIO defaults outputs to LOW, which would hold the
    # panel in hardware reset (and its BUSY pin possibly high-impedance).
    GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.setup(BUSY, GPIO.IN, pull_up_down=GPIO.PUD_OFF)

    print("Hardware reset (Seeed timing: 10ms low, 120ms high)")
    GPIO.output(RST, GPIO.LOW)
    time.sleep(0.01)
    GPIO.output(RST, GPIO.HIGH)
    time.sleep(0.12)

    # Idle and out of reset, the panel drives BUSY low; a pin the panel
    # drives reads the same under either internal pull, a disconnected one
    # follows the pull.
    GPIO.setup(BUSY, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
    time.sleep(0.01)
    low_pull = GPIO.input(BUSY)
    GPIO.setup(BUSY, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    time.sleep(0.01)
    high_pull = GPIO.input(BUSY)
    GPIO.setup(BUSY, GPIO.IN, pull_up_down=GPIO.PUD_OFF)
    floating = low_pull == 0 and high_pull == 1
    print(f"BUSY with pull-down={low_pull}, pull-up={high_pull} -> "
          + ("FLOATING: BUSY (BCM24, pin 18) is not connected to the panel" if floating else "driven by the panel"))

    spi = spidev.SpiDev()
    spi.open(0, 0)
    spi.max_speed_hz = 4_000_000
    spi.mode = 0

    def cmd(c: int, *data: int) -> None:
        GPIO.output(DC, GPIO.LOW)
        spi.writebytes([c])
        if data:
            GPIO.output(DC, GPIO.HIGH)
            spi.writebytes(list(data))

    def frame(fill: int) -> None:
        cmd(0x4E, 0x00)
        cmd(0x4F, 0x00, 0x00)
        GPIO.output(DC, GPIO.LOW)
        spi.writebytes([0x24])
        GPIO.output(DC, GPIO.HIGH)
        spi.writebytes([fill] * FRAME_BYTES)

    def wait(label: str, timeout: float = 10.0) -> float:
        start = time.monotonic()
        while GPIO.input(BUSY) == GPIO.HIGH:
            if time.monotonic() - start > timeout:
                print(f"  {label}: BUSY still high after {timeout}s")
                return timeout
            time.sleep(0.005)
        elapsed = time.monotonic() - start
        print(f"  {label}: BUSY cleared after {elapsed:.3f}s")
        return elapsed

    try:
        wait("after hw reset")

        cmd(0x12)
        wait("sw reset")

        cmd(0x3C, 0x05)
        cmd(0x01, (GATES - 1) & 0xFF, (GATES - 1) >> 8, 0x00)
        cmd(0x11, 0x03)
        cmd(0x44, 0x00, SOURCE_BYTES - 1)
        cmd(0x45, 0x00, 0x00, (GATES - 1) & 0xFF, (GATES - 1) >> 8)
        cmd(0x18, 0x80)
        cmd(0x4E, 0x00)
        cmd(0x4F, 0x00, 0x00)
        wait("init")

        results = []
        for name, fill in (("BLACK", 0x00), ("WHITE", 0xFF)):
            print(f"Full refresh to {name} — watch the panel")
            frame(fill)
            cmd(0x22, 0xF7)
            cmd(0x20)
            results.append(wait(f"refresh {name}"))

        cmd(0x10, 0x01)
    finally:
        spi.close()
        GPIO.cleanup([DC, RST, BUSY])

    if floating:
        verdict = "BUSY is not connected — fix the BUSY wire before anything else."
    elif all(t >= 0.3 for t in results):
        verdict = ("Refresh timing looks real. If the panel flashed black then white, the panel and "
                   "wiring are fine and the problem is in the firmware driver.")
    else:
        verdict = ("Refresh finished far too fast for a real e-paper waveform — the controller answers "
                   "but never drives the panel. Check the 24-pin FPC ribbon seating and the driver "
                   "board's power, not the firmware.")
    print(verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
