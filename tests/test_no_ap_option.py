from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_installer_parses_no_ap_flag():
    installer = read("install/install.sh")
    assert "no_ap=0" in installer
    assert "--no-ap) no_ap=1 ;;" in installer


def test_no_ap_skips_ap_packages_and_setup_artifacts():
    installer = read("install/install.sh")
    # Bullseye still needs wpasupplicant for normal client Wi-Fi even
    # with --no-ap; only hostapd/dnsmasq (AP-only) are conditional.
    assert "apt_retry apt-get install -y --no-install-recommends wpasupplicant" in installer
    assert "apt_retry apt-get install -y --no-install-recommends hostapd dnsmasq wpasupplicant" in installer
    # The AP hotspot script, its password file, and the hostapd/nmcli setup
    # are all skipped together, behind a single `no_ap` gate.
    assert 'install -o root -g root -m 755 "$source_dir/install/wifi-ap.sh" /usr/local/sbin/japyscope-wifi-ap' in installer
    assert "if [[ $no_ap -eq 0 ]]; then" in installer
    # Normal client Wi-Fi config is installed unconditionally.
    assert 'install -o root -g root -m 755 "$source_dir/install/wifi-config.sh" /usr/local/sbin/japyscope-wifi' in installer


def test_no_ap_keeps_sudoers_and_systemd_valid_without_the_ap_helper():
    installer = read("install/install.sh")
    assert "sudoers_cmds=" in installer
    assert "sudoers_cmds+=', /usr/local/sbin/japyscope-wifi-ap --force'" in installer
    assert 'enable_units=(japyscope-splash.service japyscope-app.service japyscope-webui.service japyscope-update.timer)' in installer
    assert 'enable_units=(japyscope-wifi-ap.service "${enable_units[@]}")' in installer
    assert 'systemctl enable "${enable_units[@]}"' in installer


def test_install_factory_forwards_no_ap_to_the_chrooted_installer():
    installer = read("install/install-factory.sh")
    assert "--no-ap) no_ap=1 ;;" in installer
    assert "install_args+=(--no-ap)" in installer
    assert './install/install.sh' in installer
    assert '-- "${install_args[@]}"' in installer
