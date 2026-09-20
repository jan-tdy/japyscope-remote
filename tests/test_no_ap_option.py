import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_installer_parses_no_ap_flag():
    installer = read("install/install.sh")
    assert "no_ap=0" in installer
    assert "--no-ap) no_ap=1 ;;" in installer


def test_no_ap_only_withholds_the_automatic_boot_time_fallback():
    installer = read("install/install.sh")
    # hostapd/dnsmasq, the AP script, its password file, and the sudoers
    # grant are all installed unconditionally — --no-ap must not touch
    # them, since the manual "Restart Wi-Fi setup" path (Web UI System
    # page, eventual Dev Tools code 5000) has to keep working either way.
    assert "apt_retry apt-get install -y --no-install-recommends hostapd dnsmasq wpasupplicant" in installer
    assert "if [[ $no_ap -eq 1 ]]" not in installer
    assert 'install -o root -g root -m 755 "$source_dir/install/wifi-ap.sh" /usr/local/sbin/japyscope-wifi-ap' in installer
    assert "japyscope-wifi-ap --force" in installer
    # The only thing --no-ap gates is enabling/starting the automatic
    # boot-time watcher unit itself.
    assert 'enable_units=(japyscope-splash.service japyscope-app.service japyscope-webui.service japyscope-update.timer)' in installer
    assert 'enable_units=(japyscope-wifi-ap.service "${enable_units[@]}")' in installer
    assert 'if [[ $no_ap -eq 0 ]]; then systemctl restart japyscope-wifi-ap.service; fi' in installer


def test_no_ap_actively_disables_a_previously_enabled_ap_unit():
    # `systemctl enable` is additive-only: on a device re-installed with
    # --no-ap after an earlier install.sh run (or an earlier JapyScope
    # version) had already enabled japyscope-wifi-ap.service, merely
    # leaving it out of enable_units would NOT turn it off — it would stay
    # enabled and still come up on the next boot. --no-ap must actively
    # disable (and stop, if currently up) the unit to keep its documented
    # promise regardless of install history.
    installer = read("install/install.sh")
    assert "systemctl disable japyscope-wifi-ap.service" in installer
    assert "systemctl stop japyscope-wifi-ap.service" in installer


def test_no_ap_enable_units_logic_actually_disables_and_stops_the_unit():
    # Exercise the real enable/disable branch in a bash sandbox (stubbed
    # `systemctl` and `systemd_is_live` that just log their calls) instead
    # of only asserting on source text, so a refactor that keeps the
    # strings but breaks the branching would still be caught.
    installer = read("install/install.sh")
    start = installer.index(
        'enable_units=(japyscope-splash.service japyscope-app.service japyscope-webui.service japyscope-update.timer)'
    )
    end = installer.index('systemctl enable "${enable_units[@]}"', start) + len(
        'systemctl enable "${enable_units[@]}"'
    )
    snippet = installer[start:end]

    def run(no_ap: int) -> str:
        script = f"""
set -euo pipefail
log=$(mktemp)
systemctl() {{ echo "systemctl $*" >> "$log"; }}
systemd_is_live() {{ true; }}
no_ap={no_ap}
{snippet}
cat "$log"
"""
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout

    with_ap = run(no_ap=0)
    assert "systemctl disable japyscope-wifi-ap.service" not in with_ap
    assert "systemctl stop japyscope-wifi-ap.service" not in with_ap
    assert "systemctl enable" in with_ap
    assert "japyscope-wifi-ap.service" in with_ap

    without_ap = run(no_ap=1)
    assert "systemctl disable japyscope-wifi-ap.service" in without_ap
    assert "systemctl stop japyscope-wifi-ap.service" in without_ap


def test_install_factory_forwards_no_ap_to_the_chrooted_installer():
    installer = read("install/install-factory.sh")
    assert "--no-ap) no_ap=1 ;;" in installer
    assert "install_args+=(--no-ap)" in installer
    assert './install/install.sh' in installer
    assert '-- "${install_args[@]}"' in installer
