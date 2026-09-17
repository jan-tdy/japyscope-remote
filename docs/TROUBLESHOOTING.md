# Troubleshooting

Start with the combined journal:

```sh
journalctl -u japyscope-app -u japyscope-webui -u japyscope-wifi-ap -n 200 --no-pager
```

## Filesystem went read-only / `dpkg`, `apt` fail with I/O or "Read-only file system" errors

Seen during real Pi Zero W bring-up (Fáza 1beta), reproduced twice: once on a
weak USB power source, and — importantly — **again after switching to a
better power supply**, mid-`dpkg` unpack, with a genuine `Input/output error`
on `fsync` immediately before the read-only remount. That recurrence under
improved power points at the **SD card itself** (wear, bad sectors, or a
counterfeit/low-quality card), not only power — treat both as suspects, but
don't assume a better PSU alone fixes it if it happens again.

Symptoms: kernel log lines like `EXT4-fs (mmcblk0p2): failed to convert
unwritten extents to written extents -- potential data loss! (inode N, error
-30)`, `dpkg: unrecoverable fatal error, ... unable to fsync ...: Input/output
error`, `Read-only file system` from `apt`. The Pi may become unresponsive
over SSH.

1. **Don't keep retrying blindly on the same card/session** — each failed
   write during an already-degraded filesystem risks compounding the
   corruption.
2. Power-cycle (pull power, don't just reboot from a hung shell). If it comes
   back:
   ```sh
   mount | grep mmcblk0p2      # still "ro"? filesystem hasn't recovered
   vcgencmd get_throttled       # anything but 0x0 = undervoltage, now or historically
   ```
   If it's `rw` and `get_throttled` is clean, retry the failed step
   (`sudo dpkg --configure -a`, then re-run `install.sh`/`system-upgrade`)
   once. If it fails again under write load, stop and go to step 3 — this is
   no longer a one-off.
3. **Test the SD card from another machine** (card reader, not the Pi):
   ```sh
   sudo badblocks -v /dev/sdX     # non-destructive read scan for bad sectors — replace sdX
   ```
   or run `f3` (Fight Flash Fraud) if you suspect a counterfeit/overreported-capacity
   card — extremely common with cheap unbranded cards.
4. **Power supply**: use an official/quality 5V/2.5A supply with a short,
   good-quality micro-USB cable. A phone charger or a PC's USB port is the
   single most common cause of exactly this failure on a Zero W under the
   combined CPU+I/O load of `apt`/`pip`/`venv` during install or
   `system-upgrade` (see `SYS-001` below) — this project has no battery/UPS
   to smooth over a brief sag.
5. **If it recurs even with confirmed-good power**: treat the card as
   suspect. Replace it — ideally a reputable-brand "High Endurance" /
   "Application class" card, meant for continuous writes and sudden power
   loss (the exact profile of a nonstop-running INDI + Web UI device), not a
   generic consumer card. Re-flash Bullseye Lite fresh rather than reusing a
   card that has already corrupted twice.

## `INDI-001`: server or driver did not start

Run `command -v indiserver`, `command -v indi_skywatcherAltAzMount`, and
`id japyscope`. The `japyscope` user must belong to `dialout`. Confirm the
physical connection is RJ12 through a 3.3 V ↔ 5 V level shifter; see
`docs/WIRING.md`.

## `INDI-002`: mount did not connect

The exact serial port and INDI property mapping must be confirmed during real
hardware bring-up. Check that `/dev/serial0` is enabled and not used by the
Linux login console, then inspect the driver output in the application journal.

## `INDI-003`: repeated watchdog restarts

Run `systemctl status japyscope-app` and inspect the preceding driver output.
Check power, serial wiring, driver name, and port configuration.

## `WIFI-001`: setup hotspot or join failed

Run `systemctl status japyscope-wifi-ap hostapd dnsmasq` and then
`sudo /usr/local/sbin/japyscope-wifi-ap --force`. The setup page is
`http://192.168.4.1:8080/setup`. The `hostapd` and `dnsmasq` journals contain
radio or DHCP errors.

## `SEARCH-001`: online SmartSearch unavailable

This is non-fatal. The controller has already fallen back to built-in and all
custom catalogs. Check DNS/HTTPS connectivity to CDS Sesame; local search
remains available while offline.

## `SYS-001`: system package upgrade failed

Best-effort step (`update.py system-upgrade`, run daily alongside `apply` by
`japyscope-update.timer`) — a failure here never blocks or rolls back a
JapyScope release install. Run `sudo apt-get update && sudo apt-get upgrade`
manually to see the actual apt error (network issue, held package, disk
space). Never resolved by running `full-upgrade`/`dist-upgrade` — that would
be a distribution upgrade, which this project deliberately avoids.

## `OTA-001`, `OTA-002`, or `OTA-003`

See `docs/UPDATE.md`. Confirm internet access and that the release contains one
archive with a SHA-256 digest. Inspect `journalctl -u japyscope-update -n 200
--no-pager` and `readlink -f /opt/japyscope/current` after a rollback.

## Web UI access

Codes expire after ten minutes. Generate a fresh one on the controller. A
client that submits five bad codes must wait 30 seconds. Sessions are reset if
`/etc/japyscope/environment` is deleted or its secret changes.
