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
| 1 | **Encoder-up stand-in** (`ENC_UP`) wherever `_move()` is used — see below; also T9 letter entry ("abc") in SmartSearch, where `_move()` isn't in play |
| 3 | **Force a full refresh** of the current screen (no state change) — see below; also T9 letter entry ("ghi") in SmartSearch, where it's excluded |
| 2 | Jog Up — only handled on `ALIGN_JOG`/`TRACK` (see `firmware/ui/controller.py`'s `JOG_DIRECTIONS`/`_jog()`); a plain digit everywhere else |
| 4 | Jog Left — same screens |
| 6 | Jog Right — same screens |
| 8 | Jog Down — same screens |
| 7 | Jog speed (opens speed adjust) on IDLE/TRACK/ALIGN_JOG; **encoder-down stand-in** (`ENC_DOWN`) everywhere else `_move()` is used |
| 5 | **Encoder-push stand-in** (`ENC_PUSH`) everywhere — see below; also T9 letter entry ("mno") in SmartSearch, where it's excluded |
| 9 | **Back, one level — everywhere except inside SmartSearch text entry** (see below) |
| 0 | digit "0" / T9 letter entry |
| FN2 | reserved outside SmartSearch (home-screen easter egg); **inside SmartSearch: cancel/back out** |
| BKSP | delete last character (text entry) |
| Encoder rotate | scroll (menus, lists) |
| Encoder push | open / select / confirm |

Keypad "1"/"7"/"5" as encoder stand-ins ("1"/"7" in
`ControllerUI._move()`, "5" at the top of `handle()`) are a temporary
stopgap for the KY-040 rotary encoder's unreliable rotation decode (see
`firmware/hal/input/encoder.py`'s module docstring) — "1"/"7" are a
vertical pair on the keypad's left column (up/down), "5" is the center
"OK" key below the 2/4/6/8 jog directions (select/confirm), together
usable for full menu/list navigation whenever the real encoder
misbehaves. "7" only falls back to `ENC_DOWN` outside IDLE, where it's
already bound to opening speed adjust; "5" falls back to `ENC_PUSH`
everywhere except TYPE (SmartSearch), where it's still a T9 letter key.

Keypad "3" (`handle()`, top of the method) redraws the current screen
with a forced full refresh — the only way to clear any ghosting left
over from partial refreshes, since nothing clears it automatically.
Excluded on TYPE, where it's still a T9 letter key ("ghi").

Scrolling (`_move()`) always draws a fast partial refresh, never a
forced full one, however many consecutive scrolls happen — only keypad
"3" clears accumulated ghosting. A fixed "every Nth scroll is full"
cadence, and later an idle flush shortly after scrolling stopped, both
used to force one automatically; both were reported on hardware as an
unwanted interruption to otherwise-smooth scrolling and were removed.

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
| `5001` | Switch Wi-Fi network | functional — picks between the Primary and Secondary Wi-Fi slots, runs `install/wifi-switch.sh` via sudo, and persists `settings.wifi_active_slot`. Configuring each slot's SSID/password is done in the Web UI's System page, not here — saving Secondary there only stores it, it never connects on its own, since it's often set up somewhere its network isn't in range yet; switching to it here is the explicit step that actually activates it, and selecting it before it's configured shows an error instead of attempting the switch. "Primary" shown as "(unknown)" is normal, not broken — it's only ever a known SSID if this device's Wi-Fi was configured through `/setup`; switching back to it never depends on knowing that, since it just means "stop overriding with Secondary" (see `install/wifi-switch.sh`'s own comment) |
| `5555` | Select mount driver | functional — opens driver selection (currently one option: Sky-Watcher Alt-Az GTi) |
| `9600` | Select communication interface | functional — opens interface selection: RJ12 direct to mount, or Bluetooth (SynScan); persists to `settings.mount_interface`. Picking Bluetooth for the first time (nothing paired yet) instead scans and lets you pick the module off a list — see `9601` below. Actually pointing the INDI driver at `/dev/rfcomm0` still needs `firmware/indi/client.py` wired up (not yet — same v0 gap as `get_status`/`sync`/`goto`/`park` below) |
| `9601` | Re-pair Bluetooth mount | functional — scans for nearby Bluetooth devices (~8s, `install/bluetooth-mount.sh scan` via sudo) and shows them on a pick list; selecting one pairs/trusts it and binds it to a persistent `/dev/rfcomm0` (`japyscope-rfcomm-mount.service`), then sets `settings.mount_interface` to `bluetooth`. Covers both the first pairing (also reachable via `9600`) and re-pairing a different/replaced module later. If pairing fails — most likely a module that needs a PIN this flow can't supply — it says so and falls back to pairing once manually over SSH (`sudo japyscope-bluetooth-mount pair <MAC>`), after which `9600`/`9601` find it already paired |
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

