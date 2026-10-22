---
layout: default
title: Architecture
permalink: /architecture/
---

# JapyScope Remote Firmware Architecture

## Confirmed decisions

| Area | Decision |
|---|---|
| Target HW | Raspberry Pi Zero W (armv6 — supports Raspberry Pi OS Lite **Bullseye, Bookworm, or Trixie, 32-bit/armhf**. Bullseye uses the legacy `wpa_supplicant`/hostapd path; Bookworm and Trixie both use NetworkManager profiles. `install.sh --no-ap` disables the setup hotspot's automatic boot-time fallback on any release, for a Pi whose Wi-Fi is already configured — the hotspot itself stays installed and can still be triggered manually.) |
| Mount connector | **RJ12** (not RJ45) |
| Display | **Confirmed: 2.13" e-paper** (250×122, SSD1680-family) — sized against the enclosure CAD (`japyscope_lid_3.step`, 20.9.2026). Firmware never hardcodes a resolution — see `firmware/hal/display/profiles.py`; 4.26" stays available as a fallback profile |
| Input | 3×4 matrix keypad (stock SparkFun COM-14662, sticker legends only) + KY-040 rotary encoder, plus an **optional** external KY-023-style dual-axis joystick (`shared.db`'s `joystick_enabled`, off by default — see `docs/WIRING.md`/`docs/CODES.md`) as a drop-in alternative to the encoder plus manual N/S/E/W jogging |
| Per-component dev/bring-up overrides | Keypad, encoder, display, backlight, mount, and (when enabled) joystick can each independently be real hardware or simulated (Web UI Settings page, `shared.db`'s `hw_sim_*` keys, read by `firmware/main.py`'s `resolve_simulation_flags()`) — e.g. keypad on real GPIO while the encoder isn't soldered yet. `--simulate` still forces everything simulated regardless (joystick included), for laptop-only dev. Requires restarting `japyscope-app.service` to take effect. |
| Install | `install/install.sh` bootstraps a clean Raspberry Pi OS Bullseye, Bookworm, or Trixie Lite image — not a prebuilt SD image, Docker, or desktop installer |
| INDI management | The firmware app spawns/owns `indiserver` as a subprocess (Ekos-style) — implemented in `firmware/indi/manager.py` |
| OTA updates | `install/update.py` polls GitHub Releases, verifies SHA-256, installs to a versioned directory, health-checks after restart, and rolls back the `current` symlink on failure. The same daily timer also runs `update.py system-upgrade` — a best-effort `apt-get update && apt-get upgrade` within the installed release's repos (never `full-upgrade`/`dist-upgrade`, never a distro upgrade) — as an independent step that can't block or roll back the app release. |
| Firmware language | Python 3 |
| Web UI stack | Flask + Jinja2, server-rendered plain HTML (no JS framework) |
| Web UI port | **8080**, all interfaces (`--host 0.0.0.0 --port 8080`, set in `install/systemd/japyscope-webui.service`) — `http://<device-ip>:8080/` normally, `http://192.168.4.1:8080/setup` while the controller is broadcasting its own Wi-Fi setup hotspot. `install/update.py`'s post-update health check also polls `http://127.0.0.1:8080/healthz` on this port. |
| Repo layout | Monorepo (this repo) |
| License | MIT — every dependency must be MIT/BSD/Apache/LGPL-compatible; INDI/PyIndi-client are LGPL, used as a separate process + Python bindings (not statically linked), so no conflict; avoid GPL-only e-ink demo code |


## Repository layout

```
japyscope-remote/
  firmware/
    hal/
      display/       # DONE — profiles.py, base.py, simulator.py, epaper.py (SSD1680 full-refresh driver + rasterizer.py, TTF text via Pillow/Roboto — see fonts/, untested against real hardware — see "Still hardware-blocked"), boot_logo.py
      input/          # DONE — keys.py, base.py, simulator.py, keypad.py, encoder.py, joystick.py (optional accessory), composite.py
    indi/
      manager.py      # DONE — indiserver subprocess lifecycle + watchdog
      client.py       # STUB — PyIndi property mapping awaits real hardware
    ui/                # DONE — Python state machine + local/online SmartSearch
    main.py             # DONE — simulation/hardware entrypoint and shutdown
  webui/                # DONE — Flask app + server-rendered templates
  shared/
    db.py               # DONE — SQLite models: catalogs (multi-catalog), settings, state, access_codes
  install/
    install.sh           # DONE — Bullseye/Bookworm/Trixie armhf bootstrap, --no-ap option
    update.py             # DONE — verified GitHub Releases OTA + rollback
    systemd/               # DONE — app/Web UI/splash/Wi-Fi AP/update units
  docs/                     # architecture, install/update/troubleshooting, wiring, mockup
  tests/                     # database, HAL, INDI, UI, Web UI, and updater coverage
```

## Implemented software scope

**TODO**: a polished end-user manual as a PDF (`docs/JapyScope_Remote_User_Manual.pdf`,
linked from the docs site's home page) covering the hand controller, the
companion Web UI, and the SSH/Dev Tools basics — kept end-user-facing on
purpose, not a substitute for this file.

