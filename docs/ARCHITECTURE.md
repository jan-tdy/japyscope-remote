---
layout: default
title: Architecture
permalink: /architecture/
---

# JapyScope Remote — Firmware v0 Architecture & Handoff

This is the living architecture doc for JapyScope Remote: a custom
Raspberry Pi Zero W hand controller that replaces the stock SynScan hand
controller on Ján's Sky-Watcher Flextube 400P Dobson mount. It connects
directly to the mount's **RJ12** "Hand Control" port (via a 3.3V↔5V
logic-level shifter) and drives INDI's existing Sky-Watcher Alt-Az mount
driver directly — no custom motor-protocol code needed.

No hardware exists yet (still Fáza 0/1beta), but firmware v0 is being built
now so installation, OTA updates, and INDI process management are implemented
before the first prototype is wired up. The UX for both the hand
controller and its companion Web UI is fully defined by the interactive
HTML/JS mockup published as part of this site (`docs/mockup.html` — open
the [Mockup tab](index.html#mockup) via GitHub Pages) plus the decisions
below, which supersede the mockup where they conflict with it.

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

## UX/behavior changes vs. the `docs/mockup.html` mockup

The mockup was built first to nail down interaction design and is kept
as-is for reference/demo purposes, but the following changed after it was
built (16.9) and **the real firmware must implement the updated behavior,
not the mockup's**:

- **Multiple custom catalogs** — not a single flat "My Catalog". `shared/db.py`'s `CatalogRepo` already supports many named catalogs, each with its own items. The controller's Catalog menu must become Catalog → pick a catalog → pick an object (two list levels, not one).
- **Web UI live position is opt-in** — the Status page must NOT auto-poll/stream RA/Dec/Alt/Az on load; add an explicit "Start live view" control the user clicks. Until clicked, Status shows only last-known static values (from `shared.db.StateRepo`).
- **Startup park confirmation → encoder sync** — on boot, before going to IDLE/PARKED, ask "Are you in the park position? Yes/No". Yes → proceed as parked. No → run an INDI **Sync** on the current position before continuing (mount has no absolute encoders, so position is lost across power cycles). New boot-time state `BOOT_PARK_CHECK` between `BOOT` and `IDLE`/`PARKED`.
- **T9 keymap fix in SmartSearch** — see `docs/CODES.md` for the exact mapping. Summary: "9" becomes a normal T9 letter key (w/x/y/z/9) *only inside SmartSearch*, and **FN2** takes over as "cancel/back out of SmartSearch" for that screen. Everywhere else, "9" keeps meaning "back, never an action."
- **SmartSearch queries the internet** — this is SmartSearch's whole point: resolve object names against an online astronomical database (recommended: SIMBAD/Sesame name resolver — free, no API key, same one KStars/Stellarium use) in addition to local catalogs, so a newly-discovered/variable star not in any local list can still be found. Must degrade gracefully offline: fall back to local-only results with a note (see `CODES.md`'s `SEARCH-001`), not hang or fail the whole search.
- **Language selection** — a new **Language** entry in Menu (between Backlight and Sudo Password) opens a list of UI languages (`firmware/ui/i18n.py`'s `LANGUAGES`); picking one persists to `settings.language` and takes effect immediately. v0 translates the highest-visibility screens only (Home, Menu, boot park check, park/unpark, About, shared footers) — anything not yet in `i18n.STRINGS` falls back to English. Not in the mockup at all.
- **External joystick support (22.9)** — an optional KY-023-style dual-axis joystick (`docs/WIRING.md`, `firmware/hal/input/joystick.py`), off by default (`shared.db`'s `joystick_enabled`, toggled on the Web UI Settings page). Its Y-axis/push button reuse the encoder's `ENC_UP`/`ENC_DOWN`/`ENC_PUSH` codes (drop-in alternative for menu navigation everywhere), and its X-axis adds `JOY_LEFT`/`JOY_RIGHT` for manual N/S/E/W jogging on `ALIGN_JOG`/`TRACK` (`firmware/ui/controller.py`'s `_jog()`), alongside the matching keypad 2/4/6/8 jog keys documented but not previously wired up in `docs/CODES.md`. `IndiClient.jog()` is a `NotImplementedError` stub like `sync`/`goto`/`park` (see "Still hardware-blocked" below) but fully functional in `--simulate` via `SimulatedIndiClient.jog()`. Not in the mockup at all.
- **Interface theme selection (23.9)** — a new **Interface Theme** entry in Menu (between Language and Sudo Password) opens a list of black/white themes (`firmware/ui/themes.py`'s `THEMES`) that only change how the *selected* row of a list/menu is marked — the panel has no other colors. `arrow` (default) prefixes it with `> `; `brackets` wraps it in `[ ]`; `invert` asks the display to swap that one row to black background/white text via `DisplayHAL.draw_lines`'s new `invert_row` parameter, honored today by `SimulatorDisplay` (ANSI reverse video) and left for the real e-paper rasterizer to honor once it exists (`firmware/hal/display/epaper.py` is still a `NotImplementedError` stub — see "Still hardware-blocked" below). Picking a theme persists to `settings.ui_theme` and takes effect immediately. Not in the mockup at all.

## Repository layout

```
japyscope-remote/
  firmware/
    hal/
      display/       # DONE — profiles.py, base.py, simulator.py, epaper.py (stub pending real panel)
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

## Implemented v0 software scope

The software-side handoff items are implemented:

1. **`firmware/ui/`** — ports the screens from `docs/mockup.html`'s JS state
   machine (`st.screen` switch in the mockup's `<script>`) to Python,
   driven by `firmware.hal.display.DisplayHAL` / `firmware.hal.input.InputHAL`
   from this pass. The behavior changes listed above are implemented in
   addition to the mockup's original states.
2. **`firmware/main.py`** — argument parsing (`--simulate`), constructs
   `make_display()` / `make_input()` / `IndiServerManager` / the `ui` state
   machine, runs the main loop, handles clean shutdown (stop indiserver).
3. **`webui/`** — Flask app implementing every page in `docs/mockup.html`'s
   `#tab-webui` (Wi-Fi AP setup, code-gated login with 5-attempt lockout,
   status with opt-in live position, multi-catalog CRUD + CSV import,
   settings, diagnostics, system), backed by `shared/db.py`.
4. **`install/install.sh`** — bootstraps a clean Raspberry Pi OS Bullseye,
   Bookworm, or Trixie Lite image: apt installs the release's `indi-bin` package, whose armhf file
   list confirms the `indi_skywatcherAltAzMount` driver binary, Python deps
   (`requirements.txt`), venv, systemd units. `--no-ap` disables the Wi-Fi
   setup hotspot's automatic boot-time fallback, for a Pi whose Wi-Fi is
   already configured — the hotspot stays installed for manual use.
5. **`install/systemd/*.service`** — includes `japyscope-app.service`,
   `japyscope-webui.service`, and a `japyscope-splash.service` oneshot that
   draws a static boot logo via partial refresh (per project memory: no
   kernel-level boot splash, e-ink is too slow for that).
6. **`install/update.py`** — implements GitHub Releases API →
   download → verify → versioned install dir → symlink flip → health-check
   → rollback on failure. Triggered by a systemd timer (and available as a
   manual command).
7. **`docs/INSTALL.md`, `docs/UPDATE.md`, `docs/TROUBLESHOOTING.md`** document
   the scripts and their operational/error-code behavior.

**Still hardware-blocked:** fill in the selected e-paper controller protocol,
map PyIndi properties against the live Sky-Watcher driver (including
`IndiClient.jog()`'s `TELESCOPE_MOTION_NS`/`TELESCOPE_MOTION_WE` switches),
confirm the physical RJ12 pinout, and exercise install/OTA on real Bullseye,
Bookworm, and Trixie Pi Zero W devices. These are not safely guessable
without the prototype.

**Deferred beyond v0 entirely**: a polished end-user manual as a PDF
   (use the PDF skill once on-device flows are stable).

## Verification

1. `python -m firmware.main --simulate` running the full
   controller state machine on a dev machine.
2. `webui/app.py` run locally (Flask dev server) against a SQLite fixture.
3. `install/install.sh` and `install/update.py` tested against a Raspberry
   Pi OS Bullseye, Bookworm, or Trixie Lite image (QEMU or a spare Pi)
   before trusting them on real Pi Zero W hardware.
4. `docs/mockup.html` opened via the GitHub Pages URL (or the Mockup tab in
   `docs/index.html`) to sanity-check current UX decisions (noting it does
   **not** reflect the behavior changes above — it's kept as the original
   interaction-design reference).
5. `docs/WIRING.md` cross-checked against the physical build at each Fáza.
6. `pytest` for covered behavior — 140 tests passing as of this pass (database,
   HAL, INDI manager, UI state machine/search, Web UI, and OTA extraction).
