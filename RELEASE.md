# Cutting a release

This is the process for publishing a version that devices in the field will
actually pick up via OTA (`install/update.py`, checked hourly-ish by the
`japyscope-update.timer` systemd timer, or on demand — see below).

## What `install/update.py` actually requires

Read this before changing the process — the updater (`install/update.py`)
is strict on purpose:

- The GitHub Release for the tag must contain **exactly one** `*.tar.gz`
  asset. More or fewer, and `apply()` refuses to install anything.
- That tarball must extract to a single top-level directory containing (at
  minimum) `firmware/main.py`, `webui/app.py`, and `requirements.lock` —
  i.e. it needs to be this repo's tracked tree at that tag, not some other
  subset of files.
- The asset needs a verifiable SHA-256: either GitHub's own asset `digest`
  (present automatically on most uploads) or a sidecar
  `<asset-name>.sha256` file (plain `sha256sum` output format) uploaded
  alongside it. The updater checks both.
- The tag name must match `[A-Za-z0-9][A-Za-z0-9._-]*` (anything sane like
  `v0.2.0` works; don't use spaces or slashes).
- `requirements.lock` must stay a valid `pip-compile --generate-hashes`
  lock file — `apply()` installs it with `pip install --require-hashes`,
  which fails outright on an unpinned or stale lock file.

The GitHub Action below (`.github/workflows/release.yml`) builds and
uploads an asset that satisfies all of this automatically from a `git
archive` of the tag — you shouldn't need to build the tarball by hand.

## Steps

1. **Land your changes on `main`** as normal.

2. **If `requirements.txt` changed**, regenerate the lock file before
   tagging (this repo doesn't do it automatically):
   ```
   pip install pip-tools
   pip-compile --generate-hashes --output-file=requirements.lock requirements.txt
   ```
   Commit the updated `requirements.lock`.

3. **Pick a version** (semver-ish is fine: `vMAJOR.MINOR.PATCH`, e.g.
   `v0.2.0`). There's no separate version file to bump — the tag itself
   *is* the version; `/opt/japyscope/current` is a symlink to
   `/opt/japyscope/releases/<tag>` on every device.

4. **Tag and push**:
   ```
   git tag v0.2.0
   git push origin v0.2.0
   ```

5. **The GitHub Action takes it from there**: on seeing the new tag, it
   builds `japyscope-remote-<tag>.tar.gz` via `git archive`, computes its
   SHA-256 into `<asset>.sha256`, and creates (or updates) the GitHub
   Release for that tag with both files attached and auto-generated
   release notes. Check the *Actions* tab if you want to watch it run, and
   the repo's *Releases* page afterward to confirm exactly one `.tar.gz` +
   its `.sha256` are attached.

6. **Devices pick it up**:
   - Automatically, next time `japyscope-update.timer` fires (daily, plus
     up to 30 min random jitter, per `install/systemd/japyscope-update.timer`).
   - Immediately, by running on the device (or over SSH):
     ```
     sudo /opt/japyscope/current/.venv/bin/python /opt/japyscope/current/install/update.py apply
     ```
     (`check` instead of `apply` just reports whether a newer tag exists,
     without installing it.)
   - A failed health check after install automatically rolls the `current`
     symlink back to the previous release and restarts the services — see
     `docs/UPDATE.md` / `docs/TROUBLESHOOTING.md` for the `OTA-00x` error
     codes this can log.

## If you ever need to build the release asset by hand

(The Action should make this unnecessary — this is a fallback.)

```
TAG=v0.2.0
git archive --format=tar.gz --prefix="japyscope-remote-${TAG}/" \
  -o "japyscope-remote-${TAG}.tar.gz" "$TAG"
sha256sum "japyscope-remote-${TAG}.tar.gz" > "japyscope-remote-${TAG}.tar.gz.sha256"
gh release create "$TAG" \
  "japyscope-remote-${TAG}.tar.gz" "japyscope-remote-${TAG}.tar.gz.sha256" \
  --title "$TAG" --generate-notes
```
