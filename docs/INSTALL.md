# Install manual — placeholder

Not written yet — `install/install.sh` doesn't exist yet either (see
[ARCHITECTURE.md → Remaining work, item 4](ARCHITECTURE.md#remaining-work-for-v0-handoff)).
This file should be written alongside that script, not before it, so it
documents what the script actually does rather than a guess.

Known constraints to build against:

- Raspberry Pi Zero W is armv6 — flash **Raspberry Pi OS Bullseye Lite
  (32-bit)**, not the current default image (Bookworm dropped armv6
  support).
- Mount connects via **RJ12** through a 3.3V↔5V level shifter — see
  [WIRING.md](WIRING.md).
- No prebuilt SD image, no Docker, no desktop installer — a plain shell
  script run on a clean OS image.
