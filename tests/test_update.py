import io
import tarfile
from types import SimpleNamespace

import pytest

import install.update as update_module
from install.update import (
    UpdateError,
    Updater,
    _apt_upgrade,
    _safe_extract,
    _select_asset,
)


def add_file(bundle, name, data=b"x"):
    info = tarfile.TarInfo(name); info.size = len(data); bundle.addfile(info, io.BytesIO(data))


def test_safe_extract_accepts_application_tree(tmp_path):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        add_file(bundle, "release/firmware/main.py")
        add_file(bundle, "release/webui/app.py")
        add_file(bundle, "release/requirements.txt")
        add_file(bundle, "release/requirements.lock")
        add_file(bundle, "release/requirements-pyindi.lock")
    root = _safe_extract(archive, tmp_path / "out")
    assert root.name == "release"


def test_safe_extract_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle: add_file(bundle, "../escape")
    with pytest.raises(UpdateError): _safe_extract(archive, tmp_path / "out")


def test_safe_extract_reports_malformed_archive(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    archive.write_bytes(b"not a tarball")
    with pytest.raises(UpdateError, match="valid tar.gz"):
        _safe_extract(archive, tmp_path / "out")


def test_select_asset_reports_empty_checksum(tmp_path, monkeypatch):
    release = {
        "assets": [
            {
                "name": "japyscope-remote-v1.0.0.tar.gz",
                "browser_download_url": "unused",
                "digest": None,
            },
            {
                "name": "japyscope-remote-v1.0.0.tar.gz.sha256",
                "browser_download_url": "unused",
            },
        ]
    }
    monkeypatch.setattr(update_module, "_download", lambda _url, path: path.write_bytes(b""))
    with pytest.raises(UpdateError, match="invalid SHA-256 checksum file"):
        _select_asset(release)


def test_apt_upgrade_never_touches_dist_upgrade(monkeypatch):
    calls = []
    def run(command, check=False, timeout=None, env=None):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(update_module.subprocess, "run", run)
    _apt_upgrade()
    assert calls[0] == ["dpkg", "--configure", "-a"]  # self-heal before touching apt
    assert calls[1] == ["apt-get", "-o", "DPkg::Lock::Timeout=120", "update"]
    assert calls[2][:3] == ["apt-get", "-y", "-o"]
    assert "upgrade" in calls[2]
    assert "dist-upgrade" not in calls[2] and "full-upgrade" not in calls[2]


def test_apt_upgrade_failure_raises_sys_001(monkeypatch):
    import subprocess as subprocess_module
    def run(command, check=False, timeout=None, env=None):
        if check:  # mirror real subprocess.run: check=False (dpkg heal) never raises
            raise subprocess_module.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(update_module.subprocess, "run", run)
    monkeypatch.setattr(update_module.time, "sleep", lambda _seconds: None)
    with pytest.raises(UpdateError, match="SYS-001"):
        _apt_upgrade()


def test_apt_upgrade_retries_transient_failure_then_succeeds(monkeypatch):
    import subprocess as subprocess_module
    calls = []
    attempts = {"apt_update": 0}
    def run(command, check=False, timeout=None, env=None):
        calls.append(list(command))
        if command == ["apt-get", "-o", "DPkg::Lock::Timeout=120", "update"]:
            attempts["apt_update"] += 1
            if attempts["apt_update"] == 1:
                raise subprocess_module.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(update_module.subprocess, "run", run)
    monkeypatch.setattr(update_module.time, "sleep", lambda _seconds: None)
    _apt_upgrade()  # must not raise — second attempt succeeds
    assert calls.count(["dpkg", "--configure", "-a"]) == 2  # healed before each attempt
    assert calls.count(["apt-get", "-o", "DPkg::Lock::Timeout=120", "update"]) == 2


def test_apt_upgrade_fails_fast_without_retry_on_readonly_root(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(update_module.subprocess, "run", lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(update_module, "_WRITABLE_PROBE", tmp_path / "missing-dir" / "probe")
    with pytest.raises(UpdateError, match="SYS-001.*read-only"):
        _apt_upgrade()
    assert calls == []  # never even tried apt/dpkg


def test_health_check_checks_services_separately(monkeypatch):
    calls = []
    times = iter((0, 0, 31))
    monkeypatch.setattr(update_module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(update_module.time, "sleep", lambda _seconds: None)
    def run(command, check=False):
        calls.append(command)
        return SimpleNamespace(returncode=0 if command[-1] == "japyscope-app.service" else 1)
    monkeypatch.setattr(update_module.subprocess, "run", run)
    with pytest.raises(UpdateError): Updater._health_check()
    assert calls == [
        ["systemctl", "is-active", "--quiet", "japyscope-app.service"],
        ["systemctl", "is-active", "--quiet", "japyscope-webui.service"],
    ]


def test_health_error_rolls_back_current_symlink(tmp_path, monkeypatch):
    root = tmp_path / "root"; releases = root / "releases"; previous = releases / "old"
    previous.mkdir(parents=True); (root / "current").symlink_to(previous)
    updater = Updater(root)
    monkeypatch.setattr(updater, "latest", lambda: {"tag_name": "new"})
    monkeypatch.setattr(update_module, "_select_asset", lambda _release: ({"name": "release.tar.gz", "browser_download_url": "unused"}, "hash"))
    monkeypatch.setattr(update_module, "_download", lambda _url, path: path.write_bytes(b"archive"))
    monkeypatch.setattr(update_module, "_sha256", lambda _path: "hash")
    extracted = tmp_path / "extracted"; extracted.mkdir()
    monkeypatch.setattr(update_module, "_safe_extract", lambda *_args: extracted)
    monkeypatch.setattr(update_module.shutil, "move", lambda _source, target: target.mkdir())
    monkeypatch.setattr(update_module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(updater, "_health_check", lambda: (_ for _ in ()).throw(UpdateError("unhealthy")))
    with pytest.raises(UpdateError): updater.apply()
    assert updater.current.resolve() == previous
    assert not (releases / "new").exists()


def test_apply_replaces_failed_directory(tmp_path, monkeypatch):
    root = tmp_path / "root"
    releases = root / "releases"
    current = releases / "old"
    failed = releases / "new"
    current.mkdir(parents=True)
    failed.mkdir()
    (failed / "stale").write_text("failed")
    (root / "current").symlink_to(current)
    updater = Updater(root)

    monkeypatch.setattr(updater, "latest", lambda: {"tag_name": "new"})
    monkeypatch.setattr(update_module, "_select_asset", lambda _release: ({"name": "release.tar.gz", "browser_download_url": "unused"}, "hash"))
    monkeypatch.setattr(update_module, "_download", lambda _url, path: path.write_bytes(b"archive"))
    monkeypatch.setattr(update_module, "_sha256", lambda _path: "hash")
    extracted = tmp_path / "extracted"; extracted.mkdir()
    monkeypatch.setattr(update_module, "_safe_extract", lambda *_args: extracted)
    monkeypatch.setattr(update_module.shutil, "move", lambda _source, target: target.mkdir())
    monkeypatch.setattr(update_module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(updater, "_health_check", lambda: None)
    assert updater.apply() == "new"
    assert updater.current.resolve() == failed
    assert not (failed / "stale").exists()
