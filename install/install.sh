#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(cd -- "$script_dir/.." && pwd)
if [[ ! -r /etc/os-release ]]; then echo "Cannot identify this operating system." >&2; exit 1; fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ ${VERSION_CODENAME:-} != bullseye ]]; then
  echo "JapyScope Pi Zero W requires Raspberry Pi OS Bullseye Lite (32-bit)." >&2
  exit 1
fi
arch=$(dpkg --print-architecture)
if [[ $arch != armhf ]]; then echo "Expected the 32-bit armhf image, found $arch." >&2; exit 1; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends python3 python3-dev python3-venv python3-pip build-essential libjpeg-dev zlib1g-dev libfreetype6-dev indi-bin libindi-dev hostapd dnsmasq wpasupplicant sudo
command -v indiserver >/dev/null
command -v indi_skywatcherAltAzMount >/dev/null

getent group gpio >/dev/null || groupadd --system gpio
getent group spi >/dev/null || groupadd --system spi
if ! id japyscope >/dev/null 2>&1; then useradd --system --home /var/lib/japyscope --create-home --shell /usr/sbin/nologin japyscope; fi
usermod -a -G gpio,spi,dialout,netdev japyscope
install -d -o root -g root -m 755 /opt/japyscope/releases /etc/japyscope
install -d -o japyscope -g japyscope -m 750 /var/lib/japyscope

version=$(git -C "$source_dir" describe --tags --always 2>/dev/null || date -u +%Y%m%d%H%M%S)
release_dir=/opt/japyscope/releases/$version
if [[ -e $release_dir ]]; then echo "Release directory already exists: $release_dir" >&2; exit 1; fi
install -d -o root -g root -m 755 "$release_dir"
cp -a "$source_dir/firmware" "$source_dir/webui" "$source_dir/shared" "$source_dir/install" "$source_dir/requirements.txt" "$release_dir/"
python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
"$release_dir/.venv/bin/python" -m pip install -r "$release_dir/requirements.txt" pyindi-client
chown -R root:root "$release_dir"
ln -sfn "$release_dir" /opt/japyscope/.current.new
mv -Tf /opt/japyscope/.current.new /opt/japyscope/current

if [[ ! -f /etc/japyscope/environment ]]; then
  secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  printf 'JAPYSCOPE_DB_PATH=/var/lib/japyscope/japyscope.db\nJAPYSCOPE_SECRET_KEY=%s\n' "$secret" > /etc/japyscope/environment
  chmod 600 /etc/japyscope/environment
fi
install -o root -g root -m 755 "$source_dir/install/wifi-config.sh" /usr/local/sbin/japyscope-wifi
install -o root -g root -m 755 "$source_dir/install/wifi-ap.sh" /usr/local/sbin/japyscope-wifi-ap
install -o root -g root -m 600 "$source_dir/install/hostapd.conf" /etc/hostapd/japyscope.conf
install -o root -g root -m 644 "$source_dir/install/dnsmasq.conf" /etc/dnsmasq.d/japyscope.conf
sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/japyscope.conf"|' /etc/default/hostapd
printf '%s\n' 'japyscope ALL=(root) NOPASSWD: /usr/local/sbin/japyscope-wifi *, /usr/local/sbin/japyscope-wifi-ap --force, /bin/systemctl restart japyscope-app.service, /bin/systemctl reboot, /bin/systemctl poweroff' > /etc/sudoers.d/japyscope
chmod 440 /etc/sudoers.d/japyscope
visudo -cf /etc/sudoers.d/japyscope
install -o root -g root -m 644 "$source_dir"/install/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl unmask hostapd.service
systemctl enable japyscope-wifi-ap.service japyscope-splash.service japyscope-app.service japyscope-webui.service japyscope-update.timer
systemctl restart japyscope-wifi-ap.service
systemctl restart japyscope-app.service japyscope-webui.service
echo "Installed JapyScope $version. Web UI: http://$(hostname -I | awk '{print $1}'):8080/"
