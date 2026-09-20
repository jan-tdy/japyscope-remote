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
case ${VERSION_CODENAME:-} in
  bullseye|bookworm) ;;
  *)
  echo "JapyScope Pi Zero W requires Raspberry Pi OS Bullseye or Bookworm Lite (32-bit)." >&2
  exit 1
  ;;
esac
arch=$(dpkg --print-architecture)
if [[ $arch != armhf ]]; then echo "Expected the 32-bit armhf image, found $arch." >&2; exit 1; fi

export DEBIAN_FRONTEND=noninteractive

# True when running on a real, booted system (systemd is actually PID 1
# and reachable) — false under install-factory.sh's chroot (SD card
# mounted and provisioned from another computer via a card reader,
# before the Pi has ever booted this filesystem). `systemctl enable`,
# `unmask`, and `disable` are pure symlink/file operations and work fine
# either way; `start`/`restart`/`daemon-reload` need a live service
# manager and hang or fail under chroot, so those are skipped when this
# is false — the units are already enabled, so they start normally on
# the real first boot instead.
systemd_is_live() {
  [[ -d /run/systemd/system ]]
}

# Real Pi Zero W bring-up hit repeated apt/dpkg failures from marginal power
# and a degrading SD card (see docs/TROUBLESHOOTING.md's "Filesystem went
# read-only"). These helpers self-heal what's safely fixable in software
# (an interrupted previous apt/dpkg run, a held lock, a transient network
# blip) and fail fast — without retrying — on what isn't: a genuinely
# read-only root filesystem, which no script should paper over.
check_writable_root() {
  local probe=/var/tmp/.japyscope-write-test
  if ! touch "$probe" 2>/dev/null; then
    echo "Root filesystem is read-only. This installer will not try to work" >&2
    echo "around that — it usually means the SD card or power supply" >&2
    echo "corrupted it. See docs/TROUBLESHOOTING.md ('Filesystem went" >&2
    echo "read-only') before retrying." >&2
    return 1
  fi
  rm -f "$probe"
}

wait_for_apt_lock() {
  local lock=/var/lib/dpkg/lock-frontend waited=0
  while [[ -e $lock ]] && ! flock -n "$lock" true 2>/dev/null; do
    waited=$((waited + 2))
    if (( waited >= 120 )); then
      echo "Timed out waiting for another apt/dpkg process to finish." >&2
      return 1
    fi
    sleep 2
  done
}

heal_dpkg() {
  # Resolves a half-configured package left by an interrupted previous
  # apt/dpkg run (power loss, Ctrl-C, a prior crash). Safe no-op otherwise.
  dpkg --configure -a || true
}

apt_retry() {
  local attempt
  for attempt in 1 2 3; do
    check_writable_root || exit 1
    wait_for_apt_lock || exit 1
    heal_dpkg
    if "$@"; then return 0; fi
    echo "apt command failed (attempt $attempt/3), retrying in 5s: $*" >&2
    sleep 5
  done
  echo "apt command failed after 3 attempts: $*" >&2
  return 1
}

apt_retry apt-get update
apt_retry apt-get install -y --no-install-recommends python3 python3-dev python3-venv python3-pip build-essential pkg-config swig ninja-build libdbus-1-dev libglib2.0-dev libjpeg-dev zlib1g-dev libfreetype6-dev libnova-dev libcfitsio-dev curl ca-certificates indi-bin sudo
command -v indiserver >/dev/null
command -v indi_skywatcherAltAzMount >/dev/null

# pyindi-client 2.2.0 requires INDI Core 2.x. Raspberry Pi OS Bullseye ships
# 1.8.8 and Bookworm ships 1.9.9, both predating that API. Fetch a prebuilt
# ARMv6-safe INDI core (headers + client lib only — indiserver/drivers keep
# using apt's indi-bin unchanged, which has no runtime dependency on
# libindi-dev) into /usr/local, one of pyindi-client's own SWIG search paths.
# Built by
# .github/workflows/build-libindi-armhf.yml; see docs/TROUBLESHOOTING.md.
#
# apt's libindi-dev must NOT be installed alongside this: pyindi-client's
# generated SWIG wrapper #includes several INDI headers directly (not
# through one umbrella header), and each one resolves independently via
# the compiler's include search path — so if both /usr/include/libindi
# (old, apt) and /usr/local/include/libindi (new) exist, some headers
# resolve to one and some to the other, producing duplicate/conflicting
# class and enum definitions in the same translation unit. Purge it
# unconditionally (safe no-op if it was never installed, or already
# removed by a prior run) before laying down the prebuilt headers.
# Never mix the old distribution headers with the 2.x header set: SWIG
# includes several files directly, so mixed include paths produce duplicate
# declarations. This is needed on both supported OS releases.
apt_retry apt-get purge -y libindi-dev
rm -rf /usr/include/libindi
libindi_core_marker=/usr/local/share/japyscope/libindi-core-installed
# shellcheck disable=SC1091
source "$source_dir/install/libindi-core.env"
# Keyed on the SHA-256, not the tag: a broken build was once re-published
# under the same tag with fixed content (a GitHub Release tag isn't actually
# immutable), so a tag-only marker would wrongly skip re-fetching.
if [[ "$(cat "$libindi_core_marker" 2>/dev/null || true)" != "$LIBINDI_CORE_SHA256" ]]; then
  tmp_tarball=$(mktemp)
  echo "Fetching prebuilt INDI core ($LIBINDI_CORE_TAG) for pyindi-client..." >&2
  curl -fL --retry 3 --retry-delay 5 -o "$tmp_tarball" \
    "https://github.com/jan-tdy/japyscope-remote/releases/download/$LIBINDI_CORE_TAG/$LIBINDI_CORE_ASSET"
  echo "$LIBINDI_CORE_SHA256  $tmp_tarball" | sha256sum -c -
  tar -xzf "$tmp_tarball" -C /usr/local
  rm -f "$tmp_tarball"
  if [[ -d /usr/local/lib/arm-linux-gnueabihf ]]; then
    find /usr/local/lib/arm-linux-gnueabihf -maxdepth 1 -name 'libindi*' -exec ln -sf {} /usr/local/lib/ \;
  fi
  ldconfig
  install -d /usr/local/share/japyscope
  echo "$LIBINDI_CORE_SHA256" > "$libindi_core_marker"
