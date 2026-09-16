# JapyScope Remote — Wiring & Pinout

Single source of truth for how the Raspberry Pi Zero W is wired. Update this
file (not a second copy elsewhere) as each build phase confirms real pins.

Status: **Fáza 0 / 1beta** — jumper-wire prototype, most pin numbers below
are the firmware's current defaults (`firmware/hal/*/keypad.py`,
`firmware/hal/display/epaper.py`), not yet verified against a soldered
board. Cross-check before trusting a pin.

## Mount connection (RJ12, not RJ45)

The controller connects directly to the mount's **RJ12** "Hand Control" port
— this bypasses the stock SynScan hand controller entirely and speaks the
Sky-Watcher Motor Controller Command Set protocol directly (same principle
as an EQDIRECT cable).

- Mount side TTL is **5V**, Pi Zero W GPIO is **3.3V** → a logic-level
  shifter is required between the two (already in hand per project notes).
- Pi Zero W UART (`/dev/serial0`) ↔ level shifter ↔ RJ12 pins carrying
  TX/RX/GND. **TODO**: confirm exact RJ12 pin-to-signal mapping once the cut
  Ethernet cable is wired through the level shifter (Fáza 1beta step).

## Keypad (3×4 matrix, stock SparkFun COM-14662)

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

| Signal | BCM pin |
|---|---|
| CLK | 16 |
| DT | 12 |
| SW (push) | 7 |

Also needs a printed D-shaft knob for the KY-040 shaft (JLC3DP, per project
notes) — not a wiring item, tracked here as a reminder for the enclosure BOM.

## Display (e-ink, SPI) — panel not finalized

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
**Switching mechanism still TBD** (confirmed: no MOSFET, contrary to an
earlier assumption) — update this section once the driving circuit is
decided; `firmware/hal/display/epaper.py::set_backlight()` is stubbed
pending this.

## Power / enclosure notes (not wiring, kept here for context)

- No battery in the enclosure.
- Bottom face: cable pass-through, mounting, joystick cable (external
  joystick module, not enclosure-mounted), power connector.
- Magnetic dock: 4× 6×2mm magnets, bracket glued to the OTA tube (16" tube
  only for now), matching through-holes (not pockets) in the enclosure back
  — required as genuine through-holes because JLC3DP prints unattended (no
  manual pause-to-insert-magnet step).
