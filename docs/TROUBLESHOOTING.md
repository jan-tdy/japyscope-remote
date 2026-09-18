# Troubleshooting

Start with the combined journal:

```sh
journalctl -u japyscope-app -u japyscope-webui -u japyscope-wifi-ap -n 200 --no-pager
```

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
`indiproperties.h`. Confirmed root cause: Bullseye's apt `libindi-dev` is
**1.8.8+dfsg-1**, which predates the `INDI::PropertyView`-family headers
current `pyindi-client`'s SWIG interface (`indiclientpython.i`) requires —
those headers simply don't exist anywhere in that package. There is no apt
repository shipping a newer `libindi-dev` for armhf/Bullseye (the INDI forum
has an open thread literally titled "INDI needs a new apt repository for
Debian ARM"), and building INDI core from source *on* a Pi Zero W (single
ARM11 core, 512 MB RAM, already SD-card-constrained — see "Filesystem went
read-only" below) is impractical and risky.

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
into `/usr/local` — already one of `indiclientpython.i`'s own SWIG search
paths, so no interface-file change was needed — before the existing
`--no-deps --no-build-isolation` `pyindi-client` install. `git pull` if
you're hitting this on an old checkout.

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

## `install.sh` says "Release directory already exists" / re-running after a fix

Fixed: `install.sh` used to hard-fail here, because re-running it after
fixing an earlier error (e.g. a missing apt package) re-derives the exact
same version string (`git describe` — nothing changed in git) and found
its own previous, incomplete attempt's directory still there. It now
detects an incomplete release directory (no `.install-complete` marker),
removes it, and rebuilds automatically — you can just re-run `install.sh`
after fixing whatever failed, no manual `rm -rf` needed.

## Filesystem went read-only / `dpkg`, `apt` fail with I/O or "Read-only file system" errors

Seen during real Pi Zero W bring-up (Fáza 1beta), reproduced twice: once on a
weak USB power source, and — importantly — **again after switching to a
better power supply**, mid-`dpkg` unpack, with a genuine `Input/output error`
on `fsync` immediately before the read-only remount. That recurrence under
improved power points at the **SD card itself** (wear, bad sectors, or a
counterfeit/low-quality card), not only power — treat both as suspects, but
don't assume a better PSU alone fixes it if it happens again.

Symptoms: kernel log lines like `EXT4-fs (mmcblk0p2): failed to convert
unwritten extents to written extents -- potential data loss! (inode N, error
-30)`, `dpkg: unrecoverable fatal error, ... unable to fsync ...: Input/output
error`, `Read-only file system` from `apt`. The Pi may become unresponsive
over SSH.

1. **Don't keep retrying blindly on the same card/session** — each failed
   write during an already-degraded filesystem risks compounding the
   corruption.
2. Power-cycle (pull power, don't just reboot from a hung shell). If it comes
   back:
   ```sh
   mount | grep mmcblk0p2      # still "ro"? filesystem hasn't recovered
   vcgencmd get_throttled       # anything but 0x0 = undervoltage, now or historically
   ```
   If it's `rw` and `get_throttled` is clean, retry the failed step
   (`sudo dpkg --configure -a`, then re-run `install.sh`/`system-upgrade`)
   once. If it fails again under write load, stop and go to step 3 — this is
   no longer a one-off.
3. **Test the SD card from another machine** (card reader, not the Pi):
   ```sh
   sudo badblocks -v /dev/sdX     # non-destructive read scan for bad sectors — replace sdX
   ```
   or run `f3` (Fight Flash Fraud) if you suspect a counterfeit/overreported-capacity
   card — extremely common with cheap unbranded cards.
4. **Power supply**: use an official/quality 5V/2.5A supply with a short,
   good-quality micro-USB cable. A phone charger or a PC's USB port is the
   single most common cause of exactly this failure on a Zero W under the
   combined CPU+I/O load of `apt`/`pip`/`venv` during install or
   `system-upgrade` (see `SYS-001` below) — this project has no battery/UPS
   to smooth over a brief sag.
5. **If it recurs even with confirmed-good power**: treat the card as
   suspect. Replace it — ideally a reputable-brand "High Endurance" /
   "Application class" card, meant for continuous writes and sudden power
   loss (the exact profile of a nonstop-running INDI + Web UI device), not a
   generic consumer card. Re-flash Bullseye Lite fresh rather than reusing a
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

Run `systemctl status japyscope-wifi-ap hostapd dnsmasq` and then
`sudo /usr/local/sbin/japyscope-wifi-ap --force`. The setup page is
`http://192.168.4.1:8080/setup`. The `hostapd` and `dnsmasq` journals contain
radio or DHCP errors.

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
