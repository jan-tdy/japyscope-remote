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
