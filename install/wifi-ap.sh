#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 || $# -gt 1 || ( $# -eq 1 && $1 != --force ) ]]; then exit 1; fi
if [[ ${1:-} != --force ]]; then
  # At boot this runs right after wlan0's device node appears (systemd
  # After=sys-subsystem-net-devices-wlan0.device), well before
  # wpa_supplicant has actually finished associating with a configured
  # network — a single immediate check here always saw "not connected yet"
  # and started the AP even when Wi-Fi was already set up and about to
  # connect fine. Poll for a few seconds to give a real association a
  # chance to complete first.
  for _ in $(seq 1 20); do
    if wpa_cli -i wlan0 status 2>/dev/null | grep -q '^wpa_state=COMPLETED$'; then
      exit 0
    fi
    sleep 1
  done
fi
systemctl stop hostapd.service dnsmasq.service || true
ip link set wlan0 up
ip address flush dev wlan0
ip address add 192.168.4.1/24 dev wlan0
systemctl start dnsmasq.service hostapd.service
