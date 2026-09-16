import io
import tarfile
from types import SimpleNamespace

import pytest

import install.update as update_module
from install.update import UpdateError, Updater, _safe_extract


def add_file(bundle, name, data=b"x"):
    info = tarfile.TarInfo(name); info.size = len(data); bundle.addfile(info, io.BytesIO(data))


def test_safe_extract_accepts_application_tree(tmp_path):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        add_file(bundle, "release/firmware/main.py")
        add_file(bundle, "release/webui/app.py")
        add_file(bundle, "release/requirements.txt")
        add_file(bundle, "release/requirements.lock")
    root = _safe_extract(archive, tmp_path / "out")
    assert root.name == "release"


def test_safe_extract_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle: add_file(bundle, "../escape")
    with pytest.raises(UpdateError): _safe_extract(archive, tmp_path / "out")


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
