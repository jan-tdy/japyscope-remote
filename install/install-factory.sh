#!/usr/bin/env bash
set -euo pipefail

# Provisions JapyScope onto an SD card from ANOTHER computer, via a USB
# card reader — no need to boot the Pi Zero W, attach a keyboard, or SSH
# in first. Run this on a Linux host (needs root, loop-free block device
# access, and qemu-user-static for armhf emulation) against a card
# already flashed with Raspberry Pi OS Bullseye/Bookworm/Trixie Lite,
# 32-bit (armhf) — e.g. via Raspberry Pi Imager. It mounts the card's two
# partitions, chroots into the rootfs under qemu-arm-static emulation
# (the same technique .github/workflows/build-libindi-armhf.yml and
# test-bookworm-armhf.yml already use in CI), and runs the ordinary
# install.sh inside it. install.sh detects it isn't running on a live,
# booted system (systemd_is_live(), see install.sh) and skips the
# service-start/reload calls that need a running init — the units are
# already enabled, so they start themselves normally on the Pi's real
# first boot.
#
# Usage: sudo install/install-factory.sh /dev/sdX [--yes] [--no-ap]
#   /dev/sdX  the SD card's whole-disk device as seen by this host (NOT
#             a partition — no trailing digit), e.g. /dev/sdb or
#             /dev/mmcblk0. Double-check this with `lsblk` first — the
#             card's existing filesystems are mounted and written to.
#   --yes     skip the interactive confirmation prompt (for scripted use)
#   --no-ap   forwarded to install.sh: don't auto-start the Wi-Fi setup
#             hotspot at boot — ideal when the image's Wi-Fi is already
#             configured (e.g. preseeded via Raspberry Pi Imager). The
#             hotspot itself stays installed and can still be brought up
#             manually (Web UI System page, Dev Tools code 5000)

if [[ $EUID -ne 0 ]]; then
  echo "Run this with sudo." >&2
  exit 1
fi
if [[ $(uname -s) != Linux ]]; then
  echo "install-factory.sh needs a Linux host (chroot, loop/block mounts," >&2
  echo "qemu-user-static binfmt emulation) — it won't work on macOS/Windows" >&2
  echo "directly. A Linux VM or container with the SD card reader passed" >&2
  echo "through will work." >&2
  exit 1
fi

confirm_yes=0
no_ap=0
device=""
for arg in "$@"; do
  case $arg in
    --yes|-y) confirm_yes=1 ;;
    --no-ap) no_ap=1 ;;
    -*) echo "Unknown option: $arg" >&2; exit 1 ;;
    *)
      if [[ -n $device ]]; then echo "Only one device argument is expected." >&2; exit 1; fi
      device=$arg
      ;;
  esac
done
if [[ -z $device ]]; then
  echo "Usage: sudo install/install-factory.sh /dev/sdX [--yes] [--no-ap]" >&2
  exit 1
fi
if [[ ! -b $device ]]; then
  echo "$device is not a block device." >&2
  exit 1
fi

for tool in lsblk findmnt mount umount chroot rsync file parted partprobe e2fsck resize2fs; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
if ! command -v qemu-arm-static >/dev/null; then
  echo "Missing qemu-arm-static. On the host (not the SD card), install:" >&2
  echo "  sudo apt-get install qemu-user-static binfmt-support" >&2
  exit 1
fi
if [[ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]]; then
  echo "binfmt_misc has no qemu-arm handler registered on this host — armhf" >&2
  echo "binaries can't run inside the chroot. Install/enable it with:" >&2
  echo "  sudo apt-get install qemu-user-static binfmt-support" >&2
  echo "  sudo systemctl restart binfmt-support" >&2
  exit 1
fi

# Refuse a device that would clobber the host's own running system.
host_root_disk=$(lsblk -no PKNAME "$(findmnt -no SOURCE /)" 2>/dev/null || true)
if [[ -n $host_root_disk && "/dev/$host_root_disk" == "$device" ]]; then
  echo "$device appears to be this computer's own system disk — refusing." >&2
  exit 1
fi

