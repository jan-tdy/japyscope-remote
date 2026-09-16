#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || $# -ne 1 ]]; then
  echo "usage: sudo japyscope-wifi SSID (password on stdin)" >&2
  exit 2
fi
ssid=$1
IFS= read -r wifi_password
if (( ${#ssid} < 1 || ${#ssid} > 32 || ${#wifi_password} < 8 || ${#wifi_password} > 63 )); then
  echo "invalid SSID or WPA passphrase length" >&2
  exit 2
fi

umask 077
config_tmp=$(mktemp /etc/wpa_supplicant/.japyscope.XXXXXX)
trap 'rm -f "$config_tmp"' EXIT
{
  printf '%s\n' 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev' 'update_config=1'
  printf '%s\n' "$wifi_password" | wpa_passphrase "$ssid"
} > "$config_tmp"
chown root:root "$config_tmp"
chmod 600 "$config_tmp"
mv "$config_tmp" /etc/wpa_supplicant/wpa_supplicant.conf
trap - EXIT
systemctl stop hostapd.service dnsmasq.service || true
ip address flush dev wlan0
wpa_cli -i wlan0 reconfigure
