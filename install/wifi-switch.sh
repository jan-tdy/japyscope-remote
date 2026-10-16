#!/usr/bin/env bash
set -euo pipefail

# Switches to an *already configured* Wi-Fi slot (see wifi-config.sh / the
# Web UI's System page) without needing the password again — this is what
# Dev Tools code 5001 (firmware/ui/controller.py) calls. Configuring the
# primary slot (the /setup AP-join flow) already connects to it
# immediately; secondary never does on its own (see wifi-config.sh), so
# this script is how it actually gets activated, as well as how either
# slot gets switched back to later.
#
# "primary" is deliberately NOT a profile JapyScope creates, names, or
# otherwise manages the identity of — it's whatever was already configured
# before: the /setup flow, Raspberry Pi Imager, raspi-config, or by hand.
# Switching to it never looks up a connection by name; it just stops
# overriding with the secondary profile (JapyScope's own) and lets
# NetworkManager's/wpa_supplicant's own logic fall back to whatever that
# already-working network was.

if [[ $EUID -ne 0 || $# -ne 1 || ( $1 != primary && $1 != secondary ) ]]; then
  echo "usage: sudo japyscope-wifi-switch primary|secondary" >&2
  exit 2
fi
slot=$1

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
  if [[ $slot == secondary ]]; then
    if ! nmcli -t -f NAME connection show | grep -Fxq "$con_name"; then
      echo "secondary is not configured yet — set it up in the Web UI first." >&2
      exit 1
    fi
    nmcli connection modify "$con_name" connection.autoconnect yes
    nmcli connection modify "$other_con_name" connection.autoconnect no >/dev/null 2>&1 || true
    nmcli connection up id "$con_name" ifname wlan0
    exit 0
  fi
  # primary: stop overriding with secondary and let NetworkManager fall
  # back on its own -- see the file-level comment for why this never looks
  # up a "primary" connection by name.
  nmcli connection modify "$other_con_name" connection.autoconnect no >/dev/null 2>&1 || true
  nmcli connection down id "$other_con_name" >/dev/null 2>&1 || true
  exit 0
fi
if [[ ${JAPYSCOPE_NETWORK_BACKEND:-} != wpa_supplicant ]]; then
  echo "unknown JapyScope network backend: ${JAPYSCOPE_NETWORK_BACKEND:-missing}" >&2
  exit 1
fi
fragment=/etc/wpa_supplicant/japyscope-$slot.conf
if [[ ! -r $fragment ]]; then
  echo "$slot is not configured yet — set it up in the Web UI first." >&2
  exit 1
fi
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
wpa_cli -i wlan0 reconfigure
