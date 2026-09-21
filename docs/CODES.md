---
layout: default
title: On-device codes
permalink: /codes/
---

# JapyScope Remote — Codes Reference

Living document — extend freely as new codes/diagnostics are introduced.
Covers every "enter a code" flow on the device plus a maintainer-facing
error/status code list for support and troubleshooting.

## Key map (physical 3×4 keypad + KY-040 encoder)

| Key | Meaning |
|---|---|
| 1, 3 | unused (reserved) |
| 2 | Jog Up (whenever the mount can move) |
| 4 | Jog Left |
| 6 | Jog Right |
| 8 | Jog Down |
| 7 | Jog speed (opens speed adjust) |
| 9 | **Back, one level — everywhere except inside SmartSearch text entry** (see below) |
| 0 | digit "0" / T9 letter entry |
| FN2 | reserved outside SmartSearch (home-screen easter egg); **inside SmartSearch: cancel/back out** |
| BKSP | delete last character (text entry) |
| Encoder rotate | scroll (menus, lists) |
| Encoder push | open / select / confirm |

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

4-digit code entered via rotate-per-digit (Home → Dev Tools). These already
exist in the mockup (`handleDevtools()` in `docs/mockup.html`) — this table
is a faithful port, not a wishlist. **Add new Dev Tools codes here as
they're introduced** — don't scatter magic numbers in `firmware/ui/`
without a matching entry in this table.

| Code | Action | Notes |
|---|---|---|
| `0000` | Exit Dev Tools | |
| `0022` | Set repo | opens repo selection (currently one option: `japyscope-remote`) |
| `0033` | Set update channel | opens channel selection — Stable only / Stable + prereleases (i.e. whether OTA also installs GitHub prereleases) |
| `0044` | SSH | shows SSH access info (IP/hostname, login user) |
| `1001` | Enable more INDI drivers (camera, focuser, etc.) | **coming soon** — placeholder message only, no drivers selectable yet |
| `1111` | Restart INDI server | functional — calls into `firmware/indi/manager.py`'s restart |
| `1234` | Show system info (IP, INDI version, uptime) | functional |
| `5000` | Launch Wi-Fi setup wizard | functional — same flow as a factory-reset Wi-Fi join |
| `5555` | Select mount driver | functional — opens driver selection (currently one option: Sky-Watcher Alt-Az GTi) |
| `9600` | Select communication interface | functional — opens interface selection (currently one option: RJ12 direct to mount) |
| `9955` | Run custom script | lists `.sh` scripts found in `{homepath}/custom` and runs the selected one |
| `9999` | Easter egg (astronomer/Moon joke) | cosmetic only |
| `4200` | Easter egg ("42.") | cosmetic only |
| `1957` | Easter egg (Sputnik) | cosmetic only |
| `0905` | Easter egg ("Protocol 09: the code stays free — JapySoft") | cosmetic only |
| anything else | "Invalid code." | |

None of the above currently require the sudo password — add the
requirement here (and enforce it in `firmware/ui/`) the day a Dev Tools
code becomes genuinely destructive (e.g. a future factory-reset code).

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
| `OTA-001` | update check failed (no internet / GitHub API unreachable) | `japyscope-app` journal, Web UI → System |
| `OTA-002` | downloaded release failed checksum verification | same |
| `OTA-003` | new release failed its post-install health check, rolled back | same |
| `WIFI-001` | AP-mode setup hotspot failed to start | `hostapd`/`dnsmasq` journal |
| `SEARCH-001` | SmartSearch online lookup timed out / no internet — fell back to local catalogs only | `japyscope-app` journal |
| `SYS-001` | Daily `apt-get update`/`upgrade` step failed (best-effort — never blocks the JapyScope release step) | `japyscope-update` journal |
