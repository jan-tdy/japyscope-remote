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
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("japyscope.update")
API_BASE = "https://api.github.com"
DEFAULT_REPO = "jan-tdy/japyscope-remote"
DEFAULT_CHANNEL = "stable"  # stable | prerelease — see docs/CODES.md Dev Tools code 0033
API_URL = f"{API_BASE}/repos/{DEFAULT_REPO}/releases/latest"
MAX_DOWNLOAD = 100 * 1024 * 1024
# A prebuilt venv (PyIndi's compiled extension plus every pinned
# dependency) is far bigger than the source tarball capped by
# MAX_DOWNLOAD above -- give it its own, more generous ceiling instead of
# raising the source limit too.
MAX_VENV_DOWNLOAD = 512 * 1024 * 1024
VENV_ASSET_PREFIX = "japyscope-venv-"


class UpdateError(RuntimeError): pass


def _releases_url(repo: str, channel: str) -> str:
    # "stable" hits GitHub's /releases/latest, which already excludes
    # prereleases and drafts. "prerelease" has no equivalent single-release
    # endpoint, so it lists releases (newest first) and Updater.latest()
    # picks the first non-draft entry — prerelease or not.
    if channel == "prerelease":
        return f"{API_BASE}/repos/{repo}/releases"
    return f"{API_BASE}/repos/{repo}/releases/latest"


def _read_update_settings() -> tuple[str, str]:
    """Dev Tools codes 0022/0033 write these to shared.db; fall back to the
    hardcoded defaults if the DB isn't reachable (e.g. run standalone)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from shared.db import SettingsRepo, db_session

        with db_session() as conn:
            settings = SettingsRepo(conn)
            return (
                settings.get("update_repo", DEFAULT_REPO),
                settings.get("update_channel", DEFAULT_CHANNEL),
            )
    except Exception as exc:  # noqa: BLE001 — never let a settings read block an update check
        logger.warning("could not read update_repo/update_channel from shared.db: %s", exc)
        return DEFAULT_REPO, DEFAULT_CHANNEL


def _write_update_status(**fields: str) -> None:
    """Best-effort progress for the controller's Menu -> System -> Update
    screen (`firmware/ui/controller.py` polls these `state.update_*`
    keys) -- same tolerance as `_read_update_settings` above: a DB hiccup
    must never fail the update itself, just leave the screen with nothing
    to show. Keys are prefixed `update_` (e.g. `phase="downloading"` ->
    `state["update_phase"]`)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from shared.db import StateRepo, db_session

        with db_session() as conn:
            state = StateRepo(conn)
            for key, value in fields.items():
                state.set(f"update_{key}", value)
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not write update status to shared.db: %s", exc)


def _fetch_json(url: str) -> dict | list:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "japyscope-updater/0"})
    with urlopen(request, timeout=15) as response:
        return json.load(response)


def _download(url: str, destination: Path, max_size: int = MAX_DOWNLOAD) -> None:
    request = Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "japyscope-updater/0"})
    with urlopen(request, timeout=30) as response, destination.open("wb") as target:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk: break
            total += len(chunk)
            if total > max_size: raise UpdateError(f"release asset exceeds {max_size} bytes")
            target.write(chunk)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _select_asset(release: dict) -> tuple[dict, str]:
    # A release may additionally carry an optional japyscope-venv-*.tar.gz
    # precompiled-venv asset (see _select_precompiled_venv_asset below) --
    # that one is also a .tar.gz but is never the application source
    # tree, so it's excluded here rather than tripping the "exactly one"
    # check below.
    archives = [
        a for a in release.get("assets", [])
        if a.get("name", "").endswith(".tar.gz") and not a.get("name", "").startswith(VENV_ASSET_PREFIX)
    ]
    if len(archives) != 1: raise UpdateError("release must contain exactly one application .tar.gz asset")
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


def _os_codename() -> Optional[str]:
    """VERSION_CODENAME from /etc/os-release (e.g. "trixie"), or None if
    unreadable/unset -- never raises, since this only gates an
    optimization (see _try_install_precompiled_venv)."""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION_CODENAME="):
                return line.split("=", 1)[1].strip().strip('"') or None
    except OSError:
        return None
    return None