echo "About to provision JapyScope onto:"
lsblk "$device"
echo
if [[ $confirm_yes -ne 1 ]]; then
  read -r -p "Type the device path ($device) to confirm and continue: " typed
  if [[ $typed != "$device" ]]; then
    echo "Confirmation did not match — aborting, nothing was touched." >&2
    exit 1
  fi
fi

part_suffix=""
if [[ $device =~ [0-9]$ ]]; then part_suffix="p"; fi
boot_part="${device}${part_suffix}1"
root_part="${device}${part_suffix}2"
for p in "$boot_part" "$root_part"; do
  if [[ ! -b $p ]]; then
    echo "Expected partition $p not found — is this a freshly-flashed" >&2
    echo "Raspberry Pi OS Lite card (exactly boot + rootfs partitions)?" >&2
    exit 1
  fi
done

# Unmount anything the desktop/host may have auto-mounted already.
for p in "$boot_part" "$root_part"; do
  if findmnt -rno TARGET "$p" >/dev/null 2>&1; then
    umount "$p"
  fi
done

# Raspberry Pi Imager ships a tiny rootfs partition (a few GB) regardless
# of card size — Raspberry Pi OS only grows it to fill the card via its
# own first-boot resize service, which never runs here since the Pi
# itself never boots this card. Without this step, apt/pip/venv/build
# work inside the chroot reliably runs out of space ("No space left on
# device") even on a large card. Grow the rootfs partition to use the
# rest of the disk, then grow its filesystem to match; this is
# idempotent (a no-op if already full-size), so re-running is safe, and
# the real Pi's own first-boot resize service correctly does nothing
# when it later finds nothing left to grow.
echo "Growing the rootfs partition to fill the card..."
parted --script "$device" resizepart 2 100%
partprobe "$device" 2>/dev/null || true
udevadm settle 2>/dev/null || true
set +e
e2fsck -f -y "$root_part"
fsck_status=$?
set -e
if (( fsck_status >= 4 )); then
  echo "e2fsck reported uncorrected errors on $root_part (exit $fsck_status)" >&2
  echo "— the card's filesystem may be damaged. Re-flash it and retry." >&2
  exit 1
fi
resize2fs "$root_part"

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_dir=$(cd -- "$script_dir/.." && pwd)

mnt=$(mktemp -d)
mounted_root=0
mounted_boot=0
mounted_dev=0
mounted_devpts=0
mounted_proc=0
mounted_sys=0
qemu_copied=0
resolv_replaced=0
resolv_backup=""

cleanup() {
  local status=$?
  # Reverse order of setup; each best-effort so one failure doesn't stop
  # the rest, and a lazy unmount as a last resort. Restoring resolv.conf
  # must happen before the root partition is unmounted.
  [[ $mounted_sys -eq 1 ]] && { umount "$mnt/sys" 2>/dev/null || umount -l "$mnt/sys" 2>/dev/null || true; }
  [[ $mounted_proc -eq 1 ]] && { umount "$mnt/proc" 2>/dev/null || umount -l "$mnt/proc" 2>/dev/null || true; }
  [[ $mounted_devpts -eq 1 ]] && { umount "$mnt/dev/pts" 2>/dev/null || umount -l "$mnt/dev/pts" 2>/dev/null || true; }
  [[ $mounted_dev -eq 1 ]] && { umount "$mnt/dev" 2>/dev/null || umount -l "$mnt/dev" 2>/dev/null || true; }
  if [[ $qemu_copied -eq 1 ]]; then rm -f "$mnt/usr/bin/qemu-arm-static"; fi
  if [[ $resolv_replaced -eq 1 ]]; then
    rm -f "$mnt/etc/resolv.conf"
    if [[ -n $resolv_backup && -e $resolv_backup ]]; then mv "$resolv_backup" "$mnt/etc/resolv.conf"; fi
  fi
  [[ $mounted_boot -eq 1 ]] && { umount "$mnt/boot" 2>/dev/null || umount -l "$mnt/boot" 2>/dev/null || true; }
  [[ $mounted_root -eq 1 ]] && { umount "$mnt" 2>/dev/null || umount -l "$mnt" 2>/dev/null || true; }
  rmdir "$mnt" 2>/dev/null || true
  exit "$status"
}
trap cleanup EXIT

