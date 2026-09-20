---
layout: default
title: Installation reference
permalink: /install-reference/
---

# Installation

JapyScope targets the original Raspberry Pi Zero W (`armv6`). Use **Raspberry
Pi OS Lite, 32-bit (armhf)**, either **Bullseye** or **Bookworm**. A 64-bit
image will not boot on the original Zero W. The installer detects the release:
Bullseye uses its legacy `wpa_supplicant`/hostapd setup, while Bookworm uses
its default NetworkManager stack for both the saved client network and the
setup hotspot.

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

1. Flash Bullseye Lite or Bookworm Lite with Raspberry Pi Imager. Configure a user and enable
   SSH in the imager if the controller has no keyboard.
2. Boot the Pi, copy or clone this repository, and enter its root directory.
3. Run `sudo install/install.sh`.

The installer refuses unsupported releases and non-`armhf` systems. It
installs `indi-bin` (which includes `indiserver` and the verified
`indi_skywatcherAltAzMount` executable), build prerequisites, Python
dependencies, the Wi-Fi setup access point, and systemd units. Both releases
fetch the pinned compatible INDI client core because their packaged headers
are older than the INDI 2.x API required by `pyindi-client`. The installed
tree is under `/opt/japyscope/releases/`; `/opt/japyscope/current` points to
the active version. Persistent data is in `/var/lib/japyscope`.

The installer enables the daily OTA timer. Disable automatic application with
`sudo systemctl disable --now japyscope-update.timer` if desired.

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
Pi. Flash Bullseye/Bookworm Lite onto the card with Raspberry Pi Imager
first, same as step 1 above; this script only does the JapyScope part.

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
