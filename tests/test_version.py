from shared.version import current_version


def test_current_version_none_without_a_current_symlink(tmp_path):
    assert current_version(tmp_path) is None


def test_current_version_none_if_current_exists_but_is_a_plain_directory(tmp_path):
    (tmp_path / "current").mkdir()
    assert current_version(tmp_path) is None


def test_current_version_is_the_release_tag_current_resolves_to(tmp_path):
    release_dir = tmp_path / "releases" / "v1.2.3"
    release_dir.mkdir(parents=True)
    (tmp_path / "current").symlink_to(release_dir)
    assert current_version(tmp_path) == "v1.2.3"
