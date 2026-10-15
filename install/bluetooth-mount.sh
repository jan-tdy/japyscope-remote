#!/usr/bin/env bash
set -euo pipefail

# One-time admin tool (run over SSH, not from the device UI — the 3x4
# keypad has no practical way to enter a Bluetooth MAC address) for mounts
# whose built-in Bluetooth module exposes the same SynScan serial protocol
# used over the RJ12 "Hand Control" port (see docs/WIRING.md). Pairs the
# module, then binds it to a persistent /dev/rfcommN via
# japyscope-rfcomm-mount.service so it survives reboots. Mirrors the
# wifi-config.sh / wifi-ap.sh scripts' style and config-file location.

usage() {
  echo "usage: sudo japyscope-bluetooth-mount pair AA:BB:CC:DD:EE:FF" >&2
  echo "       sudo japyscope-bluetooth-mount unpair" >&2
  exit 2
}

if [[ $EUID -ne 0 ]]; then usage; fi

config_file=/etc/japyscope/bluetooth-mount
service=japyscope-rfcomm-mount.service
cmd=${1:-}

case $cmd in
  pair)
    mac=${2:-}
    if [[ ! $mac =~ ^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$ ]]; then usage; fi
    mac=${mac^^}
    bluetoothctl power on >/dev/null
    # Legacy SynScan BT modules typically need no PIN, or a fixed one
    # (commonly 1234/0000) that bluetoothctl's own default agent satisfies
    # automatically. If pairing hangs waiting for a PIN it doesn't know,
    # run `bluetoothctl` interactively once and pair by hand instead —
    # BlueZ remembers the pairing afterwards, and this command (or the
    # service below) will keep working from then on.
    bluetoothctl pair "$mac" || true
    bluetoothctl trust "$mac"
    install -d -m 755 /etc/japyscope
    printf 'JAPYSCOPE_MOUNT_BT_MAC=%s\n' "$mac" > "$config_file"
    chmod 600 "$config_file"
    systemctl enable --now "$service"
    echo "Paired and bound $mac to /dev/rfcomm0 (persists via $service)."
    echo "Now select it on the device: Dev Tools code 9600 -> Bluetooth (SynScan)."
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
