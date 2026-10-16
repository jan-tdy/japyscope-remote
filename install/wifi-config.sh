#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "usage: sudo japyscope-wifi [--slot primary|secondary] SSID (password on stdin)" >&2
  exit 2
fi
if [[ $# -eq 3 && $1 == --slot ]]; then
  slot=$2
  ssid=$3
elif [[ $# -eq 1 ]]; then
  slot=primary
  ssid=$1
else
  echo "usage: sudo japyscope-wifi [--slot primary|secondary] SSID (password on stdin)" >&2
  exit 2
fi
if [[ $slot != primary && $slot != secondary ]]; then
  echo "usage: sudo japyscope-wifi [--slot primary|secondary] SSID (password on stdin)" >&2
  exit 2
fi
ssid_bytes=$(printf %s "$ssid" | wc -c)
if (( ssid_bytes < 1 || ssid_bytes > 32 )); then
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

con_name='JapyScope client'
other_con_name='JapyScope client 2'
if [[ $slot == secondary ]]; then
  con_name='JapyScope client 2'
  other_con_name='JapyScope client'
fi

if [[ ${JAPYSCOPE_NETWORK_BACKEND:-} == networkmanager ]]; then
  password=$(cat)
  if (( ${#password} < 8 || ${#password} > 63 )); then
    echo "invalid WPA2 password length" >&2
    exit 2
  fi
  # Only replace our own profile, never a connection made by Raspberry Pi
  # Imager or by the owner.  Bring the new profile up before tearing down the
  # setup AP so a failed association can still be recovered on the next boot.
  nmcli connection delete id "$con_name" >/dev/null 2>&1 || true
  nmcli connection add type wifi ifname wlan0 con-name "$con_name" autoconnect yes ssid "$ssid"
  nmcli connection modify "$con_name" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$password" ipv4.method auto ipv6.method auto
  # Whichever slot is (re)configured becomes the one NetworkManager
  # reconnects to on its own after a reboot; the other slot stops
  # autoconnecting so a later Dev Tools switch (japyscope-wifi-switch)
  # actually sticks across a power cycle instead of being raced by this one.
  nmcli connection modify "$other_con_name" connection.autoconnect no >/dev/null 2>&1 || true
  nmcli connection down id 'JapyScope Setup' >/dev/null 2>&1 || true
  nmcli connection up id "$con_name" ifname wlan0
  exit 0
fi
if [[ ${JAPYSCOPE_NETWORK_BACKEND:-} != wpa_supplicant ]]; then
  echo "unknown JapyScope network backend: ${JAPYSCOPE_NETWORK_BACKEND:-missing}" >&2
  exit 1
fi
# Persisted separately from the live wpa_supplicant.conf below (which only
# ever holds the *active* slot) so japyscope-wifi-switch can bring either
# slot back without the plaintext password being re-entered.
fragment=/etc/wpa_supplicant/japyscope-$slot.conf
fragment_tmp=$(mktemp /etc/wpa_supplicant/.japyscope.XXXXXX)
trap 'rm -f "$fragment_tmp"' EXIT
wpa_passphrase "$ssid" | sed '/^[[:space:]]*#psk=/d' > "$fragment_tmp"
chown root:root "$fragment_tmp"
chmod 600 "$fragment_tmp"
mv "$fragment_tmp" "$fragment"
trap - EXIT
config_tmp=$(mktemp /etc/wpa_supplicant/.japyscope.XXXXXX)
trap 'rm -f "$config_tmp"' EXIT
{
  printf '%s\n' 'ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev' 'update_config=1'
  cat "$fragment"
} > "$config_tmp"
chown root:root "$config_tmp"
chmod 600 "$config_tmp"
mv "$config_tmp" /etc/wpa_supplicant/wpa_supplicant.conf
trap - EXIT
systemctl stop hostapd.service dnsmasq.service || true
ip address flush dev wlan0
wpa_cli -i wlan0 reconfigure
