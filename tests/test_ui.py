import os
import tempfile

import requests

from firmware.hal.backlight.base import BacklightHAL
from firmware.hal.display.base import DisplayHAL
from firmware.hal.input.base import InputHAL
from firmware.hal.input.keys import ENC_DOWN, ENC_PUSH, ENC_UP, FN2, JOY_LEFT, JOY_RIGHT
from firmware.ui import ControllerUI, SearchResult, SmartSearch
from firmware.ui import controller as controller_module
from shared.db import CatalogRepo, SettingsRepo, StateRepo, connect, init_db


class Display(DisplayHAL):
    def __init__(self):
        super().__init__(); self.lines = []; self.invert_row = None
    def draw_lines(self, lines, invert_row=None): self.lines = lines; self.invert_row = invert_row


class Backlight(BacklightHAL):
    def __init__(self):
        self.value = None
    def set(self, r, g, b): self.value = (r, g, b)


class Input(InputHAL):
    def poll(self, timeout=0.1): return None


class Indi:
    def __init__(self): self.synced = None; self.goto_target = None; self.parked = False; self.jogs = []
    def sync(self, ra, dec): self.synced = (ra, dec)
    def goto(self, ra, dec): self.goto_target = (ra, dec)
    def park(self): self.parked = True
    def jog(self, direction, speed): self.jogs.append((direction, speed))


def make_ui():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = connect(path); init_db(conn)
    ui = ControllerUI(Display(), Input(), Indi(), conn, backlight=Backlight())
    return ui, conn, path


def enter_devtools_code(ui, code):
    ui.state.screen = "IDLE"; ui.state.index = 2  # Home -> Dev Tools
    ui.handle(ENC_PUSH)
    assert ui.state.screen == "DEVTOOLS"
    for digit in code:
        for _ in range(int(digit)):
            ui.handle(ENC_UP)
        ui.handle(ENC_PUSH)


def test_boot_not_parked_syncs_before_idle():
    ui, conn, path = make_ui()
    try:
        StateRepo(conn).set("ra", "12:00:00"); StateRepo(conn).set("dec", "+20:00:00")
        ui.start(); assert ui.state.screen == "BOOT_PARK_CHECK"
        ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
        assert ui.indi.synced == ("12:00:00", "+20:00:00")
        assert StateRepo(conn).get("parked") == "false"
    finally: conn.close(); os.unlink(path)


def test_boot_sync_failure_does_not_continue():
    ui, conn, path = make_ui()
    try:
        def fail(*_args): raise ConnectionError("not connected")
        ui.indi.sync = fail
        ui.start(); ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)
        assert ui.state.screen == "BOOT_SYNC_FAILED"
        assert StateRepo(conn).get("parked") is None
    finally: conn.close(); os.unlink(path)


def test_language_selection_persists_and_translates():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "MENU"; ui.state.index = 6; ui.handle(ENC_PUSH)
        assert ui.state.screen == "LANGUAGE" and ui.state.index == 0  # default "en"
        ui.handle(ENC_DOWN)  # -> Slovenčina
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "MENU" and ui.state.index == 6
        assert SettingsRepo(conn).get("language") == "sk"
        ui._set("IDLE")
        assert any("Katalóg" in line for line in ui.display.lines)
    finally: conn.close(); os.unlink(path)


def test_language_screen_preselects_current_choice():
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("language", "sk")
        ui.state.screen = "MENU"; ui.state.index = 6; ui.handle(ENC_PUSH)
        assert ui.state.screen == "LANGUAGE" and ui.state.index == 1
        ui.handle("9")
        assert ui.state.screen == "MENU" and ui.state.index == 6
    finally: conn.close(); os.unlink(path)


def test_backlight_menu_calls_injected_backlight_hal():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "MENU"; ui.state.index = 5; ui.handle(ENC_PUSH)
        assert ui.state.screen == "BACKLIGHT"
        assert ui.state.backlight == [1, 0, 0]  # default: R=Med, G=Off, B=Off
        ui.handle(ENC_PUSH)  # cycle channel 0 (R): Med -> High
        assert ui.backlight.value == tuple(ui.state.backlight) == (2, 0, 0)
    finally: conn.close(); os.unlink(path)


