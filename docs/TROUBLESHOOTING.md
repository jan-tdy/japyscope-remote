---
layout: default
title: Troubleshooting
permalink: /troubleshooting/
---

# Troubleshooting

Start with the combined journal:

```sh
journalctl -u japyscope-app -u japyscope-webui -u japyscope-wifi-ap -n 200 --no-pager
```

---

<details markdown="block">
  <summary>Problems already fixed in latest release</summary>
   
## Setup AP starts on every boot even though Wi-Fi is already configured and working

**Fixed** — if you're still hitting this, `git pull` and re-run `install.sh`.
Root cause: `japyscope-wifi-ap.service` runs right after wlan0's device node
appears (`After=sys-subsystem-net-devices-wlan0.device`), which is well
before the configured network manager has actually finished associating with
a configured network. The script's "skip the AP if already connected" check
ran exactly once, immediately, so it always saw "not connected yet" — even on
a device with perfectly good Wi-Fi credentials that would have connected fine
a couple of seconds later — and started the AP unnecessarily on every single
boot, kicking any already-associated client off. `install/wifi-ap.sh` now
polls for up to 20 seconds before falling back to starting the AP, using
`wpa_cli` on Bullseye and NetworkManager's device state on Bookworm/Trixie.

If Wi-Fi is preconfigured (e.g. via Raspberry Pi Imager) and you'd rather
not rely on this poll at every boot at all, re-run
`sudo install/install.sh --no-ap` (or use `--no-ap` on the original
install/`install-factory.sh` run). It disables `japyscope-wifi-ap.service` —
the automatic boot-time check — entirely, instead of just racing it. The
hotspot itself (`hostapd`/`dnsmasq` or the NetworkManager profile, the AP
password, `japyscope-wifi-ap`) stays installed and can still be brought up
manually any time from the Web UI's **System** page ("Restart Wi-Fi setup")
or `sudo japyscope-wifi-ap --force`.

If you're locked out because the AP already came up and you don't know its
password (e.g. no physical e-ink display yet): it's stored in plain text at
`/etc/japyscope/setup-ap-password` on the SD card — pull the card and read
it from another machine (or use physical console access) if you have no
other way to reach the Pi's shell.

## `pip install` fails on `dbus-python`: "meson-python: error: Could not find ninja version 1.8.2 or newer"

**Fixed as of this doc** — if you're still hitting this, you have an old
checkout: `git pull` first. Root cause, confirmed during real Pi Zero W
bring-up after installing `ninja-build`/`cmake` didn't help across many
retries: `pyindi-client`'s PyPI metadata declares hard dependencies on
`bottle` and `dbus-python` that the actual `PyIndi` module never imports
(verified against its source — nothing in `PyIndi/__init__.py` or
`PyIndi/PyIndi.py` touches either). `dbus-python` has no prebuilt wheel for
armhf, and building it needs `meson-python`, which fetches its own `ninja`
from PyPI into pip's *isolated* build sandbox rather than using the
perfectly good system `ninja` — and that isolated build doesn't work on
this hardware, regardless of what's installed system-wide.

The fix: `pyindi-client` is no longer installed via the main
`requirements.lock` at all. It's installed separately, with `--no-deps`,
from `requirements-pyindi.lock` — see `install.sh` and `install/update.py`.
This skips `bottle`/`dbus-python` entirely; nothing is lost since they were
never used.

If you ever regenerate `requirements.lock` with `pip-compile`, it will
pull `pyindi-client` (and `bottle`/`dbus-python`) back in — remove those
three again afterward, per the comment at the top of `requirements.lock`.

## `pyindi-client` build fails on `swig`: "GLIBC_2.33/2.34 not found"

