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

## System package upgrades

`system-upgrade` runs `apt-get update && apt-get upgrade` — patches within the
currently configured Bullseye repos only. It never runs `full-upgrade` or
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
