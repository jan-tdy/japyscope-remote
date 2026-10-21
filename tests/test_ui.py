import os
import sqlite3
import subprocess
import tempfile

import requests

from firmware.hal.backlight.base import BacklightHAL
from firmware.hal.display.base import DisplayHAL
from firmware.hal.input.base import InputHAL, key_up
from firmware.hal.input.keys import ENC_DOWN, ENC_PUSH, ENC_UP, FN2, JOY_LEFT, JOY_RIGHT
from firmware.indi.client import MountStatus
from firmware.ui import ControllerUI, SearchResult, SmartSearch
from firmware.ui import controller as controller_module
from shared.db import CatalogRepo, SettingsRepo, StateRepo, connect, init_db


class Display(DisplayHAL):
    def __init__(self):
        super().__init__(); self.lines = []; self.invert_row = None; self.partial = None; self.scroll = None
    def draw_lines(self, lines, invert_row=None, partial=False, scroll=None):
        self.lines = lines; self.invert_row = invert_row; self.partial = partial; self.scroll = scroll


class Backlight(BacklightHAL):
    def __init__(self):
        self.value = None
    def set(self, r, g, b): self.value = (r, g, b)


class Input(InputHAL):
    def poll(self, timeout=0.1): return None


class Indi:
    def __init__(self):
        self.synced = None; self.goto_target = None; self.parked = False
        self.tracking = False; self.aborted = False; self.jogs = []; self.jog_stops = []
    def sync(self, ra, dec): self.synced = (ra, dec)
    def goto(self, ra, dec): self.goto_target = (ra, dec); self.tracking = True
    def park(self): self.parked = True
    def unpark(self): self.parked = False
    def abort(self): self.aborted = True; self.tracking = False
    def jog(self, direction, speed): self.jogs.append((direction, speed))
    def stop_jog(self, direction): self.jog_stops.append(direction)
    def get_status(self):
        return MountStatus(
            connected=True, ra="", dec="", alt=0.0, az=0.0,
            tracking=self.tracking, aligned=False, parked=self.parked,
        )


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


def test_boot_not_parked_walks_a_real_star_sync_before_idle():
    ui, conn, path = make_ui()
    try:
        ui.start(); assert ui.state.screen == "BOOT_PARK_CHECK"
        ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)  # "No — sync now"
        assert ui.state.screen == "ALIGN_STAR_PICK" and ui.state.boot_sync is True
        star = controller_module.STARS[0]
        ui.handle(ENC_PUSH)  # pick the first star
        assert ui.state.screen == "ALIGN_JOG" and ui.state.align_star is star
        ui.handle(ENC_PUSH)  # confirm it's centered
        assert ui.state.screen == "IDLE"
        assert ui.indi.synced == (star.ra, star.dec)
        assert StateRepo(conn).get("parked") == "false"
        assert StateRepo(conn).get("aligned") == "true"
        assert ui.state.boot_sync is False
    finally: conn.close(); os.unlink(path)


def test_boot_sync_failure_does_not_continue():
    ui, conn, path = make_ui()
    try:
        def fail(*_args): raise ConnectionError("not connected")
        ui.indi.sync = fail
        ui.start(); ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)  # "No — sync now"
        ui.handle(ENC_PUSH)  # pick a star
        ui.handle(ENC_PUSH)  # confirm it's centered -> sync fails
        assert ui.state.screen == "BOOT_SYNC_FAILED"
        assert StateRepo(conn).get("parked") is None
        assert StateRepo(conn).get("aligned") is None
    finally: conn.close(); os.unlink(path)


def test_boot_sync_failure_retry_returns_to_star_pick():
    ui, conn, path = make_ui()
    try:
        def fail(*_args): raise ConnectionError("not connected")
        ui.indi.sync = fail
        ui.start(); ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)
        ui.handle(ENC_PUSH); ui.handle(ENC_PUSH)
        assert ui.state.screen == "BOOT_SYNC_FAILED"
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "ALIGN_STAR_PICK" and ui.state.boot_sync is True
        ui.handle("9")
        assert ui.state.screen == "BOOT_PARK_CHECK" and ui.state.boot_sync is False
    finally: conn.close(); os.unlink(path)


def test_menu_nags_about_default_sudo_password_until_changed():
    # Regression test for jan-tdy/japyscope-remote#35: a fresh install
    # must not silently keep the old well-known "1234" default — the Menu
    # entry itself flags it on every visit instead.
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 8)  # Sudo Password's slot in ControllerUI.MENU
        assert any("(default!)" in line for line in ui.display.lines)
    finally: conn.close(); os.unlink(path)


def test_setting_sudo_password_clears_default_reminder():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "MENU"; ui.state.index = 8  # Menu -> Sudo Password
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "SUDO_SET"
        for digit in "5678":
            for _ in range(int(digit)):
                ui.handle(ENC_UP)
            ui.handle(ENC_PUSH)
        assert ui.state.screen == "MENU"
        settings = SettingsRepo(conn)
        assert settings.get("sudo_password_is_default") == "0"
        assert settings.verify_password("sudo_password", "5678") is True
        assert StateRepo(conn).get("sudo_password_first_boot") is None
        ui._set("MENU", 8)
        assert not any("(default!)" in line for line in ui.display.lines)
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


def test_shutdown_actually_calls_power_control():
    # Confirmed on hardware as a real gap: confirming shutdown only
    # stopped the app loop and never powered anything off, even though
    # install.sh already grants passwordless sudo for exactly this.
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = connect(path); init_db(conn)
    calls = []
    ui = ControllerUI(
        Display(), Input(), Indi(), conn, backlight=Backlight(),
        power_control=lambda: calls.append(True),
    )
    try:
        ui.state.screen = "SYSTEM_CONFIRM"
        ui.handle(ENC_PUSH)
        assert calls == [True]
        assert ui.running is False
        assert ui.state.screen == "SHUTDOWN"
    finally: conn.close(); os.unlink(path)


def test_shutdown_without_power_control_still_stops_cleanly():
    # --simulate / tests: power_control defaults to None, so this must
    # not raise — just stop the loop as before.
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "SYSTEM_CONFIRM"
        ui.handle(ENC_PUSH)
        assert ui.running is False
        assert ui.state.screen == "SHUTDOWN"
    finally: conn.close(); os.unlink(path)


def test_shutdown_from_parked_screen_also_calls_power_control():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = connect(path); init_db(conn)
    calls = []
    ui = ControllerUI(
        Display(), Input(), Indi(), conn, backlight=Backlight(),
        power_control=lambda: calls.append(True),
    )
    try:
        ui.state.screen = "PARKED"; ui.state.index = 1  # "Power off"
        ui.handle(ENC_PUSH)
        assert calls == [True]
        assert ui.running is False
        assert ui.state.screen == "SHUTDOWN"
    finally: conn.close(); os.unlink(path)


