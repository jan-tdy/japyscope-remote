from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_installer_accepts_trixie_and_reuses_bookworms_networkmanager_path():
    installer = read("install/install.sh")
    assert "bullseye|bookworm|trixie" in installer
    # Trixie has no dedicated apt-install branch: it falls into the same
    # `else` (NetworkManager) branch bookworm uses, same as bookworm falls
    # in alongside any future non-bullseye release.
    assert "if [[ ${VERSION_CODENAME:-} == bullseye ]]; then" in installer


def test_install_factory_accepts_trixie():
    installer = read("install/install-factory.sh")
    assert "bullseye|bookworm|trixie" in installer


def test_trixie_ci_smoke_test_builds_the_hash_locked_pip_and_pyindi_stack():
    workflow = read(".github/workflows/test-trixie-armhf.yml")
    assert "raspios-trixie-armhf-lite.img.xz" in workflow
    assert "network-manager" in workflow
    assert "pip install --require-hashes -r requirements.lock" in workflow
    assert "pip install --require-hashes --no-deps --no-build-isolation -r requirements-pyindi.lock" in workflow
    assert "import PyIndi" in workflow
