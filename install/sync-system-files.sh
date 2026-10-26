#!/usr/bin/env bash
set -euo pipefail

# Keeps /usr/local/sbin/japyscope-*, /etc/sudoers.d/japyscope and the
# systemd unit files in sync with whatever release is actually installed.
# install.sh calls this during a full install; install/update.py calls it
# after every OTA update too -- an OTA update only extracts the new code
# under /opt/japyscope/releases/<tag> and flips the `current` symlink, so
# without this step these OS-level files would silently keep running
# whatever a past install.sh run happened to leave behind, however much a
# newer release's install/*.sh, the sudoers line, or a systemd unit
# changes. (This is what a real "usage: sudo japyscope-wifi SSID"
# WIFI-001 failure on an OTA-updated device turned out to be:
# /usr/local/sbin/japyscope-wifi was still the pre-secondary-Wi-Fi
# version, since no install.sh run had touched it since the device's
# original install.)

if [[ $EUID -ne 0 ]]; then
  echo "run this as root (install.sh and update.py both already do)" >&2
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(cd -- "$script_dir/.." && pwd)

install -o root -g root -m 755 "$source_dir/install/wifi-config.sh" /usr/local/sbin/japyscope-wifi
install -o root -g root -m 755 "$source_dir/install/wifi-ap.sh" /usr/local/sbin/japyscope-wifi-ap
install -o root -g root -m 755 "$source_dir/install/wifi-switch.sh" /usr/local/sbin/japyscope-wifi-switch
install -o root -g root -m 755 "$source_dir/install/bluetooth-mount.sh" /usr/local/sbin/japyscope-bluetooth-mount
install -o root -g root -m 755 "$source_dir/install/official-script-runner.sh" /usr/local/sbin/japyscope-run-official-script

printf '%s\n' 'japyscope ALL=(root) NOPASSWD: /usr/local/sbin/japyscope-wifi *, /usr/local/sbin/japyscope-wifi-ap --force, /usr/local/sbin/japyscope-wifi-switch *, /usr/local/sbin/japyscope-bluetooth-mount *, /usr/local/sbin/japyscope-run-official-script *, /bin/systemctl restart japyscope-app.service, /bin/systemctl start japyscope-update.service, /bin/systemctl reboot, /bin/systemctl poweroff, /bin/systemctl enable --now ssh, /bin/journalctl *, /usr/bin/journalctl *' > /etc/sudoers.d/japyscope
chmod 440 /etc/sudoers.d/japyscope
visudo -cf /etc/sudoers.d/japyscope

install -o root -g root -m 644 "$source_dir"/install/systemd/* /etc/systemd/system/
if [[ -d /run/systemd/system ]]; then systemctl daemon-reload; fi