def test_park_waits_for_driver_confirmation_before_showing_parked():
    # park() only issues the command -- a real driver parks
    # asynchronously, so PARKING must not claim success until
    # get_status().parked actually comes back true (polled via
    # _refresh_status(), not a blind fixed timer).
    ui, conn, path = make_ui()
    try:
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.state.last_status_at = now[0]
        ui.state.screen = "PARK_CONFIRM"; ui.state.index = 0
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "PARKING"
        assert ui.indi.parked is True  # command issued

        # Time passes, but no status poll has happened yet (<2s) --
        # still PARKING, not optimistically PARKED.
        now[0] += 1.0
        ui.tick()
        assert ui.state.screen == "PARKING"

        # A status poll (>=2s since last) picks up indi.parked == True
        # and only then transitions.
        now[0] += 2.0
        ui.tick()
        assert ui.state.screen == "PARKED"
        assert StateRepo(conn).get("parked") == "true"
    finally: conn.close(); os.unlink(path)


def test_park_confirmation_timeout_does_not_silently_claim_parked(monkeypatch):
    ui, conn, path = make_ui()
    try:
        now = [1000.0]
        ui.clock = lambda: now[0]
        # get_status() never reports parked (e.g. a flaky real driver).
        monkeypatch.setattr(ui.indi, "get_status", lambda: None)
        ui.state.screen = "PARK_CONFIRM"; ui.state.index = 0
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "PARKING"

        now[0] += controller_module.PARK_CONFIRM_TIMEOUT_SECONDS + 1
        ui.tick()
        assert ui.state.screen == "DEV_MESSAGE"
        assert "did not confirm" in " ".join(ui.state.dev_message).lower()
        assert StateRepo(conn).get("parked") != "true"
    finally: conn.close(); os.unlink(path)


def test_park_timeout_message_dismisses_to_idle_not_a_stale_return_screen():
    # return_screen can still hold "LIST"/"RESULTS" from an earlier
    # _confirm_slew() call that starting PARKING never touches -- the
    # timeout message must not dismiss back to a screen that lets the
    # owner immediately slew again with the park result still unknown.
    ui, conn, path = make_ui()
    try:
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.state.return_screen = "LIST"  # stale, from an earlier slew
        ui.state.screen = "PARK_CONFIRM"; ui.state.index = 0
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "PARKING"

        ui.indi.get_status = lambda: None  # never confirms parked
        now[0] += controller_module.PARK_CONFIRM_TIMEOUT_SECONDS + 1
        ui.tick()
        assert ui.state.screen == "DEV_MESSAGE"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_slew_timeout_message_dismisses_to_idle_not_a_stale_return_screen():
    ui, conn, path = make_ui()
    try:
        StateRepo(conn).set("aligned", "true")
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.indi.get_status = lambda: None  # never confirms tracking
        ui._confirm_slew(SearchResult("Moon", ra="1h", dec="+1d"), "LIST")
        assert ui.state.screen == "SLEW"
        assert ui.state.return_screen == "LIST"

        now[0] += controller_module.SLEW_CONFIRM_TIMEOUT_SECONDS + 1
        ui.tick()
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.indi.aborted is True
        ui.handle("9")
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_slew_does_not_promote_to_track_on_stale_tracking_flag():
    # runtime["tracking"] is only refreshed by _refresh_status()'s
    # throttled poll -- if the mount was already tracking a PREVIOUS
    # target, that stale "true" must not let _poll_slew() promote a
    # brand-new goto straight to TRACK before any post-goto sample
    # confirms the new slew actually arrived.
    ui, conn, path = make_ui()
    try:
        StateRepo(conn).set("aligned", "true")
        StateRepo(conn).set("tracking", "true")  # stale, from a prior target
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.state.last_status_at = now[0]  # as if just refreshed a moment ago
        ui._confirm_slew(SearchResult("Moon", ra="1h", dec="+1d"), "LIST")
        assert ui.state.screen == "SLEW"

        # Immediately ticking (as run() does right after handle()), well
        # within _refresh_status()'s own 2s throttle, must not promote to
        # TRACK off the stale DB value alone -- _begin_slew() must have
        # cleared it synchronously.
        now[0] += 1.0
        ui.tick()
        assert ui.state.screen == "SLEW"
        assert StateRepo(conn).get("tracking") == "false"
    finally: conn.close(); os.unlink(path)


def test_parked_screen_can_open_devtools_without_unparking():
    # Dev Tools used to only be reachable from IDLE, forcing the owner to
    # unpark (a real mount motion) just to open a settings menu.
    ui, conn, path = make_ui()
    try:
        ui.indi.parked = True
        StateRepo(conn).set("parked", "true")
        ui.state.screen = "PARKED"; ui.state.index = 2  # "Dev Tools"
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEVTOOLS"
        assert ui.indi.parked is True  # not unparked just by opening Dev Tools

        # A code's own cancel ("9") comes back to PARKED, not IDLE --
        # IDLE would wrongly suggest the mount had been unparked.
        for digit in "9999":  # the Easter-egg joke code -> DEV_MESSAGE
            for _ in range(int(digit)):
                ui.handle(ENC_UP)
            ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        ui.handle("9")
        assert ui.state.screen == "PARKED"
        assert ui.indi.parked is True
    finally: conn.close(); os.unlink(path)


def test_unpark_from_parked_screen_calls_indi_unpark():
    ui, conn, path = make_ui()
    try:
        ui.indi.parked = True
        StateRepo(conn).set("parked", "true")
        ui.state.screen = "PARKED"; ui.state.index = 0  # "Unpark"
        ui.handle(ENC_PUSH)
        assert ui.indi.parked is False
        assert ui.state.screen == "IDLE"
        assert StateRepo(conn).get("parked") == "false"
    finally: conn.close(); os.unlink(path)


def test_unpark_failure_keeps_parked_screen(monkeypatch):
    ui, conn, path = make_ui()
    try:
        ui.indi.parked = True
        StateRepo(conn).set("parked", "true")

        def fail():
            raise ConnectionError("driver unreachable")
        monkeypatch.setattr(ui.indi, "unpark", fail)
        ui.state.screen = "PARKED"; ui.state.index = 0
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "PARKED"  # did not leave on failure
        assert StateRepo(conn).get("parked") == "true"
    finally: conn.close(); os.unlink(path)


