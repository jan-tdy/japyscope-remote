# Installation

JapyScope targets the original Raspberry Pi Zero W (`armv6`). Use **Raspberry
Pi OS Bullseye Lite, 32-bit**. Do not use Bookworm or a 64-bit image.

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

When no saved Wi-Fi connection is active, join the open `JapyScope-Setup`
network and browse to `http://192.168.4.1:8080/setup`. Enter the home Wi-Fi
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