mount "$root_part" "$mnt"
mounted_root=1
mount "$boot_part" "$mnt/boot"
mounted_boot=1

if [[ ! -r "$mnt/etc/os-release" ]]; then
  echo "Cannot find /etc/os-release on $root_part — this doesn't look like" >&2
  echo "a Raspberry Pi OS root filesystem." >&2
  exit 1
fi
# shellcheck disable=SC1091
codename=$(. "$mnt/etc/os-release"; echo "${VERSION_CODENAME:-}")
case $codename in
  bullseye|bookworm|trixie) ;;
  *)
    echo "JapyScope requires Raspberry Pi OS Bullseye, Bookworm, or Trixie" >&2
    echo "Lite (32-bit) — found VERSION_CODENAME=${codename:-<none>}." >&2
    exit 1
    ;;
esac
if ! file --brief "$mnt/bin/bash" | grep -q ARM; then
  echo "Expected an armhf (32-bit ARM) root filesystem — $root_part doesn't" >&2
  echo "look like one. A 64-bit image will not boot on the original Pi Zero W." >&2
  exit 1
fi
echo "Detected Raspberry Pi OS $codename, armhf — provisioning..."

cp "$(command -v qemu-arm-static)" "$mnt/usr/bin/qemu-arm-static"
qemu_copied=1

mount --bind /dev "$mnt/dev"
mounted_dev=1
mount --bind /dev/pts "$mnt/dev/pts"
mounted_devpts=1
mount -t proc proc "$mnt/proc"
mounted_proc=1
mount -t sysfs sysfs "$mnt/sys"
mounted_sys=1

# A chroot shares the host's network stack/interfaces, but not its
# resolv.conf — the mounted image's own one is either empty or points at
# systemd-resolved's runtime socket, which isn't running here, so DNS
# would fail for apt/curl/pip. Swap in the host's, and restore whatever
# was there afterward (cleanup(), above).
if [[ -e "$mnt/etc/resolv.conf" || -L "$mnt/etc/resolv.conf" ]]; then
  resolv_backup="$mnt/etc/resolv.conf.japyscope-factory-backup"
  mv "$mnt/etc/resolv.conf" "$resolv_backup"
fi
cp /etc/resolv.conf "$mnt/etc/resolv.conf"
resolv_replaced=1

chroot_src=/opt/japyscope-remote-src
install -d "$mnt$chroot_src"
rsync -a --delete --exclude='.git' "$source_dir/" "$mnt$chroot_src/"

# .git is excluded above (keeps the copy small and fast), so install.sh's
# own `git describe` inside the chroot would fall back to a timestamp
# version instead of the real tag. Pass the host checkout's actual
# version through instead, when it has one.
version_override=$(git -C "$source_dir" describe --tags --always 2>/dev/null || true)
install_args=()
if [[ $no_ap -eq 1 ]]; then install_args+=(--no-ap); fi
if [[ -n $version_override ]]; then
  chroot "$mnt" /bin/bash -c "cd '$chroot_src' && JAPYSCOPE_VERSION_OVERRIDE='$version_override' ./install/install.sh \"\$@\"" -- "${install_args[@]}"
else
  chroot "$mnt" /bin/bash -c "cd '$chroot_src' && ./install/install.sh \"\$@\"" -- "${install_args[@]}"
fi

ap_password=$(cat "$mnt/etc/japyscope/setup-ap-password" 2>/dev/null || echo "<not found — check install.sh's output above>")

# Read while $mnt is still mounted — the EXIT trap unmounts everything
# once this script itself exits, right after these final echoes.
echo
echo "Factory install complete on $device."
echo "Wi-Fi setup password: $ap_password"
if [[ $no_ap -eq 1 ]]; then
  echo "(--no-ap: the setup hotspot won't come up automatically at boot, but this password still works for a manual Restart Wi-Fi setup later.)"
fi
echo "Eject the card, put it in the Pi Zero W, and power it on — it should"
echo "boot straight into JapyScope with no further setup on the device itself."