def test_unpark_from_menu_toggle_calls_indi_unpark():
    ui, conn, path = make_ui()
    try:
        ui.indi.parked = True
        StateRepo(conn).set("parked", "true")
        ui.state.screen = "MENU"; ui.state.index = 2
        ui.handle(ENC_PUSH)
        assert ui.indi.parked is False
        assert ui.state.screen == "IDLE"
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
        # MENU has no footer, so _visible() shows visible_rows - 1 item rows
        # at a time; picking an index past that window exercises the part
        # that scrolls to keep the selected item (index 2) as the first
        # visible row, regardless of exactly how many rows that is.
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


def test_smartsearch_typing_is_a_partial_refresh():
    # Typing changes a value (the search text) while staying on the same
    # TYPE screen — same category as scrolling, so it should coalesce to a
    # fast partial refresh rather than a full one on every keypress.
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TYPE"; ui.handle("9")
        assert ui.display.partial is True
    finally: conn.close(); os.unlink(path)


def test_wifi_access_countdown_tick_is_a_partial_refresh():
    # The per-second countdown changes a value (remaining time) while
    # staying on the same WIFI_ACCESS screen — should coalesce to a
    # partial refresh, not force a full one every second.
    ui, conn, path = make_ui()
    try:
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.state.access_code = "123456"
        ui.state.access_expires = now[0] + 600
        ui._set("WIFI_ACCESS")
        assert ui.display.partial is False  # the screen transition itself is full

        now[0] += 1.0
        ui.tick()
        assert ui.display.partial is True
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


def test_custom_catalog_items_get_a_real_altitude_not_a_placeholder():
    # Custom catalog items (added through the Web UI) used to always show
    # "Alt: --" -- nothing ever computed one for them, unlike the
    # hardcoded demo values on BUILTIN_CATALOGS entries. With a location
    # configured, opening the catalog should now compute a real altitude
    # from the item's own RA/Dec.
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("latitude", "48.15")
        SettingsRepo(conn).set("longitude", "17.11")
        ui.clock = lambda: 1_700_000_000.0
        repo = CatalogRepo(conn); catalog_id = repo.create_catalog("Variables")
        repo.add_item(catalog_id, "V445 Her", "18:24:11", "+12:09")
        ui.state.screen = "CATALOG_MENU"; ui.state.index = 1; ui.handle(ENC_PUSH)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "LIST"
        item = ui.state.list_items[0]
        assert item.name == "V445 Her"
        assert item.alt is not None
        assert -90.0 <= item.alt <= 90.0
    finally: conn.close(); os.unlink(path)


def test_custom_catalog_item_with_unparseable_coords_keeps_alt_none():
    ui, conn, path = make_ui()
    try:
        repo = CatalogRepo(conn); catalog_id = repo.create_catalog("Scratch")
        repo.add_item(catalog_id, "No coords yet", "", "")
        ui.state.screen = "CATALOG_MENU"; ui.state.index = 1; ui.handle(ENC_PUSH)
        ui.handle(ENC_PUSH)
        assert ui.state.list_items[0].alt is None
    finally: conn.close(); os.unlink(path)


def test_scheduled_update_does_not_interrupt_active_screen():
    # japyscope-update.timer fires at a random hour, fully independent of
    # whatever's on screen -- it must never yank the owner out of TRACK
    # (or any other non-idle screen) just because a routine background
    # update check happened to start.
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"
        StateRepo(conn).set("update_status", "running")
        StateRepo(conn).set("update_phase", "downloading")
        ui.tick()
        assert ui.state.screen == "TRACK"
    finally: conn.close(); os.unlink(path)


def test_update_in_progress_shows_on_idle_screen_and_tracks_phase():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "IDLE"
        state = StateRepo(conn)
        state.set("update_status", "running"); state.set("update_phase", "checking")
        ui.tick()
        assert ui.state.screen == "UPDATE_STATUS"
        assert ui.display.partial is False  # the screen transition itself is full

        state.set("update_phase", "downloading")
        ui.tick()
        assert ui.state.screen == "UPDATE_STATUS"
        assert ui.display.partial is True  # same screen, just the phase text changed
    finally: conn.close(); os.unlink(path)


def test_hiding_update_status_does_not_immediately_bring_it_back():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "IDLE"
        state = StateRepo(conn)
        state.set("update_status", "running"); state.set("update_phase", "downloading")
        ui.tick()
        assert ui.state.screen == "UPDATE_STATUS"

        ui.handle("9")
        assert ui.state.screen == "IDLE"
        ui.tick()  # update is still "running" -- must not pop right back up
        assert ui.state.screen == "IDLE"
    finally: conn.close(); os.unlink(path)


def test_update_finished_without_restart_returns_to_idle_and_clears_state():
    # The "already up to date" path (and a failure before anything was
    # actually touched) never restarts japyscope-app.service, so this
    # same process has to notice it finished and back out on its own.
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "IDLE"
        state = StateRepo(conn)
        state.set("update_status", "running"); state.set("update_phase", "checking")
        ui.tick()
        assert ui.state.screen == "UPDATE_STATUS"

        state.set("update_status", "idle"); state.set("update_phase", "up_to_date")
        ui.tick()
        assert ui.state.screen == "IDLE"
        assert state.get("update_status") is None
    finally: conn.close(); os.unlink(path)


def test_boot_shows_update_result_then_continues_to_park_check():
    ui, conn, path = make_ui()
    try:
        state = StateRepo(conn)
        state.set("update_status", "success"); state.set("update_tag", "v9.9.9")
        ui.start()
        assert ui.state.screen == "UPDATE_RESULT"
        assert "v9.9.9" in " ".join(ui.state.dev_message)
        assert state.get("update_status") is None  # shown once, then cleared

        ui.handle(ENC_PUSH)
        assert ui.state.screen == "BOOT_PARK_CHECK"
    finally: conn.close(); os.unlink(path)


def test_boot_shows_rolled_back_update_failure():
    ui, conn, path = make_ui()
    try:
        state = StateRepo(conn)
        state.set("update_status", "failed"); state.set("update_phase", "rolled_back")
        state.set("update_error", "OTA-003 update failed and was rolled back")
        ui.start()
        assert ui.state.screen == "UPDATE_RESULT"
        assert "Rolled back" in " ".join(ui.state.dev_message)
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


