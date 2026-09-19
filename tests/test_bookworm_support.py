from pathlib import Path


ROOT = Path(__file__).parents[1]


def read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_installer_accepts_bookworm_and_selects_its_native_dependencies():
    installer = read("install/install.sh")
    assert "bullseye|bookworm" in installer
    assert "network-manager" in installer
    assert "network-manager libindi-dev" not in installer
    assert "network_backend=networkmanager" in installer
    assert "JAPYSCOPE_NETWORK_BACKEND=%s" in installer


def test_bookworm_uses_the_pinned_indi_2_client_core_not_its_incompatible_dev_package():
    installer = read("install/install.sh")
    assert "pyindi-client 2.2.0 requires INDI Core 2.x" in installer
    assert "apt_retry apt-get purge -y libindi-dev" in installer
    assert "source \"$source_dir/install/libindi-core.env\"" in installer
    assert "Fetching prebuilt INDI core" in installer


def test_bookworm_ci_smoke_test_builds_the_hash_locked_pip_and_pyindi_stack():
    workflow = read(".github/workflows/test-bookworm-armhf.yml")
    # Not the "raspios_lite:2023-12-11" alias: arm-runner-action's alias
    # whitelist has no Bookworm entry (it stops at 2023-05-03, Bullseye),
    # so that alias silently failed with "Unknown image" before ever
    # booting anything. Assert the real image URL is used instead.
    assert "2023-12-11-raspios-bookworm-armhf-lite.img.xz" in workflow
    assert "base_image: raspios_lite:2023-12-11" not in workflow
    assert "network-manager" in workflow
    assert "pip install --require-hashes -r requirements.lock" in workflow
    assert "pip install --require-hashes --no-deps --no-build-isolation -r requirements-pyindi.lock" in workflow
    assert "import PyIndi" in workflow


def test_bookworm_uses_networkmanager_profiles_for_client_and_setup_ap():
    client = read("install/wifi-config.sh")
    hotspot = read("install/wifi-ap.sh")
    installer = read("install/install.sh")
    assert "nmcli connection add type wifi" in client
    assert "JapyScope client" in client
    assert "nmcli connection up id 'JapyScope client' ifname wlan0" in client
    assert "wifi.mode ap" in installer
    assert "ipv4.method shared" in installer
    assert "nmcli connection up id 'JapyScope Setup' ifname wlan0" in hotspot
    assert "--stop" in hotspot


def test_bullseye_legacy_wifi_path_remains_available():
    installer = read("install/install.sh")
    client = read("install/wifi-config.sh")
    hotspot = read("install/wifi-ap.sh")
    assert "hostapd dnsmasq wpasupplicant" in installer
    assert "network_backend=wpa_supplicant" in installer
    assert "wpa_passphrase" in client
    assert "wpa_cli -i wlan0 reconfigure" in client
    assert "systemctl start dnsmasq.service hostapd.service" in hotspot
