"""Reads the firmware's actual running version — the release tag that
`/opt/japyscope/current` resolves to (install/update.py's `Updater` lays
out releases this way: `releases/<tag>/`, `current` symlinked to the
active one). Deliberately not importing that module here: it pulls in
`requests` and other OTA-only machinery the firmware app has no other
reason to need just to show a version string on the ABOUT screen.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DEFAULT_RELEASE_ROOT = Path(os.environ.get("JAPYSCOPE_RELEASE_ROOT", "/opt/japyscope"))


def current_version(root: Path = DEFAULT_RELEASE_ROOT) -> Optional[str]:
    """The release tag currently live, or None outside an installed
    release (a dev checkout, --simulate, tests) — `root/"current"` is only
    ever a symlink on an actual install (install/install.sh, update.py)."""
    current = root / "current"
    if not current.is_symlink():
        return None
    return current.resolve().name
