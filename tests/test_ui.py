import os
import tempfile

import requests

from firmware.hal.display.base import DisplayHAL
from firmware.hal.input.base import InputHAL
from firmware.hal.input.keys import ENC_DOWN, ENC_PUSH, FN2
from firmware.ui import ControllerUI, SearchResult, SmartSearch
from shared.db import CatalogRepo, StateRepo, connect, init_db


class Display(DisplayHAL):
    def __init__(self):
        super().__init__(); self.lines = []; self.backlight = None
    def draw_lines(self, lines): self.lines = lines
    def set_backlight(self, r, g, b): self.backlight = (r, g, b)


class Input(InputHAL):
    def poll(self, timeout=0.1): return None


class Indi:
    def __init__(self): self.synced = None; self.goto_target = None; self.parked = False
    def sync(self, ra, dec): self.synced = (ra, dec)
    def goto(self, ra, dec): self.goto_target = (ra, dec)
    def park(self): self.parked = True


def make_ui():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = connect(path); init_db(conn)
    ui = ControllerUI(Display(), Input(), Indi(), conn)
    return ui, conn, path


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
