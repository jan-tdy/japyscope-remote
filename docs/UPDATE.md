# Update (OTA) manual — placeholder

Not written yet — `install/update.py` doesn't exist yet either (see
[ARCHITECTURE.md → Remaining work, item 6](ARCHITECTURE.md#remaining-work-for-v0-handoff)).

Known design (to be documented in detail once built):

- Polls this repo's GitHub Releases API for the latest tag.
- Downloads the release tarball, verifies it, installs to a versioned
  directory under `/opt/japyscope/releases/`, flips a `current` symlink.
- Health-checks the new version after restart; rolls the symlink back and
  restarts on failure.
- Triggered from the controller's menu ("Check for updates") and/or a
  periodic systemd timer.
