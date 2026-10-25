---
layout: default
title: On-device codes
permalink: /codes/
---

# DevTools codes, Key Map, etc.

## Key map (physical 3×4 keypad + KY-040 encoder + optional external joystick)

| Key | Meaning |
|---|---|
| 1 | Menu Up, "abc" in SmartSearch
| 3 | Force full refresh, "ghi" in SmartSearch |
| 2 | Jog Up, "def" in SmartSearch |
| 4 | Jog Left, "jkl" in SmartSearch |
| 6 | Jog Right, "pqrs" in SmartSearch |
| 8 | Jog Down, "wxyz" in SmartSearch |
| 7 | Menu Down, Jog speed, "tuv" in SmartSearch |
| 5 | OK, "mno" in SmartSearch |
| 9 | Back, "wxyz" in SmartSearch |
| 0 | digit "0" |
| FN2 | inside SmartSearch: cancel/back out |
| BKSP | delete last character in SmartSearch |
| Encoder rotate | scroll (menus, lists) |
| Encoder push | open / select / confirm |

### SmartSearch T9 exception

**Inside the SmartSearch/TYPE screen only**, this is flipped: "9" is a normal T9 letter key (classic-phone layout —
`w/x/y/z`), and **FN2** becomes "cancel out of SmartSearch" instead. 

## Full SmartSearch map

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
| 9 | w x y z |
| 0 | 0 (digit only, no letters) |

## Dev Tools codes

| Code | Action | Notes |
|---|---|---|
| `0000` | Exit Dev Tools | |
| `0022` | Set repo | opens repo selection |
| `0033` | Set update channel | opens channel selection, Stable only / Stable + prereleases |
| `0044` | SSH | runs `systemctl enable --now ssh`, then shows the result plus IP/hostname and login user |
| `1001` | Enable more INDI drivers (camera, focuser, etc.) | **coming soon** |
| `1111` | Restart INDI server | |
| `1234` | Show system info | IP/hostname, uptime (`/proc/uptime`), INDI connection status  |
| `5000` | Launch Wi-Fi setup wizard | same flow as a factory-reset Wi-Fi join |
| `5001` | Switch Wi-Fi network |  picks between the Primary and Secondary Wi-Fi slots |
| `5555` | Select mount driver | opens driver selection (currently one option: Sky-Watcher Alt-Az GTi) |
| `9600` | Select communication interface | opens interface selection: RJ12 direct to mount, Bluetooth (SynScan), WiFi (SynScan), or SynScan/Stellarium app |
| `9601` | Re-pair Bluetooth mount | scans for nearby Bluetooth devices (~8s) and shows them on a pick list |
| `9955` | Run custom script | lists `.sh` scripts found in `{homepath}/custom` |
| `9956` | Run official script | lists and runs scripts published at [`github.com/japyscope/scripts`](https://github.com/japyscope/scripts) |


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

## Maintainer-facing status / error codes

| Code | Meaning | Where logged |
|---|---|---|
| `INDI-001` | indiserver failed to start (binary not found / bad driver name) | `japyscope-app` journal |
| `INDI-002` | indiserver started but mount driver never reported CONNECTED | `japyscope-app` journal |
| `INDI-003` | indiserver crashed and was restarted by the watchdog | `japyscope-app` journal |
| `INDI-004` | Manual jog (keypad 2/4/6/8 or joystick, `ALIGN_JOG`/`TRACK`) failed — `IndiClient.jog()`'s `indi_setprop` calls (`TELESCOPE_SLEW_RATE`/`TELESCOPE_MOTION_NS`/`TELESCOPE_MOTION_WE`) couldn't reach the driver; a single missed nudge isn't worth leaving the jog screen over, so this is journal-only | `japyscope-app` journal |
| `OTA-001` | update check failed (no internet / GitHub API unreachable) | `japyscope-app` journal, Web UI → System |
| `OTA-002` | downloaded release failed checksum verification | same |
| `OTA-003` | new release failed its post-install health check, rolled back | same |

`install/update.py`'s `apply()` also writes live progress to `state`
(`update_status`/`update_phase`/`update_tag`/`update_error`), which
`firmware/ui/controller.py` polls (`_poll_update_status()`): a `checking`
/ `downloading` / `installing` screen appears on the device, but only by
taking over an already-idle screen — never by interrupting TRACK,
alignment, or anything else actually in progress, since the scheduled
daily check (`japyscope-update.timer`) fires at a random hour regardless
of what's on screen. Press `9`/push to hide it early (the update itself
keeps running either way). A finished update that restarted
`japyscope-app.service` (a real install, success or rolled-back failure)
shows its result once on the next boot, before `BOOT_PARK_CHECK`; one
that didn't (already up to date, or failed before anything was touched)
just returns the current process to `IDLE` on its own.
| `WIFI-001` | Joining a configured Wi-Fi network failed — either the initial AP-mode setup join (`/setup`) or configuring the secondary network (Web UI → System) | `japyscope-webui` journal, Web UI → Diagnostics |
| `SEARCH-001` | SmartSearch online lookup timed out / no internet — fell back to local catalogs only | `japyscope-app` journal |
| `SYS-001` | Daily `apt-get update`/`upgrade` step failed (best-effort — never blocks the JapyScope release step) | `japyscope-update` journal |
| `SYS-980` | A fatal OS/storage-level error (e.g. the SD card going read-only mid-run, confirmed during bring-up — see "Filesystem went read-only" in `docs/TROUBLESHOOTING.md`) crashed `japyscope-app` entirely | `japyscope-app` journal **and painted directly to the e-ink panel** (`firmware/main.py`'s `_show_fatal_error`) — this is one of the two codes that bypass the normal DB-backed UI, since it can fire exactly when the DB itself is unwritable, and the panel keeps showing it with no power if the Pi then crash-loops |
| `SYS-970` | Any other unhandled exception crashed `japyscope-app` (a bug, not a startup or OS/storage failure — those get their own codes above) — confirmed on hardware as a silent crash with nothing on the panel | `japyscope-app` journal (with full traceback) **and painted directly to the e-ink panel** — same `_show_fatal_error` mechanism as `SYS-980`, as a last resort so an unattended device never just goes blank |
| `SYS-990` | `systemctl poweroff` itself (requested via Menu → System → Power off, or the PARKED screen's "Power off") failed to run | `japyscope-app` journal only — not painted; the panel is left on the SHUTDOWN screen regardless, since the user already asked to power off |
