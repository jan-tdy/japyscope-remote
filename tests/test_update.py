import io
import tarfile

import pytest

from install.update import UpdateError, _safe_extract


def add_file(bundle, name, data=b"x"):
    info = tarfile.TarInfo(name); info.size = len(data); bundle.addfile(info, io.BytesIO(data))


def test_safe_extract_accepts_application_tree(tmp_path):
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        add_file(bundle, "release/firmware/main.py")
        add_file(bundle, "release/webui/app.py")
        add_file(bundle, "release/requirements.txt")
    root = _safe_extract(archive, tmp_path / "out")
    assert root.name == "release"


def test_safe_extract_rejects_traversal(tmp_path):
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle: add_file(bundle, "../escape")
    with pytest.raises(UpdateError): _safe_extract(archive, tmp_path / "out")