def test_system_menu_still_reachable_after_language_entry_added():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "MENU"; ui.state.index = 9; ui.handle(ENC_PUSH)
        assert ui.state.screen == "SYSTEM_CONFIRM"
        ui.handle("9")
        assert ui.state.screen == "MENU" and ui.state.index == 9
    finally: conn.close(); os.unlink(path)


def test_theme_selection_persists_and_defaults_to_arrow():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "MENU"; ui.state.index = 7; ui.handle(ENC_PUSH)
        assert ui.state.screen == "THEME" and ui.state.index == 0  # default "arrow"
        ui.handle(ENC_DOWN)  # -> invert
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "MENU" and ui.state.index == 7
        assert SettingsRepo(conn).get("ui_theme") == "invert"
    finally: conn.close(); os.unlink(path)


def test_theme_screen_preselects_current_choice():
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("ui_theme", "brackets")
        ui.state.screen = "MENU"; ui.state.index = 7; ui.handle(ENC_PUSH)
        assert ui.state.screen == "THEME" and ui.state.index == 2
        ui.handle("9")
        assert ui.state.screen == "MENU" and ui.state.index == 7
    finally: conn.close(); os.unlink(path)


def test_arrow_theme_marks_selected_row_with_prefix_not_invert():
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        assert ui.display.invert_row is None
        assert ui.display.lines[1].startswith("> ")
    finally: conn.close(); os.unlink(path)


def test_invert_theme_flags_selected_row_without_text_marker():
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("ui_theme", "invert")
        ui._set("MENU", 2)
        # visible_rows=4 for the default profile, so only 2 menu rows are
        # shown at a time (title + 2 rows + footer) and the window scrolls
        # to keep the selected item (index 2) as the first visible row.
        assert ui.display.invert_row == 1
        assert ui.display.lines[1] == ui._t("menu.park_toggle")
    finally: conn.close(); os.unlink(path)


def test_brackets_theme_wraps_selected_row_without_invert():
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("ui_theme", "brackets")
        ui._set("MENU", 0)
        assert ui.display.invert_row is None
        assert ui.display.lines[1] == f"[{ui._t('menu.time_sync')}]"
    finally: conn.close(); os.unlink(path)


def test_smartsearch_nine_types_and_fn2_cancels():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TYPE"; ui.handle("9")
        assert ui.state.text == "w"
        ui.handle("9"); assert ui.state.text == "x"
        ui.handle(FN2); assert ui.state.screen == "CATALOG_MENU"
    finally: conn.close(); os.unlink(path)


def test_custom_catalog_navigation_has_two_levels():
    ui, conn, path = make_ui()
    try:
        repo = CatalogRepo(conn); catalog_id = repo.create_catalog("Variables")
        repo.add_item(catalog_id, "V445 Her", "18:24:11", "+12:09")
        ui.state.screen = "CATALOG_MENU"; ui.state.index = 1; ui.handle(ENC_PUSH)
        assert ui.state.screen == "CUSTOM_CATALOGS"
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "LIST" and ui.state.list_items[0].name == "V445 Her"
    finally: conn.close(); os.unlink(path)


def test_smartsearch_network_failure_returns_local_results():
    class Offline:
        def get(self, *args, **kwargs): raise requests.ConnectionError("offline")
    results, online = SmartSearch(session=Offline()).search("vega", [SearchResult("Vega")])
    assert [result.name for result in results] == ["Vega"]
    assert online is False


def test_smartsearch_rejects_xml_entities():
    class Response:
        text = '<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><Sesame><Resolver><oname>&xxe;</oname></Resolver></Sesame>'
        def raise_for_status(self): pass
    class Session:
        def get(self, *args, **kwargs): return Response()
    results, online = SmartSearch(session=Session()).search("vega", [SearchResult("Vega")])
    assert [result.name for result in results] == ["Vega"]
    assert online is False


def test_slew_without_coordinates_shows_error():
    ui, conn, path = make_ui()
    try:
        StateRepo(conn).set("aligned", "true")
        ui._confirm_slew(SearchResult("Moon"), "LIST")
        assert ui.state.screen == "ERROR"
        assert ui.state.transition_at == 0
        assert ui.indi.goto_target is None
    finally: conn.close(); os.unlink(path)


def test_devtools_0022_sets_repo():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "0022")
        assert ui.state.screen == "DEV_REPO_SELECT"
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
        assert SettingsRepo(conn).get("update_repo") == "jan-tdy/japyscope-remote"
    finally: conn.close(); os.unlink(path)