def _dpkg_architecture() -> Optional[str]:
    try:
        result = subprocess.run(
            ["dpkg", "--print-architecture"], capture_output=True, text=True, check=True, timeout=10,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _select_precompiled_venv_asset(release: dict, tag: str, codename: str, arch: str) -> Optional[tuple[dict, str]]:
    """The optional japyscope-venv-<codename>-<arch>-<tag>.tar.gz asset
    for this exact device, if the release carries one. Returns None (not
    an error) on any mismatch or verification shortfall -- the caller
    falls back to the on-device build either way."""
    expected_name = f"{VENV_ASSET_PREFIX}{codename}-{arch}-{tag}.tar.gz"
    asset = next((a for a in release.get("assets", []) if a.get("name") == expected_name), None)
    if asset is None: return None
    digest = asset.get("digest", "")
    if digest.startswith("sha256:"): return asset, digest[len("sha256:"):]
    checksum_name = asset["name"] + ".sha256"
    checksum = next((a for a in release.get("assets", []) if a.get("name") == checksum_name), None)
    if checksum is None:
        logger.warning("precompiled venv asset %s has no verifiable checksum; skipping", expected_name)
        return None
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / checksum_name
        _download(checksum["browser_download_url"], path)
        expected = path.read_text(encoding="ascii").split()[0]
    if len(expected) != 64 or any(c not in "0123456789abcdefABCDEF" for c in expected):
        logger.warning("precompiled venv asset %s has an invalid checksum file; skipping", expected_name)
        return None
    return asset, expected.lower()


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.isdev() or member.issym() or member.islnk():
                raise UpdateError(f"unsafe archive member: {member.name}")
        # filter="data" (PEP 706): members are already restricted to
        # plain files/dirs above, so this changes nothing extraction
        # actually does here -- it only silences the DeprecationWarning
        # tarfile.extractall() raises without an explicit filter, and
        # keeps this future-proof for Python 3.14's stricter default.
        bundle.extractall(destination, filter="data")
    roots = [entry for entry in destination.iterdir() if entry.name != archive.name]
    root = roots[0] if len(roots) == 1 and roots[0].is_dir() else destination
    if (
        not (root / "firmware" / "main.py").is_file()
        or not (root / "webui" / "app.py").is_file()
        or not (root / "requirements.lock").is_file()
        or not (root / "requirements-pyindi.lock").is_file()
    ):
        raise UpdateError("release does not contain a JapyScope application tree")
    return root


def _safe_extract_venv(archive: Path, destination: Path) -> Path:
    """Like _safe_extract, but for a packaged virtualenv: unlike the
    application source tree, a venv legitimately contains symlinks --
    `python3 -m venv`'s default (non---copies) layout links bin/python to
    the system interpreter by its absolute path (e.g. /usr/bin/python3.13),
    which is expected to resolve identically on every device running the
    same Raspberry Pi OS image this was built for. Only the archive
    member paths themselves are restricted to the destination tree; hard
    links and device nodes are still rejected -- venv has no legitimate
    use for either."""
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.isdev() or member.islnk():
                raise UpdateError(f"unsafe venv archive member: {member.name}")
        # filter="data" would reject the legitimate absolute-target
        # symlinks this function exists to allow (see docstring), so use
        # "tar" instead -- it still normalizes/rejects absolute member
        # paths and ".." traversal (redundant with the manual check
        # above, which stays as the actual enforcement), without
        # touching symlink targets. This only silences the
        # DeprecationWarning tarfile.extractall() raises without an
        # explicit filter (PEP 706) and keeps this future-proof for
        # Python 3.14's stricter default.
        bundle.extractall(destination, filter="tar")
    roots = [entry for entry in destination.iterdir()]
    root = roots[0] if len(roots) == 1 and roots[0].is_dir() else destination
    if not (root / "bin" / "python").exists() or not (root / "pyvenv.cfg").is_file():
        raise UpdateError("precompiled venv asset does not contain a valid virtualenv")
    return root


_APT_LOCK = Path("/var/lib/dpkg/lock-frontend")
_WRITABLE_PROBE = Path("/var/tmp/.japyscope-write-test")


def _check_writable_root() -> None:
    """Fail fast — and do not retry — on a genuinely read-only root
    filesystem. Real bring-up hit this from marginal power / a degrading SD
    card (see docs/TROUBLESHOOTING.md's "Filesystem went read-only");
    retrying apt against an already-corrupted filesystem risks making it
    worse, so this is deliberately not one of the self-healing steps below.
    """
    try:
        _WRITABLE_PROBE.write_text("x")
        _WRITABLE_PROBE.unlink()
    except OSError as exc:
        raise UpdateError(
            "SYS-001 root filesystem is read-only — see docs/TROUBLESHOOTING.md "
            "'Filesystem went read-only'; this is not safely auto-fixable"
        ) from exc


def _wait_for_apt_lock(timeout: float = 120.0) -> None:
    """Cooperate with apt/dpkg's own lock (same file, same flock mechanism)
    instead of racing it — common right after boot if unattended-upgrades
    or a previous run is still finishing."""
    if not _APT_LOCK.exists():
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _APT_LOCK.open("w") as lock_file:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock_file, fcntl.LOCK_UN)
                return
            except BlockingIOError:
                pass
        time.sleep(2)
    raise UpdateError("SYS-001 timed out waiting for another apt/dpkg process to finish")


