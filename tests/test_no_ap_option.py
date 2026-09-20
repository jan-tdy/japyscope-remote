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
    assert 'if [[ $no_ap -eq 0 ]]; then enable_units=(japyscope-wifi-ap.service "${enable_units[@]}"); fi' in installer
    assert 'if [[ $no_ap -eq 0 ]]; then systemctl restart japyscope-wifi-ap.service; fi' in installer


def test_install_factory_forwards_no_ap_to_the_chrooted_installer():
    installer = read("install/install-factory.sh")
    assert "--no-ap) no_ap=1 ;;" in installer
    assert "install_args+=(--no-ap)" in installer
    assert './install/install.sh' in installer
    assert '-- "${install_args[@]}"' in installer