Same class of problem as the `ninja`/`dbus-python` one above, just a
different build-time dependency: `pyindi-client`'s `build-system.requires`
also lists the PyPI `swig` package (not just the system tool), and *its*
bundled `swig` binary is compiled against a newer glibc than Bullseye ships
(2.33/2.34 vs. Bullseye's 2.31) — it fails to even execute.

Fixed by installing `swig` via apt (system tool, correctly built for
Bullseye's glibc) and passing `--no-build-isolation` to the
`requirements-pyindi.lock` install, so pip builds against the
already-installed environment (system `swig` on `PATH`, plus the venv's
already-upgraded `setuptools`/`wheel`) instead of fetching its own
(incompatible) copy of `swig` into an isolated sandbox. `git pull` if
you're hitting this on an old checkout.

## `pyindi-client` build fails on SWIG: "Unable to find 'indipropertyview.h'" (and friends)

Next stage after the `swig` fix above: SWIG itself now runs, but can't find
`indimacros.h`, `indiwidgettraits.h`, `indipropertyview.h`,
`indipropertybasic.h`, `indipropertytext.h`, `indipropertynumber.h`,
`indipropertyswitch.h`, `indipropertylight.h`, `indipropertyblob.h`, or
`indiproperties.h`. Confirmed root cause: the distribution `libindi-dev`
packages are too old for current `pyindi-client`'s INDI 2.x SWIG interface:
Bullseye ships **1.8.8+dfsg-1** and Bookworm ships **1.9.9+dfsg-2**. Neither
has the required INDI 2.x `PropertyView` API. Building INDI core from source
*on* a Pi Zero W (single ARM11 core, 512 MB RAM, already SD-card-constrained
— see "Filesystem went read-only" below) is impractical and risky.

Fixed without compiling anything on the Pi: `.github/workflows/build-libindi-armhf.yml`
cross-builds INDI core on GitHub's infrastructure, booting the actual
official Raspberry Pi OS Bullseye armhf image (`raspios_lite:2023-05-03` —
see the "`status=4/ILL`" section below for why it's *not* the more obvious
`raspi_2_bullseye` shortcut) under QEMU via `pguyot/arm-runner-action` —
not a generic Debian/Ubuntu docker image, which would produce ARMv7
binaries that illegal-instruction-crash on the Zero W's ARMv6 CPU. It
packages just the new headers and the client library (not
`indiserver` or any driver — those keep running from apt's `indi-bin`/
`libindi-dev`, untouched) and attaches the tarball to a GitHub Release.
`install.sh` downloads it (pinned tag + SHA-256 in `install/libindi-core.env`)
into `/usr/local` on both supported releases — already one of
`indiclientpython.i`'s own SWIG search paths, so no interface-file change was
needed — before the existing `--no-deps --no-build-isolation` `pyindi-client`
install. `git pull` if you're hitting this on an old checkout.

If `install/libindi-core.env` still says `PENDING`, the prebuilt tarball
hasn't been published yet; trigger the workflow manually (Actions → "Build
libindi core (armhf, Bullseye, ARMv6)") or push a `libindi-armhf-vX.Y.Z` tag,
then update that file with the resulting tag/asset/SHA-256.

## `pyindi-client` build fails with "conflicts with a previous declaration" / "redefinition of class ..."

Next stage after the fix above: the prebuilt headers land in
`/usr/local/include/libindi`, but apt's `libindi-dev` is *also* still
installed (from an earlier `install.sh` run, before this fix), leaving its
old headers in `/usr/include/libindi` too. `indiclientpython.i`'s generated
SWIG wrapper `#include`s several INDI headers directly rather than through
one umbrella header, and each one resolves independently via the
compiler's include search path — some end up pulling in the old copy,
some the new one, and the same classes/enums get defined twice in one
translation unit.

Fixed: `install.sh` now purges `libindi-dev` (via apt) and additionally
`rm -rf`s `/usr/include/libindi` directly as a belt-and-braces measure —
this device's dpkg state has a history of corruption (see "Filesystem
went read-only" below), so the apt purge alone isn't trusted to have
actually cleared the directory. `indi-bin` (indiserver + drivers) has no
runtime dependency on `libindi-dev`, so removing it is safe. `git pull`
if you're hitting this on an old checkout.

## `pyindi-client` build fails at link time: "cannot find -lnova" (or `-lcfitsio`)

Next stage after the fix above: SWIG and the C++ compile succeed
completely, but linking the final `_PyIndi` extension fails — it needs
`-lnova` and `-lcfitsio`, the unversioned `.so` symlinks that only ship in
the `-dev` packages (`libnova-dev`, `libcfitsio-dev`), not the runtime
library packages. The `build-libindi-armhf.yml` CI workflow installs
these to build INDI core itself, but that doesn't help the Pi — the
prebuilt tarball only bundles INDI's own libraries, not their system
dependencies, which the target device still needs from apt.

Fixed: `install.sh` now installs `libnova-dev`/`libcfitsio-dev` directly.
`git pull` if you're hitting this on an old checkout.

## `japyscope-app.service` crashes immediately with `status=4/ILL` after `pyindi-client` finally builds

Everything up to here built and linked successfully, but the app crashes
(SIGILL — illegal instruction) the moment it actually loads/uses the
freshly-built `PyIndi` module. Root cause: `build-libindi-armhf.yml` was
using `arm-runner-action`'s `raspi_2_bullseye` base image, which is
**not** Raspberry Pi OS — it's `raspi.debian.net`'s own Debian build for
genuine Pi 2/3 hardware (ARMv7, Cortex-A7). Its toolchain defaults to
ARMv7, so the prebuilt `libindiclient`/headers — and the `pyindi-client`
extension compiled against them on-device — silently contained ARMv7
instructions the Zero W's real ARMv6 (ARM1176) CPU can't execute.

Fixed: switched to `raspios_lite:2023-05-03`, the same action's shortcut
for the actual official Raspberry Pi Foundation Bullseye Lite armhf image
(`downloads.raspberrypi.org`), whose toolchain genuinely targets
ARMv6+VFP2. This needed a full rebuild and republish of the
`libindi-armhf-v2.2.4` release — `git pull`, then re-run `install.sh` (the
SHA-256-keyed marker in `install/libindi-core.env` will detect the new
build and re-fetch it) if you're hitting this on an old checkout.

If you ever need to change `build-libindi-armhf.yml`'s base image again:
`raspi_N_*` and `dietpi:*` shortcuts in `arm-runner-action` are generic
Debian/DietPi builds for real Pi hardware of that generation, not
Raspberry Pi OS — only `raspios_lite:*` (and `raspios_lite_arm64:*`,
`raspios_oldstable_lite:*`) shortcuts resolve to genuine
`downloads.raspberrypi.org` images. Double-check the resolved URL in
`download_image.sh` before trusting a shortcut's name.

## `test-bookworm-armhf.yml` fails instantly with "Unknown image raspios_lite:2023-12-11"

The Bookworm CI smoke test never actually booted anything — it failed in
under a second at the "download base image" step, before `apt-get`,
`indiserver`, or `import PyIndi` ever ran. Root cause: unlike
`raspios_lite:2023-05-03` (Bullseye, used by `build-libindi-armhf.yml`),
`arm-runner-action`'s `raspios_lite:*` alias whitelist has **no Bookworm
entry at all** — it stops at Bullseye. `raspios_lite:2023-12-11` looked
like a valid dated shortcut but was simply never registered, so the
action rejected it outright with "Unknown image" instead of failing later
on a real dependency/PyIndi problem. This meant the workflow had been
reporting a misleading "failure" that had nothing to do with Bookworm
compatibility — and, worse, had never actually verified it either.

Fixed: pass the real `downloads.raspberrypi.org` image URL directly as
`base_image` instead of relying on an alias — `download_image.sh` uses
any `http(s):` value verbatim, bypassing the whitelist:
`https://downloads.raspberrypi.org/raspios_lite_armhf/images/raspios_lite_armhf-2023-12-11/2023-12-11-raspios-bookworm-armhf-lite.img.xz`.
`git pull` if you're hitting this on an old checkout. Don't use
`raspios_lite:latest` as a "just give me current Bookworm" substitute
either — it tracks whatever Raspberry Pi OS currently ships (already
Trixie as of this writing), not Bookworm specifically.

## `test-trixie-armhf.yml` fails with "No space left on device"

Fixed (`git pull` if you're hitting this on an old checkout). The real
cause is an `e2fsprogs` version mismatch, not actually a lack of space:

`arm-runner-action` grows the downloaded image by `image_additional_mb`
(a plain `dd` append — that part always "succeeds"), then runs the
**host** runner's `e2fsck`/`resize2fs` to actually extend the ext4
filesystem into that new room. Trixie's base image was itself built with
a much newer `e2fsprogs` (1.47.2) than Ubuntu 22.04 ships (1.46.5), which
sets an ext4 feature bit ("unsupported feature(s)", `FEATURE_C12`) the
older host tools don't recognize. `e2fsck`/`resize2fs` then fail *silently*
from the workflow's point of view — `mount_image.sh` logs "Finished
resizing disk image." either way — so the filesystem never actually grows,
and `apt`/`tar` run out of the base image's small original room at the
same exact point regardless of how high `image_additional_mb` is set (a
first attempt raising it from 4096 to 8192 changed nothing, confirming
this: the `dd` step correctly grew the image file both times, but the
*filesystem* stayed the original size both times). The same version gap
also breaks `arm-runner-action`'s own post-build image-shrink cleanup, so
`optimize_image: 'no'` skips it — it only mattered for caching the output
image, which this job doesn't do.

Fixed by running this job on `ubuntu-24.04` instead of `ubuntu-22.04`:
its `e2fsprogs` (1.47.0) is close enough to Trixie's own to actually
perform the resize. This is unrelated to the arm1176-vs-cortex-a7 QEMU
segfault in `build-libindi-armhf.yml`'s history — that was tied to the
`arm1176` CPU model specifically, reproducing on every runner version;
this job (like `test-bookworm-armhf.yml`) already uses `cortex-a7`.

## `install.sh` says "Release directory already exists" / re-running after a fix

Fixed: `install.sh` used to hard-fail here, because re-running it after
fixing an earlier error (e.g. a missing apt package) re-derives the exact
same version string (`git describe` — nothing changed in git) and found
its own previous, incomplete attempt's directory still there. It now
detects an incomplete release directory (no `.install-complete` marker),
removes it, and rebuilds automatically — you can just re-run `install.sh`
after fixing whatever failed, no manual `rm -rf` needed.

## `install.sh` says "Refusing to switch /opt/japyscope/current ..."

Not a bug — a safety check. `install.sh` and the OTA updater
(`japyscope-update.timer` / `install/update.py`) both flip the same
`/opt/japyscope/current` symlink. If OTA has already updated the device
past whatever commit your local checkout is on (common if you haven't
`git pull`ed in a while), re-running `install.sh` would otherwise silently
relink `current` back to that older version — a real downgrade, even
though nothing looked wrong in the installer's own output (this is what
produces the confusing "Release vX.Y.Z-N-gHASH is already fully installed
— skipping rebuild" message right before it, for a version older than
what's actually running). Run `git pull` in the checkout you're installing
from and re-run `install.sh`, or pass `--force` if you deliberately want
to force this device onto the version your checkout resolves to.

</details>

---

## Wheel is building, and the Pi does not react, and the loading circle does not turn
Wait at least 20 minutes (it is normal), if still nothing, wait a little more; if still nothing, hard-reboot by pulling the cable.

## No route to host via SSH / screen showing nothing while LEDs on

Wait a few minutes (wait at least 20 minutes); while normally it should boot under 6 minutes, first boot or filesystem-fix boot may take longer.
If still nothing, check if your power source is really on.

## Filesystem went read-only / `dpkg`, `apt` fail with I/O or "Read-only file system" errors

It happened to me about 5 times: That recurrence under
improved power points at the **SD card itself** (wear, bad sectors, or a
counterfeit/low-quality card), not only power — treat both as suspects, but
don't assume a better PSU alone fixes it if it happens again.

Symptoms: kernel log lines like `EXT4-fs (mmcblk0p2): failed to convert
unwritten extents to written extents -- potential data loss! (inode N, error
-30)`, `dpkg: unrecoverable fatal error, ... unable to fsync ...: Input/output
error`, `Read-only file system` from `apt`. The Pi may become unresponsive
over SSH.

1. Power-cycle (pull power, don't just reboot from a hung shell). If it comes
   back:
   ```sh
   mount | grep mmcblk0p2      # still "ro"? filesystem hasn't recovered
   vcgencmd get_throttled       # anything but 0x0 = undervoltage, now or historically
   ```
   If it's `rw` and `get_throttled` is clean, retry the failed step
   (`sudo dpkg --configure -a`, then re-run `install.sh`/`system-upgrade`)
   once. If it fails again under write load, stop and go to step 3 — this is
   no longer a one-off.
2. **Test the SD card from another machine** (card reader, not the Pi):
   ```sh
   sudo badblocks -v /dev/sdX     # non-destructive read scan for bad sectors — replace sdX
   ```
   or run `f3` (Fight Flash Fraud) if you suspect a counterfeit/overreported-capacity
   card — extremely common with cheap unbranded cards.
3. **Power supply**: use an official/quality 5V/2.5A supply with a short,
   good-quality micro-USB cable. A phone charger or a PC's USB port is the
   single most common cause of exactly this failure on a Zero W under the
   combined CPU+I/O load of `apt`/`pip`/`venv` during install or
   `system-upgrade` (see `SYS-001` below) — this project has no battery/UPS
   to smooth over a brief sag.
4. **If it recurs even with confirmed-good power**: treat the card as
   suspect. Replace it — ideally a reputable-brand "High Endurance" /
   "Application class" card, meant for continuous writes and sudden power
   loss (the exact profile of a nonstop-running INDI + Web UI device), not a
   generic consumer card. Re-flash the OS fresh rather than reusing a
   card that has already corrupted twice.

Note: `install/install.sh` and `install/update.py system-upgrade` now
self-heal the *software* half of this on their own — an interrupted
previous apt/dpkg run (a half-configured package after a crash) is fixed
automatically with `dpkg --configure -a` before every apt command, a held
apt/dpkg lock is waited out, and a transient apt failure is retried up to 3
times. None of that touches the *hardware* half above: if the root
filesystem is genuinely read-only, both scripts detect it and stop
immediately with a message pointing back here, rather than retrying (which
would just risk more corruption).

## `INDI-001`: server or driver did not start

Run `command -v indiserver`, `command -v indi_skywatcherAltAzMount`, and
`id japyscope`. The `japyscope` user must belong to `dialout`. Confirm the
physical connection is RJ12 through a 3.3 V ↔ 5 V level shifter; see
`docs/WIRING.md`.

## `INDI-002`: mount did not connect

The exact serial port and INDI property mapping must be confirmed during real
hardware bring-up. Check that `/dev/serial0` is enabled and not used by the
Linux login console, then inspect the driver output in the application journal.

## `INDI-003`: repeated watchdog restarts

Run `systemctl status japyscope-app` and inspect the preceding driver output.
Check power, serial wiring, driver name, and port configuration.

## `WIFI-001`: setup hotspot or join failed

Run `sudo /usr/local/sbin/japyscope-wifi-ap --force`; the setup page is
`http://192.168.4.1:8080/setup`. On Bullseye, inspect
`systemctl status japyscope-wifi-ap hostapd dnsmasq` and their journals. On
Bookworm or Trixie, inspect `systemctl status japyscope-wifi-ap NetworkManager`
and `journalctl -u NetworkManager`; the `JapyScope Setup` NetworkManager
profile owns the radio and DHCP service. (`--no-ap` only disables the
automatic boot-time check — all of this is still installed and `--force`
still brings the hotspot up manually either way, see the next section.)


## `SEARCH-001`: online SmartSearch unavailable

This is non-fatal. The controller has already fallen back to built-in and all
custom catalogs. Check DNS/HTTPS connectivity to CDS Sesame; local search
remains available while offline.

## `SYS-001`: system package upgrade failed

Best-effort step (`update.py system-upgrade`, run daily alongside `apply` by
`japyscope-update.timer`) — a failure here never blocks or rolls back a
JapyScope release install. Run `sudo apt-get update && sudo apt-get upgrade`
manually to see the actual apt error (network issue, held package, disk
space). Never resolved by running `full-upgrade`/`dist-upgrade` — that would
be a distribution upgrade, which this project deliberately avoids.

## `OTA-001`, `OTA-002`, or `OTA-003`

See `docs/UPDATE.md`. Confirm internet access and that the release contains one
archive with a SHA-256 digest. Inspect `journalctl -u japyscope-update -n 200
--no-pager` and `readlink -f /opt/japyscope/current` after a rollback.

## Web UI access

Codes expire after ten minutes. Generate a fresh one on the controller. A
client that submits five bad codes must wait 30 seconds. Sessions are reset if
`/etc/japyscope/environment` is deleted or its secret changes.

## Still stuck?

If none of the sections above resolve your problem, please
[open a GitHub issue](https://github.com/jan-tdy/japyscope-remote/issues/new).
Include the output of:

```sh
journalctl -u japyscope-app -u japyscope-webui -u japyscope-wifi-ap -n 200 --no-pager
systemctl status japyscope-splash japyscope-app japyscope-webui
```

…along with your OS release (`cat /etc/os-release`), how you ran the
installer, and a description of what you expected vs. what happened.
