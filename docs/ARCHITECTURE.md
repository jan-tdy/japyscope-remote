# JapyScope Remote — Firmware v0 Architecture & Handoff

This is the living architecture doc for JapyScope Remote: a custom
Raspberry Pi Zero W hand controller that replaces the stock SynScan hand
controller on Ján's Sky-Watcher Flextube 400P Dobson mount. It connects
directly to the mount's **RJ12** "Hand Control" port (via a 3.3V↔5V
logic-level shifter) and drives INDI's existing Sky-Watcher Alt-Az mount
driver directly — no custom motor-protocol code needed.

No hardware exists yet (still Fáza 0/1beta), but firmware v0 is being built
now so installation, OTA updates, and INDI process management are already
solved before the first prototype is wired up. The UX for both the hand
controller and its companion Web UI is fully defined by the interactive
HTML/JS mockup published at the root of this site (`docs/index.html` —
open it via GitHub Pages) plus the decisions below, which supersede the
mockup where they conflict with it.

## Confirmed decisions

| Area | Decision |
|---|---|
| Target HW | Raspberry Pi Zero W (armv6 — **only Raspberry Pi OS Bullseye Lite (32-bit) is usable**; Bookworm dropped armv6 support entirely) |
| Mount connector | **RJ12** (not RJ45) |
| Display | **Not finalized** — leaning 2.13" e-paper but nothing bought yet, 4.26" not ruled out. Firmware never hardcodes a resolution — see `firmware/hal/display/profiles.py` |
| Input | 3×4 matrix keypad (stock SparkFun COM-14662, sticker legends only) + KY-040 rotary encoder |
| Install | An install script (`install/install.sh`, **not yet written**, see Remaining work) run on a clean Raspberry Pi OS Bullseye Lite image — not a prebuilt SD image, not Docker, not a PyQt5 desktop installer (considered and rejected as overkill — a `.sh` script + `docs/INSTALL.md` is enough) |
| INDI management | The firmware app spawns/owns `indiserver` as a subprocess (Ekos-style) — implemented in `firmware/indi/manager.py` |
| OTA updates | GitHub Releases-based update with rollback (**not yet written**, see Remaining work): poll the repo's Releases API, download a release tarball, verify it, install to a new versioned directory, health-check after restart, roll back the `current` symlink on failure |
| Firmware language | Python 3 |
| Web UI stack | Flask + Jinja2, server-rendered plain HTML (no JS framework) |
| Repo layout | Monorepo (this repo) |
| License | MIT — every dependency must be MIT/BSD/Apache/LGPL-compatible; INDI/PyIndi-client are LGPL, used as a separate process + Python bindings (not statically linked), so no conflict; avoid GPL-only e-ink demo code |

## UX/behavior changes vs. the `docs/index.html` mockup

The mockup was built first to nail down interaction design and is kept
as-is for reference/demo purposes, but the following changed after it was
built (16.9) and **the real firmware must implement the updated behavior,
not the mockup's**:

- **Multiple custom catalogs** — not a single flat "My Catalog". `shared/db.py`'s `CatalogRepo` already supports many named catalogs, each with its own items. The controller's Catalog menu must become Catalog → pick a catalog → pick an object (two list levels, not one).
- **Web UI live position is opt-in** — the Status page must NOT auto-poll/stream RA/Dec/Alt/Az on load; add an explicit "Start live view" control the user clicks. Until clicked, Status shows only last-known static values (from `shared.db.StateRepo`).
- **Startup park confirmation → encoder sync** — on boot, before going to IDLE/PARKED, ask "Are you in the park position? Yes/No". Yes → proceed as parked. No → run an INDI **Sync** on the current position before continuing (mount has no absolute encoders, so position is lost across power cycles). New boot-time state `BOOT_PARK_CHECK` between `BOOT` and `IDLE`/`PARKED`.
- **T9 keymap fix in SmartSearch** — see `docs/CODES.md` for the exact mapping. Summary: "9" becomes a normal T9 letter key (w/x/y/z/9) *only inside SmartSearch*, and **FN2** takes over as "cancel/back out of SmartSearch" for that screen. Everywhere else, "9" keeps meaning "back, never an action."
- **SmartSearch queries the internet** — this is SmartSearch's whole point: resolve object names against an online astronomical database (recommended: SIMBAD/Sesame name resolver — free, no API key, same one KStars/Stellarium use) in addition to local catalogs, so a newly-discovered/variable star not in any local list can still be found. Must degrade gracefully offline: fall back to local-only results with a note (see `CODES.md`'s `SEARCH-001`), not hang or fail the whole search.

