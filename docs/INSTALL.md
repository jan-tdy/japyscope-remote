# Installation

JapyScope targets the original Raspberry Pi Zero W (`armv6`). Use **Raspberry
Pi OS Bullseye Lite, 32-bit**. Not a 64-bit image (won't boot on armv6 at
all) — and not Bookworm either, even though Bookworm's 32-bit (armhf) image
*does* officially support the Zero W: this project's Wi-Fi AP setup
(`install/wifi-config.sh`) writes straight to `wpa_supplicant.conf`, which
isn't how Bookworm's default NetworkManager-based networking works, and
that hasn't been ported/tested. The installer enforces this — it refuses to
run on anything but Bullseye.

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

1. Flash Bullseye Lite with Raspberry Pi Imager. Configure a user and enable
   SSH in the imager if the controller has no keyboard.
2. Boot the Pi, copy or clone this repository, and enter its root directory.
3. Run `sudo install/install.sh`.

The installer refuses non-Bullseye and non-`armhf` systems. It installs the
Bullseye `indi-bin` package (which includes `indiserver` and the verified
`indi_skywatcherAltAzMount` executable), build prerequisites, Python
dependencies, the Wi-Fi setup access point, and systemd units. The installed
tree is under `/opt/japyscope/releases/`; `/opt/japyscope/current` points to
the active version. Persistent data is in `/var/lib/japyscope`.

The installer enables the daily OTA timer. Disable automatic application with
`sudo systemctl disable --now japyscope-update.timer` if desired.

## First connection

When no saved Wi-Fi connection is active, join the WPA2-protected
`JapyScope-Setup` network. Its unique password is shown on the controller and
can also be read locally with `sudo cat /etc/japyscope/setup-ap-password`.
Browse to `http://192.168.4.1:8080/setup`. Enter the home Wi-Fi
credentials, then reconnect the client device to that network. The password is
passed directly to `wpa_supplicant`; it is not stored in the JapyScope database.

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
