---
layout: default
title: On-device codes
permalink: /codes/
---

# JapyScope Remote — Codes Reference

Living document — extend freely as new codes/diagnostics are introduced.
Covers every "enter a code" flow on the device plus a maintainer-facing
error/status code list for support and troubleshooting.

## Key map (physical 3×4 keypad + KY-040 encoder + optional external joystick)

| Key | Meaning |
|---|---|
| 1, 3 | unused (reserved) |
| 2 | Jog Up — only handled on `ALIGN_JOG`/`TRACK` (see `firmware/ui/controller.py`'s `JOG_DIRECTIONS`/`_jog()`); a plain digit everywhere else |
| 4 | Jog Left — same screens |
| 6 | Jog Right — same screens |
| 8 | Jog Down — same screens |
| 7 | Jog speed (opens speed adjust) |
| 9 | **Back, one level — everywhere except inside SmartSearch text entry** (see below) |
| 0 | digit "0" / T9 letter entry |
| FN2 | reserved outside SmartSearch (home-screen easter egg); **inside SmartSearch: cancel/back out** |
| BKSP | delete last character (text entry) |
| Encoder rotate | scroll (menus, lists) |
| Encoder push | open / select / confirm |

### External joystick (optional — `docs/WIRING.md`)

A KY-023-style dual-axis joystick module, if connected (`shared.db`'s
`joystick_enabled`), is a second, independent source of the very same
events above — see `firmware/hal/input/joystick.py` and `keys.py`:

| Joystick input | Reuses / adds |
|---|---|
| Y-axis up/down | `ENC_UP`/`ENC_DOWN` — same as rotating the encoder (scroll menus/lists) |
| Push button | `ENC_PUSH` — same as pressing the encoder (select/confirm) |
| X-axis left/right | `JOY_LEFT`/`JOY_RIGHT` (new, joystick-only) — Jog Left/Right on `ALIGN_JOG`/`TRACK`, same as keypad 4/6 |

It's a drop-in alternative to the encoder for navigation, and the more
natural way to do the 4-directional jog above (keypad 2/4/6/8 double as
digit-entry T9 keys everywhere else; the joystick's axes never do).

**No diagonal jog**: a push deflected on both axes at once (e.g. up-and-right)
is deliberately treated as no input rather than snapped to one axis — the
mount only jogs one cardinal direction (N/S/E/W) at a time. Push the stick
cleanly toward one direction (see `firmware/hal/input/joystick.py`'s
`_direction_from_axes()`).

### SmartSearch T9 exception

Everywhere else in the system, "9" always means "back, never an action" —
this is a deliberate, load-bearing rule (state machine code in
`firmware/ui/` relies on it). **Inside the SmartSearch/TYPE screen only**,
this is flipped: "9" is a normal T9 letter key (classic-phone layout —
`w/x/y/z/9`), and **FN2** becomes "cancel out of SmartSearch" instead. This
was a deliberate v0 decision (16.9) to match old-phone muscle memory,
overriding the original mockup's design. Do not "fix" this back without
re-confirming with Ján — it looks inconsistent but is intentional.

Full T9 map (`firmware/hal/input/keys.py` order, letters per digit):

| Key | Letters |
|---|---|
| 1 | a b c |
| 2 | d e f |
| 3 | g h i |
| 4 | j k l |
| 5 | m n o |
| 6 | p q r s |
| 7 | t u v |
| 8 | w x y z |
| 9 | w x y z — **SmartSearch-only exception** (everywhere else, 9 = back); yes, this duplicates key 8's letters, so w/x/y/z can be typed via either key — that's intentional, the point is giving 9 the "old phone" wxyz muscle memory without disturbing keys 1–8 |
| 0 | 0 (digit only, no letters) |

## Dev Tools codes

4-digit code entered via rotate-per-digit (Home → Dev Tools). The real
implementation lives in `firmware/ui/controller.py` (`ControllerUI._devtools_code()`)
— that's what runs on the device. `docs/mockup.html`'s `handleDevtools()`
is a browser-only prototype of the same behavior, kept in sync for
prototyping/demo purposes, but it is **not** a substitute for the firmware
implementation and a code must not be marked functional in this table
until it actually works in `firmware/ui/`. **Add new Dev Tools codes
here as they're introduced**, and wire them into both
`firmware/ui/controller.py` and the mockup — don't scatter magic numbers
in `firmware/ui/` without a matching entry in this table.

| Code | Action | Notes |
|---|---|---|
| `0000` | Exit Dev Tools | |
| `0022` | Set repo | functional — opens repo selection (currently one option: `jan-tdy/japyscope-remote`); persists to `settings.update_repo`, read by `install/update.py` |
| `0033` | Set update channel | functional — opens channel selection, Stable only / Stable + prereleases; persists to `settings.update_channel`, read by `install/update.py` (prerelease channel lists `/releases` and skips drafts instead of hitting `/releases/latest`) |
| `0044` | SSH | functional — runs `systemctl enable --now ssh`, then shows the result plus IP/hostname and login user |
| `1001` | Enable more INDI drivers (camera, focuser, etc.) | **coming soon** — placeholder message only, no drivers selectable yet |
| `1111` | Restart INDI server | functional — calls `IndiServerManager.restart()` (via `ControllerUI.indi_manager`, wired from `firmware/main.py`); shows "unavailable" in `--simulate` mode, which has no managed indiserver |
| `1234` | Show system info | functional — IP/hostname, uptime (`/proc/uptime`), INDI connection status (no fake version string — nothing exposes a real INDI version yet) |
| `5000` | Launch Wi-Fi setup wizard | functional — same flow as a factory-reset Wi-Fi join |
| `5555` | Select mount driver | functional — opens driver selection (currently one option: Sky-Watcher Alt-Az GTi) |
| `9600` | Select communication interface | functional — opens interface selection (currently one option: RJ12 direct to mount) |
| `9955` | Run custom script | functional — lists `.sh` scripts found in `{homepath}/custom` (`JAPYSCOPE_CUSTOM_SCRIPTS_DIR` env var overrides the directory) and runs the selected one via `/bin/sh`, fire-and-forget |
| `9999` | Easter egg (astronomer/Moon joke) | functional, cosmetic only |
| `4200` | Easter egg ("42.") | functional, cosmetic only |
| `1957` | Easter egg (Sputnik) | functional, cosmetic only |
| `0905` | Easter egg ("Protocol 09: the code stays free — JapySoft") | functional, cosmetic only |
| anything else | Shows "Invalid code." | |

None of the above currently require the sudo password — add the
requirement here (and enforce it in `firmware/ui/`) the day a Dev Tools
code becomes genuinely destructive (e.g. a future factory-reset code).
`9955` runs arbitrary local `.sh` files, but only ones the device owner
already placed in `{homepath}/custom` themselves — same trust level as
having a shell on the device, not a remote-execution surface.

## Sudo password

- Default: `1234` (factory default, stored as a salted PBKDF2 hash in
  `shared.db` `settings.sudo_password`).
- Set via Menu → Sudo Password (same rotary-dial 4-digit entry as Dev Tools codes).
- Intended to guard destructive Dev Tools actions — none of the current codes need it (see table above), since none are destructive yet.
- **Not a real security boundary** — same spirit as the Web UI access code below: a deterrent, not encryption-grade auth. Don't build anything safety-critical behind it without upgrading the mechanism first.

## Web UI access code

- Dynamic, generated from the controller's Menu → Wi-Fi / Web Access screen, shown on the e-ink display with a countdown.
- Entered on the Web UI's login page (`/`) to gain access.
- 5 wrong attempts → 30s lockout (see mockup `login-msg` flow, to be ported to `webui/app.py`).
- Deliberately not high-security — same LAN-only, deterrent-level design as the sudo password.

## Maintainer-facing status / error codes (new, beyond the mockup)

These don't exist in the HTML mockup — added here for `docs/TROUBLESHOOTING.md`
and systemd journal greps once the firmware app has real logging. Extend as
new failure modes are found during bring-up.

| Code | Meaning | Where logged |
|---|---|---|
| `INDI-001` | indiserver failed to start (binary not found / bad driver name) | `japyscope-app` journal |
| `INDI-002` | indiserver started but mount driver never reported CONNECTED | `japyscope-app` journal |
| `INDI-003` | indiserver crashed and was restarted by the watchdog | `japyscope-app` journal |
| `INDI-004` | Manual jog (keypad 2/4/6/8 or joystick, `ALIGN_JOG`/`TRACK`) requested but `IndiClient.jog()` isn't wired up against the live driver yet | `japyscope-app` journal |
| `OTA-001` | update check failed (no internet / GitHub API unreachable) | `japyscope-app` journal, Web UI → System |
| `OTA-002` | downloaded release failed checksum verification | same |
| `OTA-003` | new release failed its post-install health check, rolled back | same |
| `WIFI-001` | AP-mode setup hotspot failed to start | `hostapd`/`dnsmasq` journal |
| `SEARCH-001` | SmartSearch online lookup timed out / no internet — fell back to local catalogs only | `japyscope-app` journal |
| `SYS-001` | Daily `apt-get update`/`upgrade` step failed (best-effort — never blocks the JapyScope release step) | `japyscope-update` journal |