def test_devtools_0033_sets_update_channel():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "0033")
        assert ui.state.screen == "DEV_CHANNEL_SELECT" and ui.state.index == 0  # default "stable"
        ui.handle(ENC_DOWN)  # -> "Stable + prereleases"
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
        assert SettingsRepo(conn).get("update_channel") == "prerelease"
    finally: conn.close(); os.unlink(path)


def test_devtools_0033_preselects_current_channel():
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("update_channel", "prerelease")
        enter_devtools_code(ui, "0033")
        assert ui.state.screen == "DEV_CHANNEL_SELECT" and ui.state.index == 1
    finally: conn.close(); os.unlink(path)


def test_devtools_0044_enables_ssh_and_shows_status(monkeypatch):
    ui, conn, path = make_ui()
    try:
        calls = []
        monkeypatch.setattr(controller_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        monkeypatch.setattr(ControllerUI, "_local_ip", staticmethod(lambda: "10.0.0.5"))
        enter_devtools_code(ui, "0044")
        assert calls == [["systemctl", "enable", "--now", "ssh"]]
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "SSH enabled"
        assert "10.0.0.5" in ui.state.dev_message[1]
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_0044_reports_failure_without_crashing(monkeypatch):
    ui, conn, path = make_ui()
    try:
        def fail(cmd, **kw): raise OSError("systemctl not found")
        monkeypatch.setattr(controller_module.subprocess, "run", fail)
        monkeypatch.setattr(ControllerUI, "_local_ip", staticmethod(lambda: "10.0.0.5"))
        enter_devtools_code(ui, "0044")
        assert ui.state.dev_message[0] == "Could not enable SSH"
    finally: conn.close(); os.unlink(path)


def test_devtools_9955_lists_and_runs_custom_script(monkeypatch, tmp_path):
    scripts_dir = tmp_path / "custom"; scripts_dir.mkdir()
    (scripts_dir / "b.sh").write_text("#!/bin/sh\necho hi\n")
    (scripts_dir / "a.sh").write_text("#!/bin/sh\necho hi\n")
    (scripts_dir / "notes.txt").write_text("ignore me")
    monkeypatch.setenv("JAPYSCOPE_CUSTOM_SCRIPTS_DIR", str(scripts_dir))
    ui, conn, path = make_ui()
    try:
        calls = []
        monkeypatch.setattr(controller_module.subprocess, "Popen", lambda cmd, **kw: calls.append((cmd, kw)))
        enter_devtools_code(ui, "9955")
        assert ui.state.screen == "DEV_SCRIPT_SELECT"
        assert ui.state.dev_scripts == ["a.sh", "b.sh"]  # sorted, .sh only
        ui.handle(ENC_PUSH)  # run "a.sh" (index 0)
        assert calls[0][0] == ["/bin/sh", str(scripts_dir / "a.sh")]
        assert ui.state.screen == "DEV_MESSAGE"
        assert "Running a.sh" in ui.state.dev_message[0]
    finally: conn.close(); os.unlink(path)


def test_devtools_9955_no_scripts_found(monkeypatch, tmp_path):
    monkeypatch.setenv("JAPYSCOPE_CUSTOM_SCRIPTS_DIR", str(tmp_path / "missing"))
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "9955")
        assert ui.state.screen == "DEV_SCRIPT_SELECT"
        assert ui.state.dev_scripts == []
        ui.handle(ENC_PUSH)  # nothing to run, screen unchanged
        assert ui.state.screen == "DEV_SCRIPT_SELECT"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_1001_is_coming_soon():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "1001")
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "More INDI drivers"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_invalid_code_shows_message():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "6666")
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message == ["Invalid code."]
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_1111_restarts_indi_via_manager():
    ui, conn, path = make_ui()
    try:
        calls = []
        class Manager:
            def restart(self): calls.append("restart")
        ui.indi_manager = Manager()
        enter_devtools_code(ui, "1111")
        assert calls == ["restart"]
        assert ui.state.dev_message == ["INDI server restarted"]
    finally: conn.close(); os.unlink(path)


def test_devtools_1111_without_manager_shows_unavailable():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "1111")  # ui.indi_manager is None (default)
        assert ui.state.screen == "DEV_MESSAGE"
        assert "unavailable" in ui.state.dev_message[0]
    finally: conn.close(); os.unlink(path)


