---
layout: default
title: Installation reference
permalink: /install-reference/
---

# Installation

JapyScope targets the original Raspberry Pi Zero W (`armv6`). Use **Raspberry
Pi OS Lite, 32-bit (armhf)**: **Bullseye**, **Bookworm**, or **Trixie**. A
64-bit image will not boot on the original Zero W. The installer detects the
release: Bullseye uses its legacy `wpa_supplicant`/hostapd setup, while
Bookworm and Trixie both use their default NetworkManager stack for both the
saved client network and the setup hotspot.

## Power and SD card (read this first)

Confirmed twice during real bring-up: a weak power source (phone
charger/PC USB port) or a low-quality/counterfeit SD card can corrupt the
filesystem mid-install, under the sustained CPU+write load of `apt`/`pip`/
`venv` — symptoms are `EXT4-fs` extent-conversion errors, `dpkg` I/O
errors, and the filesystem going read-only. There's no battery in this
device to smooth over a brief power sag. Before you start:

- Use a proper **5V/2.5A** power supply with a short, good-quality
  micro-USB cable — not a phone charger or a PC USB port.
- Use a **reputable-brand SD card** (SanDisk, Samsung, ...); ideally a
  "High Endurance"/"Application class" one meant for continuous writes,
  since this device runs unattended 24/7. Cheap unbranded cards frequently
  misreport their capacity and fail under real write load.

If you hit filesystem/I-O errors during install anyway, see
`docs/TROUBLESHOOTING.md`'s "Filesystem went read-only" section before
retrying — repeatedly retrying on an already-degraded card/filesystem can
make it worse.

## Prepare the card

1. Flash Bullseye Lite, Bookworm Lite, or Trixie Lite with Raspberry Pi
   Imager. Configure a user and enable SSH in the imager if the controller
   has no keyboard. If you preconfigure Wi-Fi in the imager, consider
   `--no-ap` (below) instead of step 3's plain command.
2. Boot the Pi, copy or clone this repository, and enter its root directory.
3. Run `sudo install/install.sh`.

The installer refuses unsupported releases and non-`armhf` systems. It
installs `indi-bin` (which includes `indiserver` and the verified
`indi_skywatcherAltAzMount` executable), build prerequisites, Python
dependencies, the Wi-Fi setup access point, and systemd units. All three
releases fetch the pinned compatible INDI client core because their packaged
headers are older than the INDI 2.x API required by `pyindi-client`. The
installed tree is under `/opt/japyscope/releases/`; `/opt/japyscope/current`
points to the active version. Persistent data is in `/var/lib/japyscope`.

The installer enables the daily OTA timer. Disable automatic application with
`sudo systemctl disable --now japyscope-update.timer` if desired.

### Re-running `install.sh` on a device already updated by OTA

`install.sh` and the OTA updater (`install/update.py`) both flip the same
`/opt/japyscope/current` symlink. If the OTA timer has since advanced a
device past whatever commit your local checkout is on, re-running
`install.sh` from that stale checkout would otherwise silently relink
`current` back to the older version it resolves to — a silent downgrade.
`install.sh` now refuses to do this: if `/opt/japyscope/current` already
points somewhere else, it stops with an error instead of switching. Run
`git pull` in your checkout first, or pass `--force` if you deliberately
want to install exactly the version this checkout resolves to.

### Disabling the automatic Wi-Fi setup hotspot (`--no-ap`)

Run `sudo install/install.sh --no-ap` when the Pi's Wi-Fi is already working
— for example, credentials preconfigured through Raspberry Pi Imager, or a
wired/USB Ethernet controller. It only disables `japyscope-wifi-ap.service`,
the automatic check at every boot that brings the `JapyScope-Setup` hotspot
up on its own when no client Wi-Fi has associated yet — so it never fires on
a Pi whose Wi-Fi is already known-good.

Everything else the hotspot needs — `hostapd`/`dnsmasq` (Bullseye) or the
NetworkManager hotspot profile, the AP password file, and `japyscope-wifi-ap`
itself — is still installed. The Web UI's **System** page **Restart Wi-Fi
setup** action (and the eventual Dev Tools code `5000`, see `docs/CODES.md`)
still brings the hotspot up manually on request either way — `--no-ap` only
takes away the automatic fallback, never the manual one.

`--no-ap` actively disables (and, if currently up, stops)
`japyscope-wifi-ap.service`, so it takes effect even when re-running
`install.sh --no-ap` on a device that an earlier install had already enabled
it on. Verify with `systemctl is-enabled japyscope-wifi-ap.service` — it
should print `disabled`.

## Factory install from another computer (no boot/SSH needed)

`sudo install/install-factory.sh /dev/sdX` provisions a card the same way,
from a Linux host with the card in a USB reader, before the Pi Zero W ever
boots it — useful for prepping several controllers, or when there's no
keyboard/network path to the Pi at all. `/dev/sdX` is the card's whole-disk
device (check with `lsblk` first — its filesystems get mounted and written
to). It needs `qemu-user-static`/`binfmt-support` installed on the host (the
same technique `.github/workflows/build-libindi-armhf.yml` and
`test-bookworm-armhf.yml` already use in CI): it mounts the card's boot and
root partitions, chroots into the root filesystem under armhf emulation, and
runs the ordinary `install.sh` inside it. That script detects it isn't
running on a live, booted system and skips the handful of steps that need
one (starting services, `daemon-reload`) — the units are already enabled, so
they start themselves normally the first time the card actually boots on the
Pi. Flash Bullseye/Bookworm/Trixie Lite onto the card with Raspberry Pi
Imager first, same as step 1 above; this script only does the JapyScope
part. Pass `--no-ap` (same meaning as on `install.sh`) to disable the
automatic boot-time hotspot, e.g.
`sudo install/install-factory.sh /dev/sdX --no-ap`.

It also grows the card's rootfs partition/filesystem to fill the whole
card before installing anything — a freshly-flashed image ships with a
small (few-GB) rootfs regardless of card size, normally expanded by
Raspberry Pi OS's own first-boot resize step, which never runs here since
the Pi never actually boots this card. Skipping this would otherwise run
out of space partway through `apt`/`pip` even on a large card.

## First connection

When no saved Wi-Fi connection is active, join the WPA2-protected
`JapyScope-Setup` network. Its unique password is shown on the controller and
can also be read locally with `sudo cat /etc/japyscope/setup-ap-password`.
Browse to `http://192.168.4.1:8080/setup`. Enter the home Wi-Fi
credentials, then reconnect the client device to that network. The password is
passed directly to the OS network manager; it is not stored in the JapyScope database.

Generate a Web UI access code on the controller under **Menu → Wi-Fi / Web
Access**, then open `http://japyscope.local:8080/` (or the Pi's IP address).
Five bad codes cause a 30-second per-client lockout.

## Verify services

```sh
systemctl status japyscope-splash japyscope-app japyscope-webui
journalctl -u japyscope-app -u japyscope-webui -n 100 --no-pager
```

The e-paper controller and its INDI property mapping still require validation
against the eventual physical panel/mount. The splash is intentionally a
best-effort no-op until the selected panel's refresh protocol is implemented.

## Development simulation

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m firmware.main --simulate --db /tmp/japyscope.db
python -m webui.app --db /tmp/japyscope.db --host 127.0.0.1 --port 8080
```

Simulation does not start `indiserver` and does not require GPIO/SPI hardware.
