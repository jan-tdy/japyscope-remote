---
layout: default
title: Wiring and pinout
permalink: /wiring/
---

# JapyScope Remote — Wiring & Pinout

Single source of truth for how the Raspberry Pi Zero W is wired. Update this
file (not a second copy elsewhere) as each build phase confirms real pins.

Status: **Fáza 0 / 1beta** — jumper-wire prototype, most pin numbers below
are the firmware's current defaults (`firmware/hal/*/keypad.py`,
`firmware/hal/display/epaper.py`), not yet verified against a soldered
board. Cross-check before trusting a pin.

## Mount connection (RJ12, not RJ45)
{: #mount-connection}

The controller connects directly to the mount's **RJ12** "Hand Control" port
— this bypasses the stock SynScan hand controller entirely and speaks the
Sky-Watcher Motor Controller Command Set protocol directly (same principle
as an EQDIRECT cable).

- Mount side TTL is **5V**, Pi Zero W GPIO is **3.3V** → a logic-level
  shifter is required between the two (already in hand per project notes).
- Pi Zero W UART (`/dev/serial0`) ↔ level shifter ↔ RJ12 pins carrying
  TX/RX/GND.

**Confirmed** (Fáza 1beta), clip facing down / contacts up / counted left to
right, through a 4-channel level shifter (HV side = 5V mount, LV side =
3.3V Pi):

| RJ12 pin | Signal | Via | Pi pin |
|---|---|---|---|
| 1 | EXPD+ | — | not wired |
| 2 | data | shifter HV1 → LV1 | GPIO14 (TXD) or GPIO15 (RXD) |
| 3 | GND | shifter HV GND + LV GND (shared) | GND |
| 4 | EXPD-/NC | — | not wired |
| 5 | data | shifter HV2 → LV2 | GPIO15 (RXD) or GPIO14 (TXD) |
| 6 | +12V | — | **not wired — never to shifter or Pi** |

Shifter HV-VCC → Pi 5V (physical pin 2/4). Shifter LV-VCC → Pi 3V3
(physical pin 1). TX/RX direction is the only ambiguity and swapping it is
harmless — if the mount doesn't respond, swap pins 2/5 at the Pi end.

Unused: RJ12 pins 1 (white), 4 (yellow), 6 (red) — trim short and insulate,
do not connect pin 6 (+12V) to the level shifter or Pi.

## Keypad (3×4 matrix, stock SparkFun COM-14662)
{: #keypad}

Stickers-only key legend, no physical modification to the keypad itself.
Matrix scan pins (BCM numbering, `firmware/hal/input/keypad.py`):

| Signal | BCM pin |
|---|---|
| Row 1 | 5 |
| Row 2 | 6 |
| Row 3 | 13 |
| Row 4 | 19 |
| Col 1 | 26 |
| Col 2 | 20 |
| Col 3 | 21 |

Row-major key layout (see `docs/CODES.md` for what each key does):

| | Col 1 | Col 2 | Col 3 |
|---|---|---|---|
| Row 1 | 1 | 2 | 3 |
| Row 2 | 4 | 5 | 6 |
| Row 3 | 7 | 8 | 9 |
| Row 4 | FN2 | 0 | BKSP |

## Rotary encoder (KY-040)
{: #rotary-encoder}

| Signal | BCM pin |
|---|---|
| CLK | 16 |
| DT | 12 |
| SW (push) | 7 |

Also needs a printed D-shaft knob for the KY-040 shaft (JLC3DP, per project
notes) — not a wiring item, tracked here as a reminder for the enclosure BOM.

## Display (e-ink, SPI) — panel not finalized
{: #display}

See `docs/ARCHITECTURE.md` for the 2.13"-vs-4.26" status. SPI wiring is the
same regardless of panel size (`firmware/hal/display/epaper.py`):

| Signal | BCM pin | Notes |
|---|---|---|
| DIN (MOSI) | SPI0 MOSI (10) | hardware SPI |
| CLK (SCLK) | SPI0 SCLK (11) | hardware SPI |
| CS | SPI0 CE0 (8) | hardware SPI |
| DC | 25 | data/command select |
| RST | 17 | reset |
| BUSY | 24 | input, panel-busy signal |

## Backlight (custom RGB edge-lighting)

Not a bonded/commercial frontlight — a custom JapySoft side/edge-mounted RGB
LED solution (2× 5mm LED per side of the display, per project notes).

**Switching mechanism confirmed**: plain GPIO drive — each 5mm LED wired
with its own series current-limiting resistor straight to a Pi Zero W GPIO
pin, no MOSFET and no dedicated LED driver IC. Off/Med/High per channel
(R/G/B) is done with software PWM on those GPIO pins, not separate
resistor values.

**TODO**: exact GPIO pin assignment per channel/LED and resistor values —
update this table once wired, and update
`firmware/hal/display/epaper.py::set_backlight()` (currently a stub) to
drive them.

## Power / enclosure notes (not wiring, kept here for context)

- No battery in the enclosure.
- Bottom face: cable pass-through, mounting, joystick cable (external
  joystick module, not enclosure-mounted), power connector.
- Magnetic dock: 4× 6×2mm magnets, bracket glued to the OTA tube (16" tube
  only for now), matching through-holes (not pockets) in the enclosure back
  — required as genuine through-holes because JLC3DP prints unattended (no
  manual pause-to-insert-magnet step).