def _heal_dpkg() -> None:
    """Resolve a half-configured package left by an interrupted previous
    apt/dpkg run (power loss, a prior crash) before installing anything
    new. Safe no-op if nothing is broken."""
    subprocess.run(["dpkg", "--configure", "-a"], check=False)


def _apt_upgrade() -> None:
    """Refresh and upgrade system packages within the currently configured
    the installed release's repos. Deliberately just `apt-get update && apt-get upgrade`
    — never `full-upgrade`/`dist-upgrade`, and this never touches apt
    sources — so it cannot pull the device onto Bookworm or any other
    release on its own. Runs as its own systemd step (see
    install/systemd/japyscope-update.service), separate from the
    JapyScope release install below, so a transient apt failure never
    blocks or gets rolled back with an app update.

    Self-heals what's safely fixable (interrupted dpkg, a held lock,
    a transient apt failure — retried up to 3 times, with a growing pause
    between attempts rather than hammering a possibly-struggling card/power
    supply) and fails immediately, without retrying at all, on a read-only
    root filesystem.
    """
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    upgrade_command = [
        "apt-get", "-y",
        "-o", "Dpkg::Options::=--force-confdef",
        "-o", "Dpkg::Options::=--force-confold",
        "upgrade",
    ]
    # Deliberately spaced out, not a tight loop — a struggling SD card or
    # power supply needs breathing room, not to be hit again 5 seconds
    # later. 30s, then 2 minutes; nothing after the final attempt.
    retry_backoff_s = (30, 120)
    last_exc: Optional[BaseException] = None
    for attempt in range(1, 4):
        _check_writable_root()
        _wait_for_apt_lock()
        _heal_dpkg()
        try:
            subprocess.run(["apt-get", "update"], check=True, timeout=300, env=env)
            subprocess.run(upgrade_command, check=True, timeout=1800, env=env)
            return
        except (OSError, subprocess.SubprocessError) as exc:
            last_exc = exc
            logger.warning("system package upgrade attempt %d/3 failed: %s", attempt, exc)
            if attempt < 3:
                time.sleep(retry_backoff_s[attempt - 1])
    raise UpdateError(f"SYS-001 system package upgrade failed after 3 attempts: {last_exc}") from last_exc


