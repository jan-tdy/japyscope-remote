#!/usr/bin/env python3
"""Transactional GitHub Releases updater with checksum verification."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("japyscope.update")
API_URL = "https://api.github.com/repos/jan-tdy/japyscope-remote/releases/latest"
MAX_DOWNLOAD = 100 * 1024 * 1024


class UpdateError(RuntimeError): pass


def _fetch_json(url: str) -> dict:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "japyscope-updater/0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def _download(url: str, destination: Path) -> None:
    request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "japyscope-updater/0"})
    with urlopen(request, timeout=30) as response, destination.open("wb") as target:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk: break
            total += len(chunk)
            if total > MAX_DOWNLOAD: raise UpdateError("release asset exceeds 100 MiB")
            target.write(chunk)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _select_asset(release: dict) -> tuple[dict, str]:
    archives = [a for a in release.get("assets", []) if a.get("name", "").endswith(".tar.gz")]
    if len(archives) != 1: raise UpdateError("release must contain exactly one .tar.gz asset")
    asset = archives[0]
    if Path(asset.get("name", "")).name != asset.get("name"):
        raise UpdateError("unsafe release asset name")
    digest = asset.get("digest", "")
    if digest.startswith("sha256:"): return asset, digest[len("sha256:"):]
    checksum_name = asset["name"] + ".sha256"
    checksum = next((a for a in release.get("assets", []) if a.get("name") == checksum_name), None)
    if checksum is None: raise UpdateError(f"release lacks GitHub digest or {checksum_name}")
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / checksum_name
        _download(checksum["browser_download_url"], path)
        expected = path.read_text(encoding="ascii").split()[0]
    if len(expected) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected):
        raise UpdateError("invalid SHA-256 checksum file")
    return asset, expected.lower()


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.isdev() or member.issym() or member.islnk():
                raise UpdateError(f"unsafe archive member: {member.name}")
        bundle.extractall(destination)
    roots = [entry for entry in destination.iterdir() if entry.name != archive.name]
    root = roots[0] if len(roots) == 1 and roots[0].is_dir() else destination
    if (
        not (root / "firmware" / "main.py").is_file()
        or not (root / "webui" / "app.py").is_file()
        or not (root / "requirements.lock").is_file()
    ):
        raise UpdateError("release does not contain a JapyScope application tree")
    return root


def _apt_upgrade() -> None:
    """Refresh and upgrade system packages within the currently configured
    Bullseye repos. Deliberately just `apt-get update && apt-get upgrade`
    — never `full-upgrade`/`dist-upgrade`, and this never touches apt
    sources — so it cannot pull the device onto Bookworm or any other
    release on its own. Runs as its own systemd step (see
    install/systemd/japyscope-update.service), separate from the
    JapyScope release install below, so a transient apt failure never
    blocks or gets rolled back with an app update.
    """
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    try:
        subprocess.run(["apt-get", "update"], check=True, timeout=300, env=env)
        subprocess.run(
            [
                "apt-get", "-y",
                "-o", "Dpkg::Options::=--force-confdef",
                "-o", "Dpkg::Options::=--force-confold",
                "upgrade",
            ],
            check=True, timeout=1800, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise UpdateError(f"SYS-001 system package upgrade failed: {exc}") from exc


class Updater:
    def __init__(self, root: Path = Path("/opt/japyscope"), api_url: str = API_URL):
        self.root = root
        self.releases = root / "releases"
        self.current = root / "current"
        self.api_url = api_url

    def latest(self) -> dict: return _fetch_json(self.api_url)

    def current_version(self) -> Optional[str]:
        if not self.current.is_symlink(): return None
        return self.current.resolve().name

    def check(self) -> tuple[str, bool]:
        tag = self.latest().get("tag_name", "").strip()
        if not tag: raise UpdateError("latest release has no tag_name")
        return tag, tag != self.current_version()

    def apply(self) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        self.releases.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".update.lock"
        with lock_path.open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise UpdateError("another update is already running") from exc
            release = self.latest()
            tag = release.get("tag_name", "").strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
                raise UpdateError("unsafe release tag")
            if tag == self.current_version(): return tag
            target = self.releases / tag
            if target.exists(): raise UpdateError(f"release directory already exists: {target}")
            asset, expected = _select_asset(release)
            previous = self.current.resolve() if self.current.is_symlink() else None
            with tempfile.TemporaryDirectory(dir=self.root) as temp_name:
                temp = Path(temp_name); archive = temp / asset["name"]
                _download(asset["browser_download_url"], archive)
                actual = _sha256(archive)
                if actual != expected: raise UpdateError("OTA-002 release checksum verification failed")
                extracted = _safe_extract(archive, temp / "extract")
                shutil.move(str(extracted), target)
            try:
                subprocess.run(["python3", "-m", "venv", str(target / ".venv")], check=True, timeout=60)
                subprocess.run(
                    [str(target / ".venv" / "bin" / "python"), "-m", "pip", "install", "--require-hashes", "-r", str(target / "requirements.lock")],
                    check=True, timeout=900,
                )
                subprocess.run([str(target / ".venv" / "bin" / "python"), "-m", "compileall", "-q", str(target)], check=True, timeout=60)
                self._flip(target)
                subprocess.run(["systemctl", "restart", "japyscope-app.service", "japyscope-webui.service"], check=True, timeout=30)
                self._health_check()
            except (OSError, subprocess.SubprocessError, UpdateError) as exc:
                logger.error("OTA-003 new release failed health check; rolling back: %s", exc)
                if previous is not None:
                    self._flip(previous)
                    subprocess.run(["systemctl", "restart", "japyscope-app.service", "japyscope-webui.service"], check=False, timeout=30)
                raise UpdateError("OTA-003 update failed and was rolled back") from exc
            return tag

    def _flip(self, target: Path) -> None:
        temporary = self.root / ".current.new"
        if temporary.exists() or temporary.is_symlink(): temporary.unlink()
        temporary.symlink_to(target)
        os.replace(temporary, self.current)

    @staticmethod
    def _health_check() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            service_results = [
                subprocess.run(
                    ["systemctl", "is-active", "--quiet", service], check=False
                ).returncode
                for service in ("japyscope-app.service", "japyscope-webui.service")
            ]
            if all(returncode == 0 for returncode in service_results):
                try:
                    with urlopen("http://127.0.0.1:8080/healthz", timeout=2) as response:
                        if response.status == 200: return
                except (OSError, URLError):
                    pass
            time.sleep(2)
        raise UpdateError("services did not become healthy within 30 seconds")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "apply", "system-upgrade"))
    parser.add_argument("--root", type=Path, default=Path("/opt/japyscope"))
    parser.add_argument("--api-url", default=API_URL)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.action == "system-upgrade":
            _apt_upgrade(); print("system packages upgraded")
        else:
            updater = Updater(args.root, args.api_url)
            if args.action == "check":
                tag, available = updater.check(); print(f"{tag} {'available' if available else 'current'}")
            else: print(f"installed {updater.apply()}")
    except (UpdateError, HTTPError, URLError, TimeoutError) as exc:
        logger.error("OTA-001 update failed: %s", exc); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
