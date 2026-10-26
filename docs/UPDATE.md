---
layout: default
title: Updating JapyScope
permalink: /update/
---
# Summary

To update, use the Web UI’s “Check for update now” button.

# OTA updates and rollback

`install/update.py` installs GitHub Releases transactionally. The release must
contain exactly one `.tar.gz` application asset. It must also have either a
GitHub asset `sha256:` digest or a companion `<asset>.sha256` release asset.
Unsigned source archives without either checksum are rejected.

The archive must contain `firmware/main.py`, `webui/app.py`, and the generated
`requirements.lock`. Dependencies, including PyIndi, are installed only from
that fully pinned SHA-256 hash lock. The updater rejects absolute paths, traversal, links, and
device nodes before extraction, creates a fresh virtual environment in a new
versioned release directory, then atomically flips `/opt/japyscope/current`.

## Commands

```sh
sudo /opt/japyscope/current/.venv/bin/python /opt/japyscope/current/install/update.py check
sudo /opt/japyscope/current/.venv/bin/python /opt/japyscope/current/install/update.py apply
sudo /opt/japyscope/current/.venv/bin/python /opt/japyscope/current/install/update.py system-upgrade
```

The enabled `japyscope-update.timer` runs both `system-upgrade` and `apply` once
per day with a randomized delay (`japyscope-update.service` has two `ExecStart`
lines). `apply` is idempotent when the latest tag is already active.

The Web UI's System tab has a "Check for update now" button that runs
`sudo systemctl start japyscope-update.service` immediately, without waiting for
the timer. Progress and results can be followed in Diagnostics under the
`japyscope-update` service.

## System package upgrades

`system-upgrade` runs `apt-get update && apt-get upgrade` — patches within the
currently configured Raspberry Pi OS repos only. It never runs `full-upgrade` or
`dist-upgrade`, and never touches `/etc/apt/sources.list`, so it cannot move
the device onto Bookworm or any other release on its own. It's a separate,
best-effort step from the JapyScope release install above (see the `-`-prefixed
`ExecStart` in `japyscope-update.service`): a transient `apt` failure is logged
as `SYS-001` but never blocks or gets rolled back with an app update.

## Rollback behavior

The previous symlink target is retained. If dependency installation,
byte-compilation, service restart, or the 30-second systemd health check fails,
the updater restores the previous symlink and restarts both application
services. The failed version is left in `releases/` for diagnosis and will not
be overwritten automatically.

Relevant log codes are `OTA-001` (network/API/update failure), `OTA-002`
(checksum mismatch), and `OTA-003` (new release failed and rollback ran).

## Precompiled venv (dependency bumps on the Pi Zero W)

A dependency bump (a changed `requirements.lock`/`requirements-pyindi.lock`)
used to mean building the new venv on the device itself — on a Pi Zero W
(single ARM1176 core, 512 MB RAM) that `pip install` can take long enough to
hit the installer's own timeouts, which looks like (and is logged as) an
`OTA-003` rollback even though nothing is actually wrong with the release.

When the release carries a `japyscope-venv-<codename>-armhf-<tag>.tar.gz`
asset matching the device's own `/etc/os-release` `VERSION_CODENAME` and
`dpkg --print-architecture`, the updater downloads and verifies it (same
SHA-256 digest/sidecar check as the application tarball) and extracts it
straight to `releases/<tag>/.venv` instead of running `pip install` at all.
`.github/workflows/build-venv-trixie-armhf.yml` builds that asset in CI,
under QEMU, against the same dependency set `test-trixie-armhf.yml`
already validates on every PR, and attaches it to the tag's release.

This is a pure optimization with no effect on correctness: a codename or
architecture mismatch, a missing asset, a checksum failure, or the
extracted venv failing to import `PyIndi` all fall back to the on-device
build (venv reuse first if dependencies didn't actually change, then the
full `pip install` as before). The precompiled asset is currently only
built for Trixie/armhf; devices on Bullseye or Bookworm always take the
on-device build path.
