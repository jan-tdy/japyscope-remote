"""Drives each e-paper control/SPI line from the Pi one at a time, so every
wire can be checked end to end with a multimeter at the driver board.

    sudo systemctl stop japyscope-app
    cd /opt/japyscope/current
    sudo .venv/bin/python -m firmware.hal.display.wiretest
    sudo reboot

SCK, MOSI and CS are taken from the SPI driver for the test and only get
their SPI function back after a reboot.
"""
from __future__ import annotations

import sys

# (signal, BCM, Pi physical pin, XIAO pad, Seeed breakout header pin)
LINES = (
    ("RST", 17, 11, "D0", "CN1 pin 1"),
    ("CS", 8, 24, "D1", "CN1 pin 2"),
    ("DC", 25, 22, "D3", "CN1 pin 4"),
    ("SCK", 11, 23, "D8", "CN2 pin 2"),
    ("MOSI", 10, 19, "D10", "CN2 pin 4"),
)


def main() -> int:
    import RPi.GPIO as GPIO  # noqa: N814

    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    pins = [bcm for _, bcm, *_ in LINES]
    for pin in pins:
        GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)

    print("Multimeter on DC volts. Black probe on the driver board's GND pad.")
    print("For each step, put the red probe on the named pad: it should read ~3.3 V.")
    print("If it reads 0 V, or 3.3 V shows up on a different pad, that wire is wrong.\n")
    try:
        for name, bcm, physical, pad, header in LINES:
            GPIO.output(bcm, GPIO.HIGH)
            input(f"{name}: Pi pin {physical} (BCM{bcm}) is now HIGH -> measure pad {pad} "
                  f"({header}). Press Enter for the next line...")
            GPIO.output(bcm, GPIO.LOW)
    finally:
        GPIO.cleanup(pins)
    print("\nDone. BUSY (Pi pin 18 <-> pad D2 / CN1 pin 3) is an input, check it for "
          "continuity with the Pi powered off. Now reboot: sudo reboot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
