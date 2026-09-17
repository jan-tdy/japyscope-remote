# Troubleshooting

Start with the combined journal:

```sh
journalctl -u japyscope-app -u japyscope-webui -u japyscope-wifi-ap -n 200 --no-pager
```

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