def test_slew_waits_for_driver_confirmation_before_showing_track():
    # goto() only issues the command -- a real driver slews
    # asynchronously, so SLEW must not claim TRACK until
    # get_status().tracking actually comes back true (polled via
    # _refresh_status(), not a blind fixed timer).
    ui, conn, path = make_ui()
    try:
        StateRepo(conn).set("aligned", "true")
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.state.last_status_at = now[0]
        ui._confirm_slew(SearchResult("Moon", ra="1h", dec="+1d"), "LIST")
        assert ui.state.screen == "SLEW"
        assert ui.indi.goto_target == ("1h", "+1d")  # command issued

        # Time passes, but no status poll has happened yet (<2s) --
        # still SLEW, not optimistically TRACK.
        now[0] += 1.0
        ui.tick()
        assert ui.state.screen == "SLEW"

        # A status poll (>=2s since last) picks up indi.tracking == True
        # and only then transitions.
        now[0] += 2.0
        ui.tick()
        assert ui.state.screen == "TRACK"
    finally: conn.close(); os.unlink(path)


def test_slew_confirmation_timeout_does_not_silently_claim_tracking(monkeypatch):
    ui, conn, path = make_ui()
    try:
        StateRepo(conn).set("aligned", "true")
        now = [1000.0]
        ui.clock = lambda: now[0]
        # get_status() never reports tracking (e.g. a flaky real driver).
        monkeypatch.setattr(ui.indi, "get_status", lambda: None)
        ui._confirm_slew(SearchResult("Moon", ra="1h", dec="+1d"), "LIST")
        assert ui.state.screen == "SLEW"

        now[0] += controller_module.SLEW_CONFIRM_TIMEOUT_SECONDS + 1
        ui.tick()
        assert ui.state.screen == "DEV_MESSAGE"
        assert "did not confirm" in " ".join(ui.state.dev_message).lower()
    finally: conn.close(); os.unlink(path)


def test_abort_on_slew_screen_calls_indi_abort():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "SLEW"
        ui.indi.tracking = True
        ui.handle("7")
        assert ui.indi.aborted is True
        assert ui.state.screen == "SLEW_ABORTED"
    finally: conn.close(); os.unlink(path)


def test_devtools_code_enterable_via_keypad_1_7_5_stand_ins():
    # "1"/"7" (ENC_UP/ENC_DOWN) and "5" (ENC_PUSH) should work for entering
    # a Dev Tools code too, not just the real encoder — DEVTOOLS/SUDO_SET
    # read ENC_UP/ENC_DOWN directly (not via _move()), so they need their
    # own translation in _digits(), separate from _move()'s.
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "IDLE"; ui.state.index = 2  # Home -> Dev Tools
        ui.handle("5")  # ENC_PUSH stand-in
        assert ui.state.screen == "DEVTOOLS"
        for digit in "0022":
            for _ in range(int(digit)):
                ui.handle("1")  # ENC_UP stand-in
            ui.handle("5")  # ENC_PUSH stand-in
        assert ui.state.screen == "DEV_REPO_SELECT"
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


def test_devtools_9956_lists_and_runs_official_script(monkeypatch):
    ui, conn, path = make_ui()
    try:
        calls = []

        def fake_run(cmd, **kw):
            calls.append(("run", cmd))
            assert cmd[-1] == "list"
            return subprocess.CompletedProcess(cmd, 0, stdout="cleanup-old-rollbacks.sh\n")

        def fake_popen(cmd, **kw):
            calls.append(("popen", cmd))

        monkeypatch.setattr(controller_module.subprocess, "run", fake_run)
        monkeypatch.setattr(controller_module.subprocess, "Popen", fake_popen)
        enter_devtools_code(ui, "9956")
        assert ui.state.screen == "DEV_OFFICIAL_SCRIPT_SELECT"
        assert ui.state.dev_scripts == ["cleanup-old-rollbacks.sh"]
        ui.handle(ENC_PUSH)  # run it
        assert calls[0] == ("run", ["sudo", "/usr/local/sbin/japyscope-run-official-script", "list"])
        assert calls[1] == ("popen", ["sudo", "/usr/local/sbin/japyscope-run-official-script", "run", "cleanup-old-rollbacks.sh"])
        assert ui.state.screen == "DEV_MESSAGE"
        assert "cleanup-old-rollbacks.sh" in ui.state.dev_message
    finally: conn.close(); os.unlink(path)