## Repository layout

```
japyscope-remote/
  firmware/
    hal/
      display/       # DONE — profiles.py, base.py, simulator.py, epaper.py (stub pending real panel)
      input/          # DONE — keys.py, base.py, simulator.py, keypad.py
    indi/
      manager.py      # DONE — indiserver subprocess lifecycle + watchdog
      client.py       # STUB — PyIndi-client wrapper, methods raise NotImplementedError pending real hardware
    ui/                # NOT STARTED — screen/state-machine logic ported from docs/index.html
    main.py             # NOT STARTED — entrypoint wiring HAL + indi + ui together
  webui/                # NOT STARTED — Flask app + templates
  shared/
    db.py               # DONE — SQLite models: catalogs (multi-catalog), settings, state, access_codes
  install/
    install.sh           # NOT STARTED
    update.py             # NOT STARTED
    systemd/               # NOT STARTED
  docs/                     # this file, WIRING.md, CODES.md — DONE; INSTALL.md/UPDATE.md/TROUBLESHOOTING.md — STUBS pending install.sh/update.py; index.html — the mockup, DONE
  tests/                     # DONE for what exists (db, display HAL, indi manager); needs more once ui/webui/install exist
```

## Remaining work for v0 (handoff)

This pass deliberately stopped at the infrastructure layer (HAL, INDI
process management, data model, docs) with working tests, and left the
following for a follow-up session — everything below has enough context in
this doc, `docs/CODES.md`, and `docs/WIRING.md` to be picked up cold:

1. **`firmware/ui/`** — port every screen from `docs/index.html`'s JS state
   machine (`st.screen` switch in the mockup's `<script>`) to Python,
   driven by `firmware.hal.display.DisplayHAL` / `firmware.hal.input.InputHAL`
   from this pass. Include the four behavior changes listed above — they are
   not in the mockup's JS and must be added fresh, not ported.
2. **`firmware/main.py`** — argument parsing (`--simulate`), constructs
   `make_display()` / `make_input()` / `IndiServerManager` / the `ui` state
   machine, runs the main loop, handles clean shutdown (stop indiserver).
3. **`webui/`** — Flask app implementing every page in `docs/index.html`'s
   `#tab-webui` (Wi-Fi AP setup, code-gated login with 5-attempt lockout,
   status with opt-in live position, multi-catalog CRUD + CSV import,
   settings, diagnostics, system), backed by `shared/db.py`.
4. **`install/install.sh`** — bootstrap on a clean Raspberry Pi OS Bullseye
   Lite image: apt install INDI (confirm exact package/driver binary name
   for the Sky-Watcher Alt-Az driver — `firmware/indi/manager.py`'s
   `DEFAULT_DRIVER_BINARY` is a placeholder), Python deps
   (`requirements.txt`), venv, systemd units.
5. **`install/systemd/*.service`** — `japyscope-app.service`,
   `japyscope-webui.service`, and a `japyscope-splash.service` oneshot that
   draws a static boot logo via partial refresh (per project memory: no
   kernel-level boot splash, e-ink is too slow for that).
6. **`install/update.py`** — OTA per the table above: GitHub Releases API →
   download → verify → versioned install dir → symlink flip → health-check
   → rollback on failure. Triggered from the controller's menu and/or a
   systemd timer.
7. **`docs/INSTALL.md`, `docs/UPDATE.md`, `docs/TROUBLESHOOTING.md`** —
   write these alongside items 4–6 respectively, once the actual scripts
   exist (writing them earlier would just be speculation).
8. **Deferred beyond v0 entirely**: a polished end-user manual as a PDF
   (use the PDF skill once on-device flows are stable).

## Verification

1. `firmware/main.py --simulate` (once item 2 above exists) running the full
   controller state machine on a dev machine.
2. `webui/app.py` run locally (Flask dev server) against a SQLite fixture.
3. `install/install.sh` and `install/update.py` tested against a Raspberry
   Pi OS Bullseye Lite image (QEMU or a spare Pi) before trusting them on
   real Pi Zero W hardware.
4. `docs/index.html` opened via the GitHub Pages URL to sanity-check current
   UX decisions (noting it does **not** reflect the behavior changes above —
   it's kept as the original interaction-design reference).
5. `docs/WIRING.md` cross-checked against the physical build at each Fáza.
6. `pytest` for everything already covered (`tests/`) — 12 tests passing as
   of this pass (`shared/db.py`, display HAL, INDI manager lifecycle).
