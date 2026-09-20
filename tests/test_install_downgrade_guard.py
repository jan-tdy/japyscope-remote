import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_installer_parses_force_flag():
    installer = read("install/install.sh")
    assert "force=0" in installer
    assert "--force) force=1 ;;" in installer


def test_installer_refuses_to_silently_switch_current_to_a_different_version():
    # install.sh and the OTA updater (install/update.py) both flip the same
    # /opt/japyscope/current symlink. Re-running install.sh from a stale
    # checkout (no `git pull` since an OTA update advanced current) must not
    # silently relink current back to the old version it resolves to.
    installer = read("install/install.sh")
    assert "-L /opt/japyscope/current" in installer
    assert 'active_version=$(basename "$(readlink -f /opt/japyscope/current)")' in installer
    assert 'active_version != "$version"' in installer
    assert "Refusing to switch /opt/japyscope/current" in installer
    assert "exit 1" in installer.split("Refusing to switch")[1][:600]


def test_downgrade_guard_is_skipped_for_fresh_installs_and_factory_chroot():
    installer = read("install/install.sh")
    # A fresh install (no current symlink yet) and install-factory.sh's
    # chroot runs (JAPYSCOPE_VERSION_OVERRIDE set, no live current of its
    # own) must not be blocked by the guard.
    assert "$force -eq 0 && -z ${JAPYSCOPE_VERSION_OVERRIDE:-} && -L /opt/japyscope/current" in installer


def test_downgrade_guard_logic_blocks_mismatch_and_force_overrides():
    # Exercise the actual guard logic in isolation (no apt/systemd/root
    # needed) by extracting just the guard block and running it in a bash
    # sandbox with a fake /opt/japyscope/current.
    installer = read("install/install.sh")
    start = installer.index("if [[ $force -eq 0 && -z ${JAPYSCOPE_VERSION_OVERRIDE:-}")
    end = installer.index("\nfi\n", start) + len("\nfi")
    guard = installer[start:end]

    def run_guard(tmp_path, version, force, active_dir_name):
        current = tmp_path / "current"
        release = tmp_path / "releases" / active_dir_name
        release.mkdir(parents=True)
        current.symlink_to(release)
        script = f"""
set -euo pipefail
force={1 if force else 0}
version={version!r}
{guard.replace("/opt/japyscope/current", str(current))}
echo NOT-BLOCKED
"""
        return subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    def make(tmp_path):
        d = tmp_path
        d.mkdir(exist_ok=True)
        return d

    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        result = run_guard(make(tmp / "mismatch"), version="v0.6.0-12-ge439ae6", force=False, active_dir_name="v0.7.0")
        assert result.returncode == 1, result.stderr
        assert "Refusing to switch" in result.stderr
        assert "NOT-BLOCKED" not in result.stdout

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        result = run_guard(make(tmp / "forced"), version="v0.6.0-12-ge439ae6", force=True, active_dir_name="v0.7.0")
        assert result.returncode == 0, result.stderr
        assert "NOT-BLOCKED" in result.stdout

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        result = run_guard(make(tmp / "same"), version="v0.7.0", force=False, active_dir_name="v0.7.0")
        assert result.returncode == 0, result.stderr
        assert "NOT-BLOCKED" in result.stdout
