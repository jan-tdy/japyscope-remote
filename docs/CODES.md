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

## Dev Tools code

4-digit code entered via rotate-per-digit (Home → Dev Tools). No specific
codes are defined yet in v0 — the mockup only implements the entry UI, not
any destructive action gated behind it. **Add new Dev Tools codes here as
they're introduced** (e.g. factory reset, force-reindex local catalogs,
manual driver restart) — don't scatter magic numbers in code without an
entry in this table.

| Code | Action | Requires sudo password? |
|---|---|---|
| _(none defined yet)_ | | |

## Sudo password

- Default: `1234` (factory default, stored in `shared.db` `settings.sudo_password`).
- Set via Menu → Sudo Password (same rotary-dial 4-digit entry as Dev Tools codes).
- Intended to guard future destructive Dev Tools actions — none currently need it, since none are defined yet (see table above).
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