fi

if [[ ${VERSION_CODENAME:-} == bullseye ]]; then
  apt_retry apt-get install -y --no-install-recommends hostapd dnsmasq wpasupplicant
  network_backend=wpa_supplicant
else
  # Bookworm's supported network stack is NetworkManager; do not install
  # hostapd/dnsmasq alongside it and fight for wlan0.
  apt_retry apt-get install -y --no-install-recommends network-manager
  systemctl enable NetworkManager.service
  if systemd_is_live; then systemctl start NetworkManager.service; fi
  command -v nmcli >/dev/null
  network_backend=networkmanager
fi

getent group gpio >/dev/null || groupadd --system gpio
getent group spi >/dev/null || groupadd --system spi
if ! id japyscope >/dev/null 2>&1; then useradd --system --home /var/lib/japyscope --create-home --shell /usr/sbin/nologin japyscope; fi
usermod -a -G gpio,spi,dialout,netdev japyscope
install -d -o root -g root -m 755 /opt/japyscope/releases /etc/japyscope
printf 'JAPYSCOPE_NETWORK_BACKEND=%s\n' "$network_backend" > /etc/japyscope/network-backend
chmod 644 /etc/japyscope/network-backend
install -d -o japyscope -g japyscope -m 750 /var/lib/japyscope

# JAPYSCOPE_VERSION_OVERRIDE lets install-factory.sh pass through the real
# `git describe` of the host checkout it copied from — its own copy into
# the chroot deliberately excludes .git, so `git describe` in here would
# otherwise always fall back to a timestamp.
version=${JAPYSCOPE_VERSION_OVERRIDE:-$(git -C "$source_dir" describe --tags --always 2>/dev/null || date -u +%Y%m%d%H%M%S)}
release_dir=/opt/japyscope/releases/$version
marker="$release_dir/.install-complete"
if [[ -e $release_dir && ! -e $marker ]]; then
  # Re-running install.sh after an earlier failure (e.g. a missing apt
  # package mid-way through) always re-derives the same version string —
  # nothing changed in git — so this is virtually always a stale,
  # incomplete directory from that failed attempt, not a real conflict.
  # Safe to remove: it was never marked complete, so nothing depends on it.
  echo "Removing incomplete release directory from a previous failed install: $release_dir" >&2
  rm -rf "$release_dir"
fi
if [[ -e $release_dir ]]; then
  echo "Release $version is already fully installed — skipping rebuild." >&2
else
  install -d -o root -g root -m 755 "$release_dir"
  cp -a "$source_dir/firmware" "$source_dir/webui" "$source_dir/shared" "$source_dir/install" "$source_dir/requirements.txt" "$source_dir/requirements.lock" "$source_dir/requirements-pyindi.lock" "$release_dir/"
  python3 -m venv "$release_dir/.venv"
  "$release_dir/.venv/bin/python" -m pip install --upgrade pip setuptools wheel
  "$release_dir/.venv/bin/python" -m pip install --require-hashes -r "$release_dir/requirements.lock"
  # Separate, --no-deps install: pyindi-client's declared bottle/dbus-python
  # dependencies are unused by the actual PyIndi module and dbus-python
  # can't be built on the Pi Zero W — see requirements-pyindi.lock.
  # --no-build-isolation: its build-system.requires also lists the PyPI
  # "swig" package, whose bundled binary needs a newer glibc than Bullseye
  # has (GLIBC_2.33/2.34 vs. Bullseye's 2.31) — use the system swig (apt,
  # above) instead by building against the already-installed environment.
  "$release_dir/.venv/bin/python" -m pip install --require-hashes --no-deps --no-build-isolation -r "$release_dir/requirements-pyindi.lock"
  chown -R root:root "$release_dir"
  touch "$marker"
fi
ln -sfn "$release_dir" /opt/japyscope/.current.new
mv -Tf /opt/japyscope/.current.new /opt/japyscope/current

