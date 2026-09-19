#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || $# -ne 1 ]]; then
  echo "usage: sudo japyscope-wifi SSID (password on stdin)" >&2
  exit 2
fi
ssid=$1
if (( ${#ssid} < 1 || ${#ssid} > 32 )); then
  echo "invalid SSID length" >&2
  exit 2
fi

umask 077
backend_file=/etc/japyscope/network-backend
if [[ ! -r $backend_file ]]; then
  echo "JapyScope network backend is not configured; run install.sh first." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$backend_file"

if [[ ${JAPYSCOPE_NETWORK_BACKEND:-} == networkmanager ]]; then
  password=$(cat)
  if (( ${#password} < 8 || ${#password} > 63 )); then
    echo "invalid WPA2 password length" >&2
    exit 2
  fi
  # Only replace our own profile, never a connection made by Raspberry Pi
  # Imager or by the owner.  Bring the new profile up before tearing down the
  # setup AP so a failed association can still be recovered on the next boot.
  nmcli connection delete id 'JapyScope client' >/dev/null 2>&1 || true
  nmcli connection add type wifi ifname wlan0 con-name 'JapyScope client' autoconnect yes ssid "$ssid"
  nmcli connection modify 'JapyScope client' wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$password" ipv4.method auto ipv6.method auto
  nmcli connection down id 'JapyScope Setup' >/dev/null 2>&1 || true
  nmcli connection up id 'JapyScope client' ifname wlan0
  exit 0
fi
if [[ ${JAPYSCOPE_NETWORK_BACKEND:-} != wpa_supplicant ]]; then
  echo "unknown JapyScope network backend: ${JAPYSCOPE_NETWORK_BACKEND:-missing}" >&2
  exit 1
fi
config_tmp=$(mktemp /etc/wpa_supplicant/.japyscope.XXXXXX)
trap 'rm -f "$config_tmp"' EXIT
{
  printf '%s\n' 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev' 'update_config=1'
  wpa_passphrase "$ssid" | sed '/^[[:space:]]*#psk=/d'
} > "$config_tmp"
chown root:root "$config_tmp"
chmod 600 "$config_tmp"
mv "$config_tmp" /etc/wpa_supplicant/wpa_supplicant.conf
trap - EXIT
systemctl stop hostapd.service dnsmasq.service || true
ip address flush dev wlan0
wpa_cli -i wlan0 reconfigure