class Updater:
    def __init__(
        self,
        root: Path = Path("/opt/japyscope"),
        repo: str = DEFAULT_REPO,
        channel: str = DEFAULT_CHANNEL,
        api_url: Optional[str] = None,
    ):
        self.root = root
        self.releases = root / "releases"
        self.current = root / "current"
        self.repo = repo
        self.channel = channel
        self.api_url = api_url or _releases_url(repo, channel)

    def latest(self) -> dict:
        if self.channel == "prerelease":
            for release in _fetch_json(self.api_url):
                if not release.get("draft"):
                    return release
            raise UpdateError(f"no non-draft releases found for {self.repo}")
        return _fetch_json(self.api_url)

    def current_version(self) -> Optional[str]:
        # A `current` whose release directory is gone (deleted by hand, or an
        # interrupted update) is not a running version: reporting its name
        # makes apply() think the device is already up to date.
        if not self.current.is_symlink() or not self.current.exists(): return None
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
            _write_update_status(status="running", phase="checking", error="")
            try:
                release = self.latest()
                tag = release.get("tag_name", "").strip()
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tag):
                    raise UpdateError("unsafe release tag")
                if tag == self.current_version():
                    _write_update_status(status="idle", phase="up_to_date")
                    return tag
                target = self.releases / tag
                if target.exists():
                    # The live release was handled above, so this is what an
                    # earlier update that died mid-install left behind.
                    logger.warning("removing leftover release directory from an interrupted update: %s", target)
                    shutil.rmtree(target)
                asset, expected = _select_asset(release)
                previous = self.current.resolve() if self.current.exists() else None
                _write_update_status(phase="downloading", tag=tag)
                with tempfile.TemporaryDirectory(dir=self.root) as temp_name:
                    temp = Path(temp_name); archive = temp / asset["name"]
                    _download(asset["browser_download_url"], archive)
                    actual = _sha256(archive)
                    if actual != expected: raise UpdateError("OTA-002 release checksum verification failed")
                    extracted = _safe_extract(archive, temp / "extract")
                    shutil.move(str(extracted), target)
            except (UpdateError, OSError, HTTPError, URLError, TimeoutError) as exc:
                _write_update_status(status="failed", phase="failed", error=str(exc)[:160])
                raise
            _write_update_status(phase="installing")
            try:
                if self._venv_reusable(previous, target):
                    # Most releases are code-only hotfixes with an
                    # unchanged requirements.lock/requirements-pyindi.lock
                    # -- rebuilding the venv from scratch then re-installs
                    # the exact same pinned versions it already has,
                    # which on this hardware is most of an update's
                    # wall-clock time for zero actual change. Copying the
                    # previous release's already-built venv is safe here
                    # specifically because every invocation in this
                    # codebase (this file, firmware/main.py, and the
                    # systemd units, which always launch via the
                    # `current` symlink) names the venv's python by an
                    # explicit absolute path rather than relying on a
                    # console-script's baked-in shebang.
                    logger.info("requirements unchanged since %s; reusing its venv", previous.name)
                    shutil.copytree(previous / ".venv", target / ".venv", symlinks=True)
                elif self._try_install_precompiled_venv(release, tag, target):
                    logger.info("installed precompiled venv for this device's OS/architecture")
                else:
                    subprocess.run(["python3", "-m", "venv", str(target / ".venv")], check=True, timeout=180)
                    subprocess.run(
                        [str(target / ".venv" / "bin" / "python"), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
                        check=True, timeout=300,
                    )
                    subprocess.run(
                        [str(target / ".venv" / "bin" / "python"), "-m", "pip", "install", "--require-hashes", "-r", str(target / "requirements.lock")],
                        check=True, timeout=900,
                    )
                    # Separate, --no-deps, --no-build-isolation install — see
                    # requirements-pyindi.lock and install.sh for why
                    # pyindi-client can't go through the main hash-locked
                    # install on this hardware (bottle/dbus-python unused and
                    # unbuildable; --no-build-isolation makes its swig build
                    # dependency resolve to the system swig, not a PyPI-bundled
                    # binary that needs a newer glibc than Bullseye has).
                    subprocess.run(
                        [str(target / ".venv" / "bin" / "python"), "-m", "pip", "install", "--require-hashes", "--no-deps", "--no-build-isolation", "-r", str(target / "requirements-pyindi.lock")],
                        check=True, timeout=300,
                    )
                subprocess.run([str(target / ".venv" / "bin" / "python"), "-m", "compileall", "-q", str(target)], check=True, timeout=120)
                # An OTA update only ever extracts code into releases/<tag>
                # and flips the `current` symlink — unlike install.sh, it
                # never re-copies /usr/local/sbin/japyscope-*, the sudoers
                # file, or the systemd units. Without this, those OS-level
                # files silently keep running whatever a past install.sh
                # run left behind, however much a newer release's
                # install/*.sh, the sudoers line, or a unit changes (seen
                # on real hardware as a WIFI-001 failure: the installed
                # japyscope-wifi script rejected --slot because it
                # predated that flag). Must run — and its systemd unit
                # copy + daemon-reload land — before the restart below, or
                # that restart still runs under the old unit definitions.
                self._sync_system_files(target)
                self._flip(target)
                # Written before the restart below (which kills this very
                # process's controller) so the controller that comes back
                # up actually sees "success" on its first boot-time state
                # read, instead of racing its own restart to write it.
                _write_update_status(status="success", phase="done", tag=tag)
                subprocess.run(["systemctl", "restart", "japyscope-app.service", "japyscope-webui.service"], check=True, timeout=30)
                self._health_check()
            except (OSError, subprocess.SubprocessError, UpdateError) as exc:
                logger.error("OTA-003 new release failed health check; rolling back: %s", exc)
                if previous is not None:
                    self._flip(previous)
                    # Match the OS-level files back to the release we're
                    # rolling back to — a release built before this sync
                    # step existed has no such script, in which case the
                    # new release's sync (which already ran above) is left
                    # in place rather than erroring the rollback over it.
                    self._sync_system_files(previous, required=False)
                    _write_update_status(status="failed", phase="rolled_back", error=str(exc)[:160])
                    subprocess.run(["systemctl", "restart", "japyscope-app.service", "japyscope-webui.service"], check=False, timeout=30)
                else:
                    _write_update_status(status="failed", phase="failed", error=str(exc)[:160])
                raise UpdateError("OTA-003 update failed and was rolled back") from exc
            return tag

    @staticmethod
    def _venv_reusable(previous: Optional[Path], target: Path) -> bool:
        """Whether `target`'s dependencies are byte-identical to
        `previous`'s already-built venv, so that venv can just be copied
        instead of rebuilt. Hash-locked requirements files mean "same
        file contents" really does mean "same resolved, verified
        dependency set" -- there's nothing a fresh `pip install` would
        do differently."""
        if previous is None or not (previous / ".venv").is_dir():
            return False
        for name in ("requirements.lock", "requirements-pyindi.lock"):
            previous_lock = previous / name
            target_lock = target / name
            if not previous_lock.is_file() or not target_lock.is_file():
                return False
            if previous_lock.read_bytes() != target_lock.read_bytes():
                return False
        return True

    @staticmethod
    def _try_install_precompiled_venv(release: dict, tag: str, target: Path) -> bool:
        """When dependencies changed since the previous release (so
        _venv_reusable above can't apply), try installing a venv
        prebuilt in CI for this exact device's OS codename and dpkg
        architecture instead of `pip install`-ing from source on the Pi
        Zero itself -- that on-device build is what has been timing out
        and triggering a rollback on every dependency bump (see
        docs/UPDATE.md). This is purely a fast path: on a mismatched
        codename/architecture, a missing asset, a checksum failure, or
        any other problem, it cleans up after itself and returns False so
        the caller falls back to the slow but always-available on-device
        build below."""
        target_venv = target / ".venv"
        try:
            codename = _os_codename()
            arch = _dpkg_architecture()
            if codename is None or arch is None:
                return False
            selection = _select_precompiled_venv_asset(release, tag, codename, arch)
            if selection is None:
                return False
            asset, expected = selection
            _write_update_status(phase="downloading_venv", tag=tag)
            with tempfile.TemporaryDirectory(dir=target.parent) as temp_name:
                temp = Path(temp_name)
                archive = temp / asset["name"]
                _download(asset["browser_download_url"], archive, max_size=MAX_VENV_DOWNLOAD)
                if _sha256(archive) != expected:
                    logger.warning("precompiled venv checksum mismatch; falling back to on-device build")
                    return False
                extracted = _safe_extract_venv(archive, temp / "extract")
                if target_venv.exists():
                    shutil.rmtree(target_venv)
                shutil.move(str(extracted), target_venv)
            # The extracted venv was built on a GitHub Actions QEMU
            # runner, not this device -- confirm it actually runs and
            # that the compiled PyIndi extension loads before trusting it
            # for the install this method is otherwise skipping.
            subprocess.run(
                [str(target_venv / "bin" / "python"), "-c", "import PyIndi"], check=True, timeout=30,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — a glitch in this optimization must never fail the update
            logger.warning("precompiled venv install failed (%s); falling back to on-device build", exc)
            shutil.rmtree(target_venv, ignore_errors=True)
            return False

    @staticmethod
    def _sync_system_files(release: Path, required: bool = True) -> None:
        script = release / "install" / "sync-system-files.sh"
        if not script.is_file():
            if required:
                raise UpdateError(f"release is missing install/sync-system-files.sh: {release}")
            return
        subprocess.run(["bash", str(script)], check=required, timeout=30)

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
    parser.add_argument("--repo", default=None, help="owner/repo (default: read from shared.db, else %s" % DEFAULT_REPO)
    parser.add_argument("--channel", choices=("stable", "prerelease"), default=None, help="default: read from shared.db, else stable")
    parser.add_argument("--api-url", default=None, help="override the computed GitHub API URL entirely")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        if args.action == "system-upgrade":
            _apt_upgrade(); print("system packages upgraded")
        else:
            repo, channel = args.repo, args.channel
            if repo is None or channel is None:
                db_repo, db_channel = _read_update_settings()
                repo = repo or db_repo
                channel = channel or db_channel
            updater = Updater(args.root, repo=repo, channel=channel, api_url=args.api_url)
            if args.action == "check":
                tag, available = updater.check(); print(f"{tag} {'available' if available else 'current'}")
            else: print(f"installed {updater.apply()}")
    except (UpdateError, HTTPError, URLError, TimeoutError) as exc:
        logger.error("OTA-001 update failed: %s", exc); return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