if [[ ! -f /etc/japyscope/environment ]]; then
  secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  printf 'JAPYSCOPE_DB_PATH=/var/lib/japyscope/japyscope.db\nJAPYSCOPE_SECRET_KEY=%s\n' "$secret" > /etc/japyscope/environment
  chmod 600 /etc/japyscope/environment
fi
install -o root -g root -m 755 "$source_dir/install/wifi-config.sh" /usr/local/sbin/japyscope-wifi
install -o root -g root -m 755 "$source_dir/install/wifi-ap.sh" /usr/local/sbin/japyscope-wifi-ap
ap_password_file=/etc/japyscope/setup-ap-password
if [[ ! -s $ap_password_file ]]; then
  umask 077
  python3 -c 'import secrets; print(secrets.token_hex(12))' > "$ap_password_file"
  chown root:japyscope "$ap_password_file"
  chmod 640 "$ap_password_file"
fi
if [[ $network_backend == wpa_supplicant ]]; then
python3 - "$source_dir/install/hostapd.conf" /etc/hostapd/japyscope.conf "$ap_password_file" <<'PY'
import pathlib
import sys

template = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
password = pathlib.Path(sys.argv[3]).read_text(encoding="ascii").strip()
pathlib.Path(sys.argv[2]).write_text(
    template.replace("__JAPYSCOPE_SETUP_PSK__", password), encoding="utf-8"
)
PY
chown root:root /etc/hostapd/japyscope.conf
chmod 600 /etc/hostapd/japyscope.conf
install -o root -g root -m 644 "$source_dir/install/dnsmasq.conf" /etc/dnsmasq.d/japyscope.conf
sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/japyscope.conf"|' /etc/default/hostapd
else
  # The profile is deliberately non-autoconnecting: it is started only when
  # no configured client Wi-Fi has associated, by japyscope-wifi-ap.
  if systemd_is_live; then
    nmcli connection delete id 'JapyScope Setup' >/dev/null 2>&1 || true
    nmcli connection add type wifi ifname wlan0 con-name 'JapyScope Setup' autoconnect no ssid JapyScope-Setup
    nmcli connection modify 'JapyScope Setup' wifi.mode ap wifi.band bg ipv4.method shared ipv4.addresses 192.168.4.1/24 ipv6.method disabled wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$(<"$ap_password_file")"
  else
    # No live NetworkManager to talk to (install-factory.sh's chroot) —
    # nmcli needs its daemon running over D-Bus, which doesn't exist here.
    # Write the equivalent connection profile as a keyfile directly;
    # NetworkManager reads these unmodified on the real first boot. Must
    # be root-only 0600, or NetworkManager silently ignores the file.
    nm_conn_dir=/etc/NetworkManager/system-connections
    install -d -m 700 "$nm_conn_dir"
    nm_uuid=$(python3 -c 'import uuid; print(uuid.uuid4())')
    nm_psk=$(<"$ap_password_file")
    cat > "$nm_conn_dir/JapyScope Setup.nmconnection" <<NMCONN
[connection]
id=JapyScope Setup
uuid=$nm_uuid
type=wifi
interface-name=wlan0
autoconnect=false

[wifi]
mode=ap
band=bg
ssid=JapyScope-Setup

[wifi-security]
key-mgmt=wpa-psk
psk=$nm_psk

[ipv4]
method=shared
address1=192.168.4.1/24

[ipv6]
method=disabled
NMCONN
    chown root:root "$nm_conn_dir/JapyScope Setup.nmconnection"
    chmod 600 "$nm_conn_dir/JapyScope Setup.nmconnection"
  fi
fi
printf '%s\n' 'japyscope ALL=(root) NOPASSWD: /usr/local/sbin/japyscope-wifi *, /usr/local/sbin/japyscope-wifi-ap --force, /bin/systemctl restart japyscope-app.service, /bin/systemctl reboot, /bin/systemctl poweroff' > /etc/sudoers.d/japyscope
chmod 440 /etc/sudoers.d/japyscope
visudo -cf /etc/sudoers.d/japyscope
install -o root -g root -m 644 "$source_dir"/install/systemd/* /etc/systemd/system/
if systemd_is_live; then systemctl daemon-reload; fi
if [[ $network_backend == wpa_supplicant ]]; then systemctl unmask hostapd.service; fi
systemctl enable japyscope-wifi-ap.service japyscope-splash.service japyscope-app.service japyscope-webui.service japyscope-update.timer
if systemd_is_live; then
  systemctl restart japyscope-wifi-ap.service
  systemctl restart japyscope-app.service japyscope-webui.service
  echo "Wi-Fi setup password: sudo cat $ap_password_file"
  echo "Installed JapyScope $version. Web UI: http://$(hostname -I | awk '{print $1}'):8080/"
else
  # install-factory.sh's chroot: nothing is actually running yet — the
  # enabled units above start themselves normally on the real first boot.
  echo "Installed JapyScope $version onto this filesystem (offline/factory install)."
  echo "Wi-Fi setup password: $(cat "$ap_password_file")"
fi