- Default: a random 4-digit code generated per device on first boot
  (`shared.db`'s `init_db()`), stored as a salted PBKDF2 hash in
  `settings.sudo_password`. It used to be the hardcoded literal `1234` —
  the same password on every device, visible to anyone reading this repo
  — which is no longer the case (see jan-tdy/japyscope-remote#35).
- While still unchanged, the Menu entry itself reads "Sudo Password
  (default!)" every time the screen is opened, driven by
  `settings.sudo_password_is_default` reading `1` — a nag the owner can't
  miss by only seeing once, nudging them to pick their own.
- Set via Menu → Sudo Password (same rotary-dial 4-digit entry as Dev Tools codes, and no need to know the current code first) — this also clears the reminder and erases the generated code from `state`.
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
new failure modes are found during bring-up. All of these are journal-only
except `SYS-980` and `SYS-970`, which also get painted straight to the
e-ink panel (see their rows below for why).

| Code | Meaning | Where logged |
|---|---|---|
| `INDI-001` | indiserver failed to start (binary not found / bad driver name) | `japyscope-app` journal |
| `INDI-002` | indiserver started but mount driver never reported CONNECTED | `japyscope-app` journal |
| `INDI-003` | indiserver crashed and was restarted by the watchdog | `japyscope-app` journal |
| `INDI-004` | Manual jog (keypad 2/4/6/8 or joystick, `ALIGN_JOG`/`TRACK`) requested but `IndiClient.jog()` isn't wired up against the live driver yet | `japyscope-app` journal |
| `OTA-001` | update check failed (no internet / GitHub API unreachable) | `japyscope-app` journal, Web UI → System |
| `OTA-002` | downloaded release failed checksum verification | same |
| `OTA-003` | new release failed its post-install health check, rolled back | same |
| `WIFI-001` | Joining a configured Wi-Fi network failed — either the initial AP-mode setup join (`/setup`) or configuring the secondary network (Web UI → System) | `japyscope-webui` journal, Web UI → Diagnostics |
| `SEARCH-001` | SmartSearch online lookup timed out / no internet — fell back to local catalogs only | `japyscope-app` journal |
| `SYS-001` | Daily `apt-get update`/`upgrade` step failed (best-effort — never blocks the JapyScope release step) | `japyscope-update` journal |
| `SYS-980` | A fatal OS/storage-level error (e.g. the SD card going read-only mid-run, confirmed during bring-up — see "Filesystem went read-only" in `docs/TROUBLESHOOTING.md`) crashed `japyscope-app` entirely | `japyscope-app` journal **and painted directly to the e-ink panel** (`firmware/main.py`'s `_show_fatal_error`) — this is one of the two codes that bypass the normal DB-backed UI, since it can fire exactly when the DB itself is unwritable, and the panel keeps showing it with no power if the Pi then crash-loops |
| `SYS-970` | Any other unhandled exception crashed `japyscope-app` (a bug, not a startup or OS/storage failure — those get their own codes above) — confirmed on hardware as a silent crash with nothing on the panel | `japyscope-app` journal (with full traceback) **and painted directly to the e-ink panel** — same `_show_fatal_error` mechanism as `SYS-980`, as a last resort so an unattended device never just goes blank |
| `SYS-990` | `systemctl poweroff` itself (requested via Menu → System → Power off, or the PARKED screen's "Power off") failed to run | `japyscope-app` journal only — not painted; the panel is left on the SHUTDOWN screen regardless, since the user already asked to power off |
