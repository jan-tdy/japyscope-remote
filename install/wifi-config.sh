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
  # Imager or by the owner.
  nmcli connection delete id "$con_name" >/dev/null 2>&1 || true
  # autoconnect no here regardless of slot: primary flips it to yes (and
  # connects now) a few lines down, but secondary never does either on its
  # own -- see the big comment below for why.
  nmcli connection add type wifi ifname wlan0 con-name "$con_name" autoconnect no ssid "$ssid"
  nmcli connection modify "$con_name" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$password" ipv4.method auto ipv6.method auto
  if [[ $slot == primary ]]; then
    # The AP-join flow (/setup) always means "connect to this now" -- it's
    # how the device first gets online, or rejoins after a factory reset.
    # Bring the new profile up before tearing down the setup AP so a
    # failed association can still be recovered on the next boot.
    #
    # Secondary is different on purpose: it's saved for later, often from
    # somewhere its network isn't even in range yet (that's the whole
    # point of a second slot), so saving it must never force a connection
    # attempt that could fail, and must never touch whatever is already
    # working -- including disabling its autoconnect, which previously
    # happened unconditionally here and could leave a device unable to
    # auto-reconnect to EITHER network if the new one then failed to
    # associate. Activating a saved secondary slot is a separate, explicit
    # step (japyscope-wifi-switch), not a side effect of saving it.
    nmcli connection modify "$con_name" connection.autoconnect yes
    nmcli connection modify "$other_con_name" connection.autoconnect no >/dev/null 2>&1 || true
    nmcli connection down id 'JapyScope Setup' >/dev/null 2>&1 || true
    nmcli connection up id "$con_name" ifname wlan0
  fi
  exit 0
fi
if [[ ${JAPYSCOPE_NETWORK_BACKEND:-} != wpa_supplicant ]]; then
  echo "unknown JapyScope network backend: ${JAPYSCOPE_NETWORK_BACKEND:-missing}" >&2
  exit 1
fi
live_config=/etc/wpa_supplicant/wpa_supplicant.conf
primary_fragment=/etc/wpa_supplicant/japyscope-primary.conf
if [[ $slot == secondary && ! -r $primary_fragment && -r $live_config ]]; then
  # First-ever use of the secondary slot on a device whose Wi-Fi was never
  # configured through JapyScope's own flow (Raspberry Pi Imager, raspi-config,
  # or by hand) -- there's no "primary" fragment to switch back to later
  # because nothing ever saved one. Capture whatever's live right now, so
  # japyscope-wifi-switch has something to restore afterwards; best-effort,
  # never blocks saving the secondary network over it.
  capture_tmp=$(mktemp /etc/wpa_supplicant/.japyscope.XXXXXX)
  trap 'rm -f "$capture_tmp"' EXIT
  awk '/^network=\{/{found=1} found' "$live_config" > "$capture_tmp" 2>/dev/null || true
  if [[ -s $capture_tmp ]]; then
    chown root:root "$capture_tmp"; chmod 600 "$capture_tmp"
    mv "$capture_tmp" "$primary_fragment"
  else
    rm -f "$capture_tmp"
  fi
  trap - EXIT
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
if [[ $slot != primary ]]; then
  # Saved for later, same reasoning as the NetworkManager branch above --
  # never applied immediately. Switching to it is japyscope-wifi-switch's
  # job, not this script's.
  exit 0
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
systemctl stop hostapd.service dnsmasq.service || true
ip address flush dev wlan0
wpa_cli -i wlan0 reconfigure
