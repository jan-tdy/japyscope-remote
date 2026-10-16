#!/usr/bin/env bash
set -euo pipefail

# Admin tool for mounts whose built-in Bluetooth module exposes the same
# SynScan serial protocol used over the RJ12 "Hand Control" port (see
# docs/WIRING.md). `scan` and `pair` are normally driven from the device's
# own Dev Tools screen (codes 9600/9601, firmware/ui/controller.py) via
# sudo, not typed by hand -- but both also work fine run directly over SSH.
# Pairs the module, then binds it to a persistent /dev/rfcommN via
# japyscope-rfcomm-mount.service so it survives reboots.

usage() {
  echo "usage: sudo japyscope-bluetooth-mount scan [seconds]" >&2
  echo "       sudo japyscope-bluetooth-mount pair AA:BB:CC:DD:EE:FF" >&2
  echo "       sudo japyscope-bluetooth-mount unpair" >&2
  exit 2
}

if [[ $EUID -ne 0 ]]; then usage; fi

config_file=/etc/japyscope/bluetooth-mount
service=japyscope-rfcomm-mount.service
cmd=${1:-}

case $cmd in
  scan)
    duration=${2:-8}
    if [[ ! $duration =~ ^[0-9]+$ ]]; then usage; fi
    bluetoothctl power on >/dev/null
    {
      echo "scan on"
      sleep "$duration"
      echo "scan off"
    } | bluetoothctl >/dev/null 2>&1 || true
    # `devices` lists every device BlueZ has ever seen, not only this scan
    # -- fine for picking the mount out of what's nearby, but a rescan can
    # also show other previously-seen Bluetooth gear. One "MAC|Name" line
    # per device, for the caller (firmware/ui/controller.py) to parse.
    bluetoothctl devices | sed -n 's/^Device \([0-9A-Fa-f:]\{17\}\) \(.*\)$/\1|\2/p'
    ;;
  pair)
    mac=${2:-}
    if [[ ! $mac =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then usage; fi
    mac=${mac^^}
    bluetoothctl power on >/dev/null
    # NoInputNoOutput auto-accepts "Just Works" Secure Simple Pairing,
    # which covers most modern Bluetooth Classic SPP modules -- no PIN
    # prompt at all. A module that still needs a PIN will fail here; pair
    # it once by hand instead (`bluetoothctl`, then `agent on` and
    # `pair MAC`, answering the PIN prompt) -- BlueZ remembers it
    # afterwards, and this command (and the Dev Tools screen) will then
    # find it already paired.
    {
      echo "agent NoInputNoOutput"
      echo "default-agent"
      echo "pair $mac"
      sleep 5
    } | bluetoothctl >/dev/null 2>&1 || true
    if ! bluetoothctl info "$mac" | grep -q "Paired: yes"; then
      echo "Pairing with $mac failed -- it may need a PIN this command can't supply." >&2
      echo "Pair it once by hand (bluetoothctl -> agent on -> pair $mac), then retry." >&2
      exit 1
    fi
    bluetoothctl trust "$mac" >/dev/null
    install -d -m 755 /etc/japyscope
    printf 'JAPYSCOPE_MOUNT_BT_MAC=%s\n' "$mac" > "$config_file"
    chmod 600 "$config_file"
    systemctl enable --now "$service"
    echo "Paired and bound $mac to /dev/rfcomm0 (persists via $service)."
    ;;
  unpair)
    systemctl disable --now "$service" 2>/dev/null || true
    if [[ -r $config_file ]]; then
      # shellcheck disable=SC1090
      source "$config_file"
      bluetoothctl untrust "${JAPYSCOPE_MOUNT_BT_MAC:-}" >/dev/null 2>&1 || true
    fi
    rm -f "$config_file"
    echo "Unbound and untrusted. Switch the device back to RJ12 via Dev Tools code 9600."
    ;;
  *)
    usage
    ;;
esac
