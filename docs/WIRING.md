---
layout: default
title: Wiring and pinout
permalink: /wiring/
---

# JapyScope Remote — Wiring & Pinout

Single source of truth for how the Raspberry Pi Zero W is wired. Update this
file (not a second copy elsewhere) as each build phase confirms real pins.

## Mount connection (RJ12)
{: #mount-connection}

The controller connects directly to the mount's **RJ12** "Hand Control" port(Also supports Wi-Fi, see below) and speaks the
Sky-Watcher Motor Controller Command Set protocol directly (same principle
as an EQDIRECT cable).

- Mount side TTL is **5V**, Pi Zero W GPIO is **3.3V** → a logic-level
  shifter is required between the two (already in hand per project notes).
- Pi Zero W UART (`/dev/serial0`) ↔ level shifter ↔ RJ12 pins carrying
  TX/RX/GND.

| RJ12 pin | Signal | Via | Pi pin |
|---|---|---|---|
| 1 | EXPD+ | — | not wired |
| 2 | data | shifter HV1 → LV1 | GPIO14 (TXD) or GPIO15 (RXD) |
| 3 | GND | shifter HV GND + LV GND (shared) | GND |
| 4 | EXPD-/NC | — | not wired |
| 5 | data | shifter HV2 → LV2 | GPIO15 (RXD) or GPIO14 (TXD) |
| 6 | +12V | — | **never connect to shifter or Pi** |

Shifter HV-VCC → Pi 5V (physical pin 2/4). Shifter LV-VCC → Pi 3V3
(physical pin 1). TX/RX direction is the only ambiguity and swapping it is
harmless — if the mount doesn't respond, swap pins 2/5 at the Pi end.

Unused: RJ12 pins 1 (white), 4 (yellow), 6 (red) — trim short and insulate,
do not connect pin 6 (+12V) to the level shifter or Pi.

### Optional: WiFi (SynScan) instead of RJ12/Bluetooth

Mounts whose built-in module exposes Sky-Watcher's SynScan WiFi adapter
(the same ESP-WROOM-style chip used across Sky-Watcher's WiFi products —
AZ-GTi, Freedom-Find bases, the standalone SynScan WiFi Adapter) can be
reached over the network instead of RJ12 or Bluetooth. Unlike Bluetooth,
this one **is** wired end-to-end at the INDI level: `indi_skywatcherAltAzMount`
has built-in support for a network connection (the standard INDI
`Connection::TCP` plugin), and the module itself is just a transparent
serial↔UDP bridge for the same SynScan protocol RJ12 carries (confirmed
against independent open-source reimplementations of it, e.g.
[`emard/esp32synscan`](https://github.com/emard/esp32synscan)) — no custom
protocol work needed.

1. Find the module's IP: `192.168.4.1` if it's in its own Access Point
   mode (its default `SynScan_WiFi_xxxx` network), or its DHCP-assigned
   LAN IP if it's in Station mode joined to your own WiFi (check your
   router's client list).
2. Save that IP in the Web UI → System → "Mount WiFi (SynScan)".
3. Dev Tools code `9600` → WiFi — this runs `indi_setprop` to set the
   driver's `CONNECTION_MODE`/`DEVICE_ADDRESS` properties to that IP over
   UDP port 11880 and connects (`firmware/ui/controller.py`'s
   `_connect_mount_wifi()`).

The device name (`"Skywatcher Alt-Az"` — note the lowercase "w", not
"SkyWatcher") and property names (`CONNECTION_MODE`/`DEVICE_ADDRESS`/
`CONNECTION`) are confirmed against the driver's actual upstream source
(`indilib/indi`, `drivers/telescope/skywatcherAPIMount.cpp` — this is
what the `indi_skywatcherAltAzMount` binary is built from — plus the
standard `INDI::Connection::TCP` plugin it uses, `libs/indibase/
connectionplugins/connectiontcp.cpp`), not just guessed from naming
convention.

Never run the SynScan Pro phone app and this at the same time against the
same mount, they'll fight over the same connection.

## Keypad (3×4 matrix, stock SparkFun COM-14662)
{: #keypad}

Stickers-only key legend.
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

## Rotary encoder (KY-040, Adafruit in future)
{: #rotary-encoder}

| Signal | BCM pin |
|---|---|
| CLK | 16 |
| DT | 12 |
| SW (push) | 7 |

## External joystick (optional, KY-023-style)
{: #joystick}

Genuinely optional accessory, not enclosure-mounted — an external dual-axis
analog joystick module (VRx/VRy + SW push button) on its own cable through
the bottom-face pass-through (see "Power / enclosure notes" below), enabled
in the Web UI Settings page's Joystick section (`shared.db`'s
`joystick_enabled`, default off). Firmware never even opens the I2C bus for
it unless that setting is on — see `firmware/hal/input/joystick.py`.

The Pi Zero W has no native analog input, so VRx/VRy go through an ADS1115
I2C ADC rather than straight into GPIO. SW is a plain digital GPIO input,
same idea as the KY-040's own push button above.

| Signal | Via | Pi pin |
|---|---|---|
| VRx | ADS1115 AIN0 | — |
| VRy | ADS1115 AIN1 | — |
| ADS1115 SDA | I2C1 | GPIO2 (physical pin 3) |
| ADS1115 SCL | I2C1 | GPIO3 (physical pin 5) |
| ADS1115 VDD/GND | — | 3V3 / GND |
| ADS1115 ADDR | tied to GND (address `0x48`) | GND |
| SW (push) | direct GPIO, `PUD_UP` | GPIO27 (physical pin 13) |

The I2C interface itself needs enabling (`raspi-config` or
`/boot/firmware/config.txt`'s `dtparam=i2c_arm=on`) — a manual bring-up
step for now, same as SPI. The joystick's Y-axis and push button reuse the
same event codes as the KY-040 rotary encoder above (`ENC_UP`/`ENC_DOWN`/
`ENC_PUSH`), so it's a drop-in alternative for menu navigation; its X-axis
(`JOY_LEFT`/`JOY_RIGHT`, unique to it) drives manual N/S/E/W jogging — see
`docs/CODES.md`.

## Display (e-ink, SPI) — 2.13" confirmed, not yet soldered
{: #display}

See `docs/ARCHITECTURE.md` for the confirmed 2.13"/SSD1680 pick (4.26" kept
as a fallback profile). SPI wiring is the same regardless of panel size
(`firmware/hal/display/epaper.py`):

| Signal | BCM pin | Notes |
|---|---|---|
| DIN (MOSI) | SPI0 MOSI (10) | hardware SPI |
| CLK (SCLK) | SPI0 SCLK (11) | hardware SPI |
| CS | SPI0 CE0 (8) | hardware SPI |
| DC | 25 | data/command select |
| RST | 17 | reset |
| BUSY | 24 | input, panel-busy signal |

## Backlight (custom RGB edge-lighting)

PLANNED FOR DEPRECATION/CHANGE
