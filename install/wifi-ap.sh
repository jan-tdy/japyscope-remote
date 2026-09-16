#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || $# -gt 1 || ( $# -eq 1 && $1 != --force ) ]]; then exit 1; fi
if [[ ${1:-} != --force ]] && wpa_cli -i wlan0 status 2>/dev/null | grep -q '^wpa_state=COMPLETED$'; then
  exit 0
fi
systemctl stop hostapd.service dnsmasq.service || true
ip link set wlan0 up
ip address flush dev wlan0
ip address add 192.168.4.1/24 dev wlan0
systemctl start dnsmasq.service hostapd.service