def test_devtools_9956_list_failure_shows_empty_not_a_crash(monkeypatch):
    ui, conn, path = make_ui()
    try:
        def fail(cmd, **kw): raise subprocess.CalledProcessError(1, cmd, stderr="offline\n")
        monkeypatch.setattr(controller_module.subprocess, "run", fail)
        enter_devtools_code(ui, "9956")
        assert ui.state.screen == "DEV_OFFICIAL_SCRIPT_SELECT"
        assert ui.state.dev_scripts == []
        ui.handle(ENC_PUSH)  # nothing to run, screen unchanged
        assert ui.state.screen == "DEV_OFFICIAL_SCRIPT_SELECT"
        ui.handle("9")
        assert ui.state.screen == "IDLE"
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
        # Default (no prior selection) persists "rj12", the first option.
        assert SettingsRepo(conn).get("mount_interface") == "rj12"
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_bluetooth_not_yet_paired_triggers_scan(monkeypatch):
    ui, conn, path = make_ui()
    try:
        monkeypatch.setattr(
            controller_module.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="AA:BB:CC:DD:EE:FF|SynScan Mount\n"),
        )
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN)  # select Bluetooth (index 1), not persisted yet
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "BT_SCAN_SELECT"
        assert ui.state.bt_scan_results == [("AA:BB:CC:DD:EE:FF", "SynScan Mount")]
        assert SettingsRepo(conn).get("mount_interface") == "rj12"  # unchanged until paired
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_wifi_without_configured_ip_shows_message():
    ui, conn, path = make_ui()
    try:
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)  # select WiFi (index 2)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "No mount WiFi IP set"
        assert SettingsRepo(conn).get("mount_interface") == "rj12"  # unchanged
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_wifi_configures_indi_and_persists(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")
        calls = []
        monkeypatch.setattr(
            controller_module.subprocess, "run",
            lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""),
        )
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)  # select WiFi (index 2)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Connecting via WiFi"
        assert "192.168.4.1" in ui.state.dev_message
        assert SettingsRepo(conn).get("mount_interface") == "wifi"
        # The fake Indi has no host/port attrs -- _connect_mount_wifi()
        # falls back to indi_setprop's own defaults (localhost:7624) via
        # getattr(), same as if a real IndiClient were constructed with
        # no explicit host/port override.
        assert calls == [
            ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.CONNECTION_MODE.CONNECTION_TCP=On"],
            ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.DEVICE_ADDRESS.ADDRESS=192.168.4.1"],
            ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.DEVICE_ADDRESS.PORT=11880"],
            ["indi_setprop", "-h", "localhost", "-p", "7624", "Skywatcher Alt-Az.CONNECTION.CONNECT=On"],
        ]
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_wifi_reports_real_failure_reason(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")

        def fail(cmd, **kw):
            # returncode 1, not the retryable 2 (indiserver unreachable) --
            # a malformed/unknown property won't fix itself on retry.
            raise subprocess.CalledProcessError(1, cmd, output="", stderr="No such property CONNECTION_MODE\n")

        monkeypatch.setattr(controller_module.subprocess, "run", fail)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Mount WiFi connect failed"
        assert "No such property" in ui.state.dev_message[1]
        assert SettingsRepo(conn).get("mount_interface") == "rj12"  # unchanged on failure
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_wifi_retries_transient_connect_refusal(monkeypatch):
    # Exit code 2 from indi_setprop (setINDIproperty.c's openINDIServer())
    # specifically means it could not connect to indiserver yet -- e.g. a
    # restart still coming up -- worth one brief retry instead of failing
    # the whole WiFi switch on the first refusal.
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")
        attempts = {"n": 0}

        def flaky_then_ok(cmd, **kw):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise subprocess.CalledProcessError(2, cmd, output="", stderr="connect: Connection refused\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="")

        monkeypatch.setattr(controller_module.subprocess, "run", flaky_then_ok)
        monkeypatch.setattr(controller_module.time, "sleep", lambda s: None)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Connecting via WiFi"
        assert SettingsRepo(conn).get("mount_interface") == "wifi"
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_wifi_gives_up_after_repeated_connect_refusal(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")

        def always_refused(cmd, **kw):
            raise subprocess.CalledProcessError(2, cmd, output="", stderr="connect: Connection refused\n")

        monkeypatch.setattr(controller_module.subprocess, "run", always_refused)
        monkeypatch.setattr(controller_module.time, "sleep", lambda s: None)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Mount WiFi connect failed"
        assert SettingsRepo(conn).get("mount_interface") == "rj12"
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_app_connects_on_first_candidate_port(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")
        setprop_calls = []

        def fake_run(cmd, **kw):
            if cmd[0] == "indi_setprop":
                setprop_calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, stdout="")
            return subprocess.CompletedProcess(cmd, 0, stdout="On\n")  # indi_getprop

        monkeypatch.setattr(controller_module.subprocess, "run", fake_run)
        monkeypatch.setattr(controller_module.time, "sleep", lambda s: None)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)  # SynScan/Stellarium app (index 3)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Connected: SynScan Pro app"
        assert SettingsRepo(conn).get("mount_interface") == "synscan_app"
        assert SettingsRepo(conn).get("mount_app_port") == "11881"
        assert any("DEVICE_ADDRESS.PORT=11881" in c[-1] for c in setprop_calls)
        # Only the first candidate port was ever tried.
        assert not any("11882" in c[-1] or "10001" in c[-1] for c in setprop_calls)
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_app_falls_through_to_a_later_port(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")

        # Track which port is currently "active" so the getprop readback
        # reflects only the most recent DEVICE_ADDRESS.PORT setprop, like
        # a real driver would -- only the 10001 (Stellarium) attempt
        # actually comes up.
        state = {"port": None}

        def run(cmd, **kw):
            if cmd[0] == "indi_setprop":
                spec = cmd[-1]
                if "DEVICE_ADDRESS.PORT=" in spec:
                    state["port"] = spec.split("=")[-1]
                return subprocess.CompletedProcess(cmd, 0, stdout="")
            stdout = "On\n" if state["port"] == "10001" else "Off\n"
            return subprocess.CompletedProcess(cmd, 0, stdout=stdout)

        monkeypatch.setattr(controller_module.subprocess, "run", run)
        monkeypatch.setattr(controller_module.time, "sleep", lambda s: None)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Connected: Stellarium"
        assert SettingsRepo(conn).get("mount_app_port") == "10001"
    finally: conn.close(); os.unlink(path)


def test_devtools_9600_app_reports_failure_when_no_port_connects(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("mount_wifi_host", "192.168.4.1")

        def run(cmd, **kw):
            if cmd[0] == "indi_setprop":
                return subprocess.CompletedProcess(cmd, 0, stdout="")
            return subprocess.CompletedProcess(cmd, 0, stdout="Off\n")  # never comes up

        monkeypatch.setattr(controller_module.subprocess, "run", run)
        monkeypatch.setattr(controller_module.time, "sleep", lambda s: None)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN); ui.handle(ENC_DOWN); ui.handle(ENC_DOWN)
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Mount app connect failed"
        assert SettingsRepo(conn).get("mount_interface") == "rj12"  # unchanged
    finally: conn.close(); os.unlink(path)


def test_devtools_bluetooth_scan_pair_persists_and_reopens_selected(monkeypatch):
    ui, conn, path = make_ui()
    try:
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[-2:] == ["scan", "8"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="AA:BB:CC:DD:EE:FF|SynScan Mount\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="")

        monkeypatch.setattr(controller_module.subprocess, "run", fake_run)
        enter_devtools_code(ui, "9600")
        ui.handle(ENC_DOWN)
        ui.handle(ENC_PUSH)  # scans
        assert ui.state.screen == "BT_SCAN_SELECT"
        ui.handle(ENC_PUSH)  # pick the only device, pair it
        assert ui.state.screen == "DEV_MESSAGE"
        assert "Paired" in ui.state.dev_message[0]
        assert SettingsRepo(conn).get("bluetooth_mount_paired") == "1"
        assert SettingsRepo(conn).get("mount_interface") == "bluetooth"
        assert calls[0][-2:] == ["scan", "8"]
        assert calls[1][-2:] == ["pair", "AA:BB:CC:DD:EE:FF"]

        # Reopening 9600 now goes straight to IDLE on push (already paired),
        # no rescanning needed, and starts on the previously picked slot.
        enter_devtools_code(ui, "9600")
        assert ui.state.screen == "IFACE_SELECT"
        assert ui.state.index == 1
        calls.clear()
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "IDLE"
        assert calls == []
    finally: conn.close(); os.unlink(path)


def test_devtools_bluetooth_scan_finds_nothing(monkeypatch):
    ui, conn, path = make_ui()
    try:
        monkeypatch.setattr(
            controller_module.subprocess, "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=""),
        )
        enter_devtools_code(ui, "9601")
        assert ui.state.screen == "DEV_MESSAGE"
        assert "No Bluetooth devices found" in ui.state.dev_message[0]
    finally: conn.close(); os.unlink(path)


def test_devtools_bluetooth_scan_failure_is_reported(monkeypatch):
    ui, conn, path = make_ui()
    try:
        def fail(cmd, **kw): raise OSError("bluetoothctl not found")
        monkeypatch.setattr(controller_module.subprocess, "run", fail)
        enter_devtools_code(ui, "9601")
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Bluetooth scan failed"
    finally: conn.close(); os.unlink(path)


def test_devtools_bluetooth_scan_failure_shows_the_real_reason(monkeypatch):
    # A failed scan used to show a useless truncated repr of the command
    # itself ("Command '['sudo', '/usr/local/s") instead of the actual
    # reason (bluetoothctl's own stderr) — this is what the owner actually
    # needs to diagnose a real hardware/adapter problem.
    ui, conn, path = make_ui()
    try:
        def fail(cmd, **kw):
            raise subprocess.CalledProcessError(
                1, cmd, output="", stderr="No default controller available\n"
            )
        monkeypatch.setattr(controller_module.subprocess, "run", fail)
        enter_devtools_code(ui, "9601")
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Bluetooth scan failed"
        assert "No default controller available" in ui.state.dev_message[1]
    finally: conn.close(); os.unlink(path)


def test_devtools_bluetooth_pair_failure_suggests_manual_ssh_pairing(monkeypatch):
    ui, conn, path = make_ui()
    try:
        def fake_run(cmd, **kw):
            if cmd[-2:] == ["scan", "8"]:
                return subprocess.CompletedProcess(cmd, 0, stdout="AA:BB:CC:DD:EE:FF|SynScan Mount\n")
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(controller_module.subprocess, "run", fake_run)
        enter_devtools_code(ui, "9601")
        ui.handle(ENC_PUSH)  # pick the only device, pairing fails (e.g. needs a PIN)
        assert ui.state.screen == "DEV_MESSAGE"
        assert ui.state.dev_message[0] == "Pairing failed"
        assert SettingsRepo(conn).get("bluetooth_mount_paired") is None
    finally: conn.close(); os.unlink(path)


def test_devtools_5001_shows_configured_ssids_and_switches(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("wifi_ssid", "HomeNet")
        SettingsRepo(conn).set("wifi_ssid_secondary", "FieldHotspot")
        calls = []
        monkeypatch.setattr(controller_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        enter_devtools_code(ui, "5001")
        assert ui.state.screen == "WIFI_SWITCH_SELECT"
        assert ui.state.wifi_switch_labels == ["Primary: HomeNet", "Secondary: FieldHotspot"]
        ui.handle(ENC_DOWN)  # move to Secondary
        ui.handle(ENC_PUSH)
        assert calls == [["sudo", "/usr/local/sbin/japyscope-wifi-switch", "secondary"]]
        assert SettingsRepo(conn).get("wifi_active_slot") == "secondary"
        assert ui.state.screen == "DEV_MESSAGE"
        assert "Switched to secondary" in ui.state.dev_message[0]
    finally: conn.close(); os.unlink(path)


def test_devtools_5001_reopens_on_previously_active_slot():
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("wifi_ssid_secondary", "FieldHotspot")
        SettingsRepo(conn).set("wifi_active_slot", "secondary")
        enter_devtools_code(ui, "5001")
        assert ui.state.screen == "WIFI_SWITCH_SELECT"
        assert ui.state.index == 1
    finally: conn.close(); os.unlink(path)


def test_devtools_5001_unconfigured_slot_shows_error_without_switching(monkeypatch):
    ui, conn, path = make_ui()
    try:
        calls = []
        monkeypatch.setattr(controller_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        enter_devtools_code(ui, "5001")
        ui.handle(ENC_DOWN)  # Secondary, never configured
        ui.handle(ENC_PUSH)
        assert calls == []
        assert ui.state.screen == "DEV_MESSAGE"
        assert "not set up" in ui.state.dev_message[0]
    finally: conn.close(); os.unlink(path)


def test_devtools_5001_switch_to_primary_works_even_when_its_ssid_was_never_recorded(monkeypatch):
    # Wi-Fi configured some other way than /setup (Raspberry Pi Imager,
    # raspi-config, by hand) never writes settings.wifi_ssid, even though
    # that network is the one actually working. Switching back to it must
    # not be gated on knowing its SSID -- only secondary (the one slot
    # JapyScope actually creates) needs that guard.
    ui, conn, path = make_ui()
    try:
        calls = []
        monkeypatch.setattr(controller_module.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
        enter_devtools_code(ui, "5001")
        assert ui.state.wifi_switch_labels[0] == "Primary: (unknown)"
        ui.handle(ENC_PUSH)  # Primary (index 0), still never configured via /setup
        assert calls == [["sudo", "/usr/local/sbin/japyscope-wifi-switch", "primary"]]
        assert SettingsRepo(conn).get("wifi_active_slot") == "primary"
        assert "Switched to primary" in ui.state.dev_message[0]
    finally: conn.close(); os.unlink(path)


def test_devtools_5001_switch_failure_is_reported(monkeypatch):
    ui, conn, path = make_ui()
    try:
        SettingsRepo(conn).set("wifi_ssid", "HomeNet")

        def fail(cmd, **kw): raise OSError("sudo: command not found")
        monkeypatch.setattr(controller_module.subprocess, "run", fail)
        enter_devtools_code(ui, "5001")
        ui.handle(ENC_PUSH)  # Primary (index 0)
        assert ui.state.dev_message[0] == "Switch to primary failed"
        assert SettingsRepo(conn).get("wifi_active_slot") is None
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
        star = controller_module.STARS[1]  # Vega
        ui.state.screen = "ALIGN_JOG"
        ui.state.align_star = star; ui.state.jog_target = star.name; ui.state.align_points = 0
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
        assert ui.indi.synced == (star.ra, star.dec)
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


def test_align_jog_sync_failure_does_not_block_the_menu_flow():
    """Unlike the boot-time single-star sync, a sync failure during the
    Manual (2 stars) menu flow must not strand the user — real hardware
    doesn't implement sync() yet, so this path has to keep working."""
    ui, conn, path = make_ui()
    try:
        def fail(*_args): raise NotImplementedError("no hardware yet")
        ui.indi.sync = fail
        ui.state.screen = "ALIGN_JOG"
        ui.state.align_star = controller_module.STARS[0]; ui.state.align_points = 0
        ui.handle(ENC_PUSH)
        assert ui.state.screen == "ALIGN_STAR_PICK" and ui.state.align_points == 1
    finally: conn.close(); os.unlink(path)


def test_manual_two_star_alignment_syncs_each_real_star():
    ui, conn, path = make_ui()
    try:
        first, second = controller_module.STARS[0], controller_module.STARS[1]
        ui.state.screen = "ALIGN_STAR_PICK"; ui.state.align_points = 0
        ui.handle(ENC_PUSH)  # pick first star (index 0)
        assert ui.state.align_star is first
        ui.handle(ENC_PUSH)  # confirm centered -> sync(first)
        assert ui.indi.synced == (first.ra, first.dec)
        assert ui.state.screen == "ALIGN_STAR_PICK" and ui.state.align_points == 1

        ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)  # pick second star (index 1)
        assert ui.state.align_star is second
        ui.handle(ENC_PUSH)  # confirm centered -> sync(second)
        assert ui.indi.synced == (second.ra, second.dec)
        assert ui.state.screen == "ALIGN_MORE" and ui.state.align_points == 2

        # "aligned" only flips once the user explicitly confirms, at the
        # end of ALIGN_CONFIRM — not merely from syncing each star.
        assert StateRepo(conn).get("aligned") is None
        ui.handle(ENC_DOWN); ui.handle(ENC_PUSH)  # ALIGN_MORE -> "Finish alignment"
        assert ui.state.screen == "ALIGN_CONFIRM"
        ui.handle(ENC_PUSH)  # "Yes, done"
        assert StateRepo(conn).get("aligned") == "true"
    finally: conn.close(); os.unlink(path)


def test_align_save_lands_on_idle_not_back_on_align_confirm():
    # Confirmed on hardware as an infinite loop: ALIGN_SAVE's timer used to
    # send the screen back to ALIGN_CONFIRM — the very screen whose "Yes,
    # done" enters ALIGN_SAVE in the first place — so any further input
    # (a queued push, encoder noise) re-entered ALIGN_SAVE and the cycle
    # repeated until the app crashed.
    ui, conn, path = make_ui()
    try:
        now = [1000.0]
        ui.clock = lambda: now[0]
        ui.state.screen = "ALIGN_CONFIRM"; ui.state.index = 0
        ui.handle(ENC_PUSH)  # "Yes, done" -> ALIGN_SAVE
        assert ui.state.screen == "ALIGN_SAVE"

        now[0] += 2.0  # past the 1.5s transition_at
        ui.tick()
        assert ui.state.screen == "IDLE"
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
        assert controller_module.SPEEDS == tuple(range(1, 10))
        ui.state.screen = "TRACK"; ui.state.speed = 8
        ui.handle("6")
        assert ui.indi.jogs[-1] == ("E", 8)
    finally: conn.close(); os.unlink(path)


def test_speed_screens_display_the_actual_mount_rate():
    ui, conn, path = make_ui()
    try:
        ui.state.speed = 9
        ui._set("SPEED_ADJUST")
        assert ui.display.lines[1] == "Max"

        ui._set("ALIGN_JOG")
        assert "Speed 800x" in " ".join(ui.display.lines)
    finally: conn.close(); os.unlink(path)


def test_jog_stays_on_while_held_and_stops_on_release():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"
        ui.handle("2")
        assert ui.indi.jogs == [("N", 1)]
        for _ in range(5):
            ui.tick()
        assert ui.indi.jog_stops == []
        ui.handle(key_up("2"))
        assert ui.indi.jog_stops == ["N"]
        assert ui.state.jog_direction == ""
    finally: conn.close(); os.unlink(path)


def test_jog_ignores_release_from_a_different_input():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"
        ui.handle("2")  # keypad starts north
        ui.handle(key_up(ENC_UP))  # joystick also maps to north, but did not start it
        assert ui.indi.jog_stops == []
        assert ui.state.jog_direction == "N"

        ui.handle(key_up("2"))
        assert ui.indi.jog_stops == ["N"]
        assert ui.state.jog_direction == ""
    finally: conn.close(); os.unlink(path)


def test_jog_watchdog_stops_a_stuck_held_key():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"
        ui.handle("6")
        ui.state.jog_started_at = ui.clock() - controller_module.JOG_HOLD_TIMEOUT_SECONDS - 1
        ui.tick()
        assert ui.indi.jog_stops == ["E"]
        assert ui.state.jog_direction == ""
        ui.handle("6")
        assert len(ui.indi.jogs) == 1
        ui.handle(key_up("6"))
        ui.handle("6")
        assert len(ui.indi.jogs) == 2
    finally: conn.close(); os.unlink(path)


def test_process_teardown_stops_active_jog():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "TRACK"
        ui.handle("2")
        ui.stop_motion()
        assert ui.indi.jog_stops == ["N"]
        assert ui.state.jog_direction == ""
    finally: conn.close(); os.unlink(path)


def test_process_teardown_aborts_active_slew():
    ui, conn, path = make_ui()
    try:
        ui.state.screen = "SLEW"
        ui.stop_motion()
        assert ui.indi.aborted is True
    finally: conn.close(); os.unlink(path)


def test_failed_jog_attempts_safety_abort():
    ui, conn, path = make_ui()
    try:
        def fail(*_args): raise ConnectionError("mount stopped responding")
        ui.indi.jog = fail
        ui.state.screen = "TRACK"
        ui.handle("2")
        assert ui.indi.aborted is True
        assert ui.state.jog_direction == ""
    finally: conn.close(); os.unlink(path)


def test_scrolling_never_forces_a_full_refresh_mid_burst():
    # A fixed "every Nth scroll is full" cadence used to interrupt
    # otherwise-smooth scrolling with an unwanted full, visibly-flashing
    # refresh mid-burst — removed. Scrolling should stay partial no
    # matter how many consecutive detents happen; only keypad "3" clears
    # ghosting.
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        assert ui.display.partial is False  # screen transitions always get a full refresh

        for _ in range(10):
            ui.handle(ENC_DOWN)
            assert ui.display.partial is True
    finally: conn.close(); os.unlink(path)


def test_tick_never_auto_promotes_scrolling_to_a_full_refresh():
    # An idle flush used to force a full, visibly-flashing refresh shortly
    # after scrolling stopped (even after a single isolated click) —
    # reported on hardware as still interrupting otherwise-smooth
    # scrolling, so it was removed outright. tick() should never turn a
    # pending partial frame into a full one on its own, whether scrolling
    # was a single click or a longer burst; only keypad "3" forces a full
    # refresh now.
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        now = [1000.0]
        ui.clock = lambda: now[0]

        ui.handle(ENC_DOWN)
        ui.handle(ENC_DOWN)
        assert ui.display.partial is True

        now[0] += 10.0
        ui.tick()
        assert ui.display.partial is True  # no auto full refresh, however long idle
    finally: conn.close(); os.unlink(path)


def test_about_screen_shows_the_actual_running_release(monkeypatch):
    ui, conn, path = make_ui()
    try:
        monkeypatch.setattr(controller_module, "current_version", lambda: "v1.2.3")
        ui._set("ABOUT")
        assert ui.display.lines[2] == "Firmware v1.2.3"
    finally: conn.close(); os.unlink(path)


def test_about_screen_falls_back_to_dev_outside_an_installed_release(monkeypatch):
    ui, conn, path = make_ui()
    try:
        monkeypatch.setattr(controller_module, "current_version", lambda: None)
        ui._set("ABOUT")
        assert ui.display.lines[2] == "Firmware dev"
    finally: conn.close(); os.unlink(path)


def test_keypad_1_and_7_are_encoder_up_down_stand_ins_on_menu():
    # Temporary stopgap while the physical rotary encoder is unreliable —
    # "1"/"7" on the matrix keypad should move the selection exactly like
    # ENC_UP/ENC_DOWN wherever _move() is used.
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        ui.handle("7")
        assert ui.state.index == 1
        ui.handle("1")
        assert ui.state.index == 0
    finally: conn.close(); os.unlink(path)


def test_keypad_7_on_idle_still_opens_speed_adjust_not_navigation():
    # IDLE is the one screen where literal "7" already means something
    # (open SPEED_ADJUST) — that binding must keep winning over the
    # ENC_DOWN stand-in, so "7" there should NOT move the IDLE menu.
    ui, conn, path = make_ui()
    try:
        ui._set("IDLE", 0)
        ui.handle("7")
        assert ui.state.screen == "SPEED_ADJUST"
    finally: conn.close(); os.unlink(path)


def test_keypad_1_still_works_as_encoder_up_stand_in_on_idle():
    # "1" has no conflicting binding on IDLE, so it should still navigate
    # the home menu there even though "7" is reserved for speed.
    ui, conn, path = make_ui()
    try:
        ui._set("IDLE", 1)
        ui.handle("1")
        assert ui.state.screen == "IDLE" and ui.state.index == 0
    finally: conn.close(); os.unlink(path)


def test_keypad_5_is_an_encoder_push_stand_in():
    # Same stopgap spirit as "1"/"7": "5" (the keypad's center "OK" key,
    # below the 2/4/6/8 jog directions) should act as ENC_PUSH everywhere
    # except TYPE, where it's still a T9 letter key.
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        ui.handle("5")
        assert ui.state.screen == "TIME_SYNC"  # MENU item 0 selected, same as ENC_PUSH
    finally: conn.close(); os.unlink(path)


def test_keypad_5_still_types_in_smartsearch_not_select():
    ui, conn, path = make_ui()
    try:
        ui._set("TYPE")
        ui.handle("5")
        assert ui.state.text == "m"  # T9 letter entry, not ENC_PUSH's "search"
    finally: conn.close(); os.unlink(path)


def test_keypad_3_forces_a_full_refresh_without_changing_state():
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 2)
        ui.display.partial = True  # pretend the last draw was partial
        ui.handle("3")
        assert ui.state.screen == "MENU" and ui.state.index == 2  # unchanged
        assert ui.display.partial is False  # forced full refresh
    finally: conn.close(); os.unlink(path)


def test_keypad_3_still_types_in_smartsearch_not_force_refresh():
    ui, conn, path = make_ui()
    try:
        ui._set("TYPE")
        ui.handle("3")
        assert ui.state.text == "g"  # T9 letter entry, not a forced refresh
    finally: conn.close(); os.unlink(path)


def test_screen_transitions_are_always_a_full_refresh():
    # Confirmed on hardware: making _set() partial was wrong, especially
    # noticeable going back with "9" — screen transitions (a completely
    # different frame each time) should always be a full refresh.
    ui, conn, path = make_ui()
    try:
        ui._set("IDLE")
        assert ui.display.partial is False
        ui._set("MENU", 0)
        assert ui.display.partial is False
        ui.handle("9")
        assert ui.state.screen == "IDLE" and ui.display.partial is False
    finally: conn.close(); os.unlink(path)


def test_scroll_indicator_set_when_a_menu_does_not_fit_at_a_glance():
    # MENU has 11 entries but only 5 rows are available for them (6
    # visible_rows minus 1 for the title, no footer) — it doesn't fit at
    # a glance, so render() should hand the display a scrollbar (see
    # ControllerUI._visible()'s docstring): (row_start=1, rows, start,
    # total).
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        assert ui.display.scroll == (1, 5, 0, 11)
    finally: conn.close(); os.unlink(path)


def test_scroll_indicator_absent_when_a_menu_fits_on_screen():
    # IDLE's HOME menu is only 3 entries with a footer (aligned/not
    # aligned) — 4 rows are available, so everything fits already; no
    # scrollbar should be drawn for it.
    ui, conn, path = make_ui()
    try:
        ui._set("IDLE")
        assert ui.display.scroll is None
    finally: conn.close(); os.unlink(path)


def test_scroll_indicator_tracks_the_current_position_while_scrolling():
    ui, conn, path = make_ui()
    try:
        ui._set("MENU", 0)
        assert ui.display.scroll == (1, 5, 0, 11)

        for _ in range(6):
            ui.handle(ENC_DOWN)
        assert ui.state.index == 6
        assert ui.display.scroll == (1, 5, 6, 11)  # window scrolled to keep index 6 visible
    finally: conn.close(); os.unlink(path)


def test_refresh_status_skips_a_locked_key_instead_of_crashing(monkeypatch):
    # A transient "database is locked" on one status key must be logged and
    # skipped for that tick, not propagate out of _refresh_status() and crash
    # the whole UI loop (see issue #36 — busy_timeout/WAL already handle the
    # retry at the SQLite level; this is the belt-and-suspenders layer).
    ui, conn, path = make_ui()
    try:
        status = MountStatus(
            connected=True, ra="1:00:00", dec="+10:00:00", alt=45.0, az=90.0,
            tracking=True, aligned=True, parked=False,
        )
        ui.indi.get_status = lambda: status

        real_set = ui.runtime.set
        calls = []

        def flaky_set(key, value):
            calls.append(key)
            if key == "ra":
                raise sqlite3.OperationalError("database is locked")
            real_set(key, value)

        monkeypatch.setattr(ui.runtime, "set", flaky_set)

        ui._refresh_status()  # must not raise

        assert "ra" in calls  # the locked key was attempted
        assert StateRepo(conn).get("ra") is None  # ...but its write was skipped
        assert StateRepo(conn).get("dec") == "+10:00:00"  # other keys still wrote fine
        assert StateRepo(conn).get("indi_connected") == "true"
    finally: conn.close(); os.unlink(path)