def test_devtools_1111_restart_failure_is_reported(monkeypatch):
    ui, conn, path = make_ui()
    try:
        class Manager:
            def restart(self): raise OSError("indiserver binary not found")
        ui.indi_manager = Manager()
        enter_devtools_code(ui, "1111")
        assert ui.state.dev_message[0] == "INDI restart failed"
    finally: conn.close(); os.unlink(path)


def test_devtools_1234_shows_real_system_info(monkeypatch):
    ui, conn, path = make_ui()
    try:
        monkeypatch.setattr(ControllerUI, "_local_ip", staticmethod(lambda: "10.0.0.5"))
        monkeypatch.setattr(ControllerUI, "_uptime", staticmethod(lambda: "2h14m"))
        StateRepo(conn).set("indi_connected", "true")
        enter_devtools_code(ui, "1234")
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "System Info"
        assert "10.0.0.5" in ui.state.dev_message[1]
        assert "2h14m" in ui.state.dev_message[2] and "INDI up" in ui.state.dev_message[2]
    finally: conn.close(); os.unlink(path)


def test_devtools_5000_opens_wifi_setup_and_back_returns_idle():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "5000")
        assert ui.state.screen == "WIFI_SETUP"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_5555_opens_driver_select_and_back_returns_idle():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "5555")
        assert ui.state.screen == "DRIVER_SELECT"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_opens_iface_select_and_back_returns_idle():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "9600")
        assert ui.state.screen == "IFACE_SELECT"
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_devtools_easter_eggs_show_and_dismiss():
    ui, conn, path = make_ui()
    try:
        for code, first_line in (
            ("9999", "Why did the astronomer"),
            ("4200", "42."),
            ("1957", "1957 — Sputnik beeped."),
            ("0905", "Protocol 09:"),
        ):
            enter_devtools_code(ui, code)
            assert ui.state.screen == "DEV_MESSAGE"
            assert ui.state.dev_message[0] == first_line
            ui.handle("9")
            assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_align_jog_screen_jogs_with_keypad_encoder_and_joystick():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "ALIGN_JOG"; ui.state.jog_target = "Vega"; ui.state.align_points = 0
        ui.handle("2"); assert ui.indi.jogs[-1] == ("N", 1)
        ui.handle("8"); assert ui.indi.jogs[-1] == ("S", 1)
        ui.handle("4"); assert ui.indi.jogs[-1] == ("W", 1)
        ui.handle("6"); assert ui.indi.jogs[-1] == ("E", 1)
        ui.handle(ENC_UP); assert ui.indi.jogs[-1] == ("N", 1)  # joystick Y-axis
        ui.handle(ENC_DOWN); assert ui.indi.jogs[-1] == ("S", 1)
        ui.handle(JOY_LEFT); assert ui.indi.jogs[-1] == ("W", 1)  # joystick X-axis
        ui.handle(JOY_RIGHT); assert ui.indi.jogs[-1] == ("E", 1)
        assert ui.state.screen == "ALIGN_JOG"  # jogging doesn't change screen
        assert len(ui.indi.jogs) == 8

        ui.handle(ENC_PUSH)
        assert ui.state.screen == "ALIGN_STAR_PICK" and ui.state.align_points == 1
    finally: conn.close(); os.unlink(path)


def test_align_jog_survives_indi_not_implemented():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "ALIGN_JOG"
        def fail(direction, speed): raise NotImplementedError("no hardware yet")
        ui.indi.jog = fail
        ui.handle(ENC_UP)  # must not raise, and must not leave the jog screen
        assert ui.state.screen == "ALIGN_JOG"
        ui.handle("9")
        assert ui.state.screen == "ALIGN_CHOOSE"
    finally: conn.close(); os.unlink(path)


def test_track_screen_jogs_and_keeps_its_own_keys_working():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"
        ui.handle(JOY_LEFT)
        assert ui.indi.jogs[-1] == ("W", 1)
        ui.handle("7")
        assert ui.state.screen == "SPEED_ADJUST" and ui.state.return_screen == "TRACK"
        ui.state.screen = "TRACK"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_jog_uses_the_current_speed():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"; ui.state.speed = 8
        ui.handle("6")
        assert ui.indi.jogs[-1] == ("E", 8)
    finally: conn.close(); os.unlink(path)
