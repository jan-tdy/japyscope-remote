"""Display-independent controller state machine.

The screen names mirror the interactive mockup in ``docs/mockup.html``.  The
state machine owns navigation and persistence; concrete display, input and
INDI implementations are injected so the same code runs on a Pi or in
``--simulate`` mode.
"""
from __future__ import annotations

import logging
import os
import random
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

from firmware.hal.backlight.base import BacklightHAL
from firmware.hal.backlight.simulator import SimulatorBacklight
from firmware.hal.display.base import DisplayHAL
from firmware.hal.input.base import InputHAL
from firmware.hal.input.keys import BKSP, ENC_DOWN, ENC_PUSH, ENC_UP, FN2, JOY_LEFT, JOY_RIGHT
from shared.db import AccessCodeRepo, CatalogRepo, SettingsRepo, StateRepo

from .i18n import DEFAULT_LANGUAGE, LANGUAGES
from .i18n import t as translate
from .search import SearchResult, SmartSearch
from .themes import DEFAULT_THEME, THEMES, get_theme

logger = logging.getLogger(__name__)

T9 = {
    "1": "abc",
    "2": "def",
    "3": "ghi",
    "4": "jkl",
    "5": "mno",
    "6": "pqrs",
    "7": "tuv",
    "8": "wxyz",
    "9": "wxyz",  # SmartSearch-only exception; FN2 is back on TYPE.
}
SPEEDS = (1, 2, 4, 8, 16, 32, 64)
STARS = ("Polaris", "Vega", "Capella", "Deneb", "Arcturus", "Altair")
# Manual N/S/E/W jog, available on screens where the mount can move (see
# docs/CODES.md) — from either the keypad's 2/4/6/8 or the external
# joystick (ENC_UP/ENC_DOWN for its Y-axis, JOY_LEFT/JOY_RIGHT for its
# X-axis; see keys.py for why the joystick reuses the encoder's codes).
JOG_DIRECTIONS = {
    "2": "N", ENC_UP: "N",
    "8": "S", ENC_DOWN: "S",
    "4": "W", JOY_LEFT: "W",
    "6": "E", JOY_RIGHT: "E",
}

BUILTIN_CATALOGS: dict[str, tuple[SearchResult, ...]] = {
    "Basic Objects": (
        SearchResult("Moon", alt=55, source="basic"),
        SearchResult("Mars", "09h12m40s", "+18°02′", alt=30, source="basic"),
        SearchResult("Jupiter", "03h11m05s", "+17°55′", alt=48, source="basic"),
        SearchResult("Saturn", "23h18m22s", "−06°40′", alt=20, source="basic"),
        SearchResult("Polaris", "02h31m49s", "+89°15′", alt=38, source="basic"),
        SearchResult("Vega", "18h36m56s", "+38°47′", alt=61, source="basic"),
    ),
    "Messier": (
        SearchResult("M31 Andromeda Galaxy", "00h42m44s", "+41°16′", alt=29, source="messier"),
        SearchResult("M42 Orion Nebula", "05h35m17s", "−05°23′", alt=-15, source="messier"),
        SearchResult("M13 Hercules Cluster", "16h41m41s", "+36°28′", alt=50, source="messier"),
    ),
    "NGC": (
        SearchResult("NGC 7000 North America", "20h58m48s", "+44°20′", alt=33, source="ngc"),
        SearchResult("NGC 869 Double Cluster", "02h19m00s", "+57°09′", alt=41, source="ngc"),
    ),
    "Caldwell": (
        SearchResult("C14 Double Cluster", "02h20m00s", "+57°08′", alt=41, source="caldwell"),
    ),
}


@dataclass
class UIState:
    screen: str = "BOOT"
    index: int = 0
    return_screen: str = "IDLE"
    speed: int = 1
    text: str = ""
    t9_key: Optional[str] = None
    t9_pos: int = 0
    t9_at: float = 0.0
    results: list[SearchResult] = field(default_factory=list)
    online_available: bool = True
    selected: Optional[SearchResult] = None
    catalog_id: Optional[int] = None
    catalog_title: str = ""
    list_items: list[SearchResult] = field(default_factory=list)
    align_points: int = 0
    jog_target: str = ""
    digits: list[int] = field(default_factory=list)
    digit_value: int = 0
    access_code: str = ""
    access_expires: float = 0.0
    access_last_remaining: int = -1
    transition_at: float = 0.0
    last_status_at: float = 0.0
    error_message: str = ""
    backlight: list[int] = field(default_factory=lambda: [1, 0, 0])
    dev_scripts: list[str] = field(default_factory=list)
    dev_message: list[str] = field(default_factory=list)


class ControllerUI:
    # i18n keys, not display text — translated via self._t() at render time.
    HOME = ("home.menu", "home.catalog", "home.dev_tools")
    MENU = (
        "menu.time_sync", "menu.alignment", "menu.park_toggle", "menu.wifi_access",
        "menu.location", "menu.backlight", "menu.language", "menu.theme",
        "menu.sudo_password", "menu.system", "menu.about",
    )
    CATALOG = ("SmartSearch", "Custom Catalogs", *BUILTIN_CATALOGS)
    # Dev Tools codes 0022/0033 — see docs/CODES.md. Single-option for now,
    # same "real placeholder for future hardware/config" spirit as DRIVERS/
    # INTERFACES above.
    REPOS = ("jan-tdy/japyscope-remote",)
    UPDATE_CHANNELS = (("stable", "Stable only"), ("prerelease", "Stable + prereleases"))

    def __init__(
        self,
        display: DisplayHAL,
        input_hal: InputHAL,
        indi_client,
        conn,
        search: Optional[SmartSearch] = None,
        clock: Callable[[], float] = time.time,
        backlight: Optional[BacklightHAL] = None,
        indi_manager=None,
    ):
        self.display = display
        self.input = input_hal
        self.indi = indi_client
        # Owns the indiserver subprocess (firmware.indi.manager.IndiServerManager) —
        # None in --simulate mode, where there's no real indiserver to restart.
        # Dev Tools code 1111.
        self.indi_manager = indi_manager
        self.backlight = backlight or SimulatorBacklight()
        self.catalogs = CatalogRepo(conn)
        self.settings = SettingsRepo(conn)
        self.runtime = StateRepo(conn)
        self.codes = AccessCodeRepo(conn)
        self.search = search or SmartSearch()
        self.clock = clock
        self.state = UIState()
        self.running = True

    def start(self) -> None:
        self.render()
        self.state.screen = "BOOT_PARK_CHECK"
        self.state.index = 0
        self.render()

    def run(self) -> None:
        self.start()
        while self.running:
            key = self.input.poll(0.2)
            if key:
                self.handle(key)
            self.tick()

    def tick(self) -> None:
        now = self.clock()
        s = self.state
        if now - s.last_status_at >= 2:
            s.last_status_at = now
            self._refresh_status()
        if s.transition_at and now >= s.transition_at:
            s.transition_at = 0
            if s.screen == "SLEW": self._set("TRACK")
            elif s.screen == "PARKING": self.runtime.set("parked", "true"); self._set("PARKED")
            elif s.screen == "ALIGN_SAVE": self._set("ALIGN_CONFIRM")
        if s.screen == "WIFI_ACCESS":
            remaining = max(0, int(s.access_expires - now))
            if now >= s.access_expires: self._set("MENU", 3)
            elif remaining != s.access_last_remaining:
                s.access_last_remaining = remaining
                self.render()

    def _refresh_status(self) -> None:
        get_status = getattr(self.indi, "get_status", None)
        if get_status is None: return
        try:
            status = get_status()
        except (NotImplementedError, ConnectionError) as exc:
            logger.debug("INDI status not available: %s", exc)
            return
        if status is None: return
        values = {
            "indi_connected": status.connected, "ra": status.ra, "dec": status.dec,
            "alt": status.alt, "az": status.az, "tracking": status.tracking,
            "aligned": status.aligned, "parked": status.parked,
        }
        for key, value in values.items():
            encoded = str(value).lower() if isinstance(value, bool) else str(value)
            if self.runtime.get(key) != encoded:
                self.runtime.set(key, encoded)

    def _set(self, screen: str, index: int = 0) -> None:
        self.state.screen = screen
        self.state.index = index
        self.render()

    @staticmethod
    def _truth(value: Optional[str]) -> bool:
        return str(value).lower() in {"1", "true", "yes", "on"}

    def _t(self, key: str, **kwargs: object) -> str:
        return translate(key, self.settings.get("language", DEFAULT_LANGUAGE), **kwargs)

    def _theme(self):
        return get_theme(self.settings.get("ui_theme", DEFAULT_THEME))

    def _visible(self, title: str, values: Sequence[str], footer: str = "rotate · push · 9=back") -> list[str]:
        rows = max(1, self.display.visible_rows - 2)
        start = max(0, min(self.state.index, max(0, len(values) - rows)))
        theme = self._theme()
        lines = [title]
        for i in range(start, min(len(values), start + rows)):
            selected = i == self.state.index
            text = values[i]
            if selected and theme.wrap:
                text = f"{theme.wrap[0]}{text}{theme.wrap[1]}"
            lines.append((theme.marker if selected else theme.unmarked) + text)
            if selected and theme.invert:
                self._invert_row = len(lines) - 1
        return [*lines, footer]

    def render(self) -> None:
        s = self.state
        screen = s.screen
        self._invert_row: Optional[int] = None
        if screen == "BOOT":
            lines = ["JapyScope Remote", "by JapySoft", "", "Starting…"]
        elif screen == "BOOT_PARK_CHECK":
            lines = self._visible(
                self._t("boot.park_question"),
                [self._t("boot.park_yes"), self._t("boot.park_no")],
                self._t("footer.rotate_push"),
            )
        elif screen == "BOOT_SYNC_FAILED":
            lines = [
                self._t("boot.sync_failed_1"), self._t("boot.sync_failed_2"),
                self._t("boot.sync_failed_3"), self._t("boot.sync_failed_4"),
            ]
        elif screen == "IDLE":
            aligned = self._truth(self.runtime.get("aligned", "false"))
            lines = self._visible(
                f"JapyScope {datetime.now():%H:%M:%S}", [self._t(k) for k in self.HOME],
                self._t("home.aligned") if aligned else self._t("home.not_aligned"),
            )
        elif screen == "MENU":
            lines = self._visible(self._t("menu.title"), [self._t(k) for k in self.MENU])
        elif screen == "LANGUAGE":
            lines = self._visible(self._t("language.title"), [name for name, _ in LANGUAGES])
        elif screen == "THEME":
            lines = self._visible(self._t("theme.title"), [theme.label for theme in THEMES])
        elif screen == "CATALOG_MENU":
            lines = self._visible("CATALOG", self.CATALOG)
        elif screen == "CUSTOM_CATALOGS":
            names = [row["name"] for row in self.catalogs.list_catalogs()]
            lines = self._visible("Custom catalogs", names or ["(empty)"])
        elif screen == "LIST":
            labels = [f"{o.name} [Alt:{'—' if o.alt is None else f'{o.alt:g}°'}]" for o in s.list_items]
            lines = self._visible(f"{s.catalog_title} ({len(labels)})", labels or ["(empty)"])
        elif screen == "TYPE":
            lines = ["SmartSearch", s.text + "_", "push=search BKSP=delete", "FN2=back · 9=wxyz"]
        elif screen == "RESULTS":
            labels = [o.name for o in s.results]
            note = "online + local" if s.online_available else "offline · local only"
            lines = self._visible("Search results", labels or ["Nothing found"], note + " · 9=back")
        elif screen == "WARN":
            warnings = []
            if not self._truth(self.runtime.get("aligned", "false")):
                warnings.append("Not aligned — pointing may be off")
            if s.selected and s.selected.alt is not None and s.selected.alt < 0:
                warnings.append("Object below horizon")
            lines = ["WARNING", *(warnings or ["Confirm slew"]), "push=slew · 9=back"]
        elif screen == "TRACK":
            obj = s.selected or SearchResult("Unknown")
            lines = ["TRACKING", obj.name, f"RA {obj.ra or '—'}", f"Dec {obj.dec or '—'} · 9=back"]
        elif screen == "SLEW":
            lines = ["SLEWING TO", s.selected.name if s.selected else "—", "", "7=abort"]
        elif screen == "SLEW_ABORTED":
            lines = ["SLEW ABORTED", s.selected.name if s.selected else "—", "push=continue", "9=back"]
        elif screen == "ALIGN_CHOOSE":
            lines = self._visible("ALIGNMENT", ["Smart (unavailable)", "Manual (2 stars)"])
        elif screen == "ALIGN_SMART_NA":
            lines = ["Smart alignment", "Plate-solve unavailable", "", "push/9=back"]
        elif screen == "ALIGN_STAR_PICK":
            lines = self._visible(f"Point {s.align_points + 1}", STARS)
        elif screen == "ALIGN_JOG":
            lines = [f"Point to {s.jog_target}", f"Speed {s.speed}x", "2/8/4/6/stick=jog", "7=spd · push=ok · 9=back"]
        elif screen == "ALIGN_MORE":
            lines = self._visible(f"Points: {s.align_points}", ["Add another point", "Finish alignment"])
        elif screen == "ALIGN_CONFIRM":
            lines = self._visible("Looks right?", ["Yes, done", "Fine-tune"])
        elif screen == "ALIGN_SAVE":
            lines = ["ALIGNED", "Saving alignment…", "", ""]
        elif screen == "SPEED_ADJUST":
            lines = ["Jog speed", f"{s.speed}x", "rotate=change", "push/9=back"]
        elif screen == "PARK_CONFIRM":
            lines = self._visible(
                self._t("park.confirm_question"), [self._t("park.confirm_yes"), self._t("park.confirm_cancel")]
            )
        elif screen == "PARKING":
            lines = [self._t("park.parking"), "", "", ""]
        elif screen == "PARKED":
            lines = self._visible(
                self._t("park.parked_title"), [self._t("park.unpark"), self._t("park.power_off")],
                self._t("footer.rotate_push"),
            )
        elif screen == "WIFI_ACCESS":
            remain = max(0, int(s.access_expires - self.clock()))
            lines = ["Web UI access code", s.access_code, f"Valid {remain // 60:02}:{remain % 60:02}", "push/9=back"]
        elif screen == "WIFI_SETUP":
            password_path = os.environ.get(
                "JAPYSCOPE_AP_PASSWORD_FILE", "/etc/japyscope/setup-ap-password"
            )
            try:
                password = Path(password_path).read_text(encoding="ascii").strip()
            except OSError:
                password = "see local admin"
            lines = ["Join JapyScope-Setup", f"Password: {password}", "Open 192.168.4.1:8080", "9=back"]
        elif screen == "BACKLIGHT":
            levels = ("Off", "Med", "High")
            labels = [f"{ch}: {levels[s.backlight[i]]}" for i, ch in enumerate("RGB")]
            lines = self._visible("Backlight", labels)
        elif screen in {"DEVTOOLS", "SUDO_SET"}:
            entered = " ".join(map(str, s.digits))
            slots = (entered + " " if entered else "") + " ".join([str(s.digit_value), *(["_"] * max(0, 3 - len(s.digits)))])
            lines = ["Dev Tools" if screen == "DEVTOOLS" else "Set sudo password", f"[ {slots} ]", "rotate=digit push=lock", "9=cancel"]
        elif screen == "LOCATION":
            lines = ["Location", f"Lat {self.settings.get('latitude')}", f"Lon {self.settings.get('longitude')}", "push/9=back"]
        elif screen == "ABOUT":
            lines = [self._t("about.line1"), self._t("about.line2"), self._t("about.line3"), self._t("footer.push_back")]
        elif screen == "DRIVER_SELECT":
            lines = self._visible("Mount driver", ["Sky-Watcher Alt-Az"])
        elif screen == "IFACE_SELECT":
            lines = self._visible("Mount interface", ["RJ12 serial"])
        elif screen == "DEV_REPO_SELECT":
            lines = self._visible("Set repo", list(self.REPOS))
        elif screen == "DEV_CHANNEL_SELECT":
            lines = self._visible("Update channel", [label for _, label in self.UPDATE_CHANNELS])
        elif screen == "DEV_SCRIPT_SELECT":
            lines = self._visible("Run custom script", s.dev_scripts or ["(no .sh scripts found)"])
        elif screen == "DEV_MESSAGE":
            lines = [*s.dev_message, "push/9=back"]
        elif screen == "TIME_SYNC":
            lines = ["Time synchronized", "using system NTP", "", "push/9=back"]
        elif screen == "SYSTEM_CONFIRM":
            lines = ["Power off controller?", "push=yes", "", "9=back"]
        elif screen == "SHUTDOWN":
            lines = ["SHUTTING DOWN…"]
        elif screen == "FN2_EASTER":
            lines = ["Made in Piconcillo.", "Solder and stubbornness.", "", "push/9=back"]
        elif screen == "ERROR":
            lines = ["Cannot slew", s.error_message, "", "push/9=back"]
        else:
            lines = [screen]
        self.display.draw_lines(lines[: self.display.visible_rows], invert_row=self._invert_row)

    def _move(self, key: str, count: int, wrap: bool = True) -> bool:
        if key not in (ENC_UP, ENC_DOWN) or count <= 0:
            return False
        delta = -1 if key == ENC_UP else 1
        self.state.index = (self.state.index + delta) % count if wrap else max(0, min(count - 1, self.state.index + delta))
        self.render()
        return True

    def _jog(self, key: str) -> bool:
        """Manual nudge for screens where the mount can move (see
        JOG_DIRECTIONS). Returns whether `key` was a jog key at all, same
        calling convention as `_move`, so callers fall through to their own
        handling otherwise. Failure (real hardware not wired up yet — see
        firmware/indi/client.py) just logs, same as `park()`'s failure
        handling: a single missed nudge isn't worth leaving the jog screen."""
        direction = JOG_DIRECTIONS.get(key)
        if direction is None:
            return False
        try:
            self.indi.jog(direction, self.state.speed)
        except (NotImplementedError, ConnectionError) as exc:
            logger.error("INDI-004 jog failed: %s", exc)
        return True

    def handle(self, key: str) -> None:
        s = self.state
        if s.screen == "BOOT_PARK_CHECK":
            if self._move(key, 2): return
            if key == ENC_PUSH:
                parked = s.index == 0
                if not parked:
                    try:
                        self.indi.sync(self.runtime.get("ra", "0"), self.runtime.get("dec", "0"))
                    except (NotImplementedError, ConnectionError) as exc:
                        logger.error("INDI-002 boot Sync failed: %s", exc)
                        self._set("BOOT_SYNC_FAILED")
                        return
                self.runtime.set("parked", "true" if parked else "false")
                self._set("PARKED" if parked else "IDLE")
            return
        if s.screen == "BOOT_SYNC_FAILED":
            if key == ENC_PUSH:
                self._set("BOOT_PARK_CHECK", 1)
                self.handle(ENC_PUSH)
            elif key == "9": self._set("BOOT_PARK_CHECK", 1)
            return
        if s.screen == "IDLE":
            if self._move(key, len(self.HOME)): return
            if key == ENC_PUSH:
                self._set(("MENU", "CATALOG_MENU", "DEVTOOLS")[s.index]); s.digits = []
            elif key == "7": self._speed("IDLE")
            elif key == FN2: self._set("FN2_EASTER")
            return
        if s.screen == "MENU":
            if self._move(key, len(self.MENU)): return
            if key == "9": self._set("IDLE")
            elif key == ENC_PUSH: self._select_menu()
            return
        if s.screen == "CATALOG_MENU":
            if self._move(key, len(self.CATALOG)): return
            if key == "9": self._set("IDLE")
            elif key == ENC_PUSH: self._open_catalog()
            return
        if s.screen == "CUSTOM_CATALOGS":
            rows = self.catalogs.list_catalogs()
            if self._move(key, max(1, len(rows))): return
            if key == "9": self._set("CATALOG_MENU", 1)
            elif key == ENC_PUSH and rows:
                row = rows[s.index]; s.catalog_id = row["id"]
                s.list_items = [SearchResult(i["name"], i["ra"], i["dec"], i["type"], i["source"]) for i in self.catalogs.list_items(row["id"])]
                s.catalog_title = row["name"]; self._set("LIST")
            return
        if s.screen == "LIST":
            if self._move(key, max(1, len(s.list_items)), wrap=False): return
            if key == "9": self._set("CUSTOM_CATALOGS" if s.catalog_id else "CATALOG_MENU")
            elif key == ENC_PUSH and s.list_items: self._confirm_slew(s.list_items[s.index], "LIST")
            return
        if s.screen == "TYPE": self._type(key); return
        if s.screen == "RESULTS":
            if self._move(key, max(1, len(s.results)), wrap=False): return
            if key == "9": self._set("TYPE")
            elif key == ENC_PUSH and s.results: self._confirm_slew(s.results[s.index], "RESULTS")
            return
        if s.screen == "WARN":
            if key == ENC_PUSH: self._begin_slew()
            elif key == "9": self._set(s.return_screen)
            return
        if s.screen == "SLEW":
            if key == "7": self._set("SLEW_ABORTED")
            return
        if s.screen == "SLEW_ABORTED":
            if key == ENC_PUSH: self._begin_slew()
            elif key == "9": self._set("IDLE")
            return
        if s.screen == "TRACK":
            if self._jog(key): return
            if key == "9": self._set("IDLE")
            elif key == "7": self._speed("TRACK")
            return
        if s.screen == "SPEED_ADJUST":
            idx = SPEEDS.index(s.speed)
            if key in (ENC_UP, ENC_DOWN):
                s.speed = SPEEDS[max(0, min(len(SPEEDS) - 1, idx + (-1 if key == ENC_UP else 1)))]; self.render()
            elif key in (ENC_PUSH, "9"): self._set(s.return_screen)
            return
        if s.screen == "ALIGN_CHOOSE":
            if self._move(key, 2): return
            if key == "9": self._set("MENU", 1)
            elif key == ENC_PUSH:
                if s.index == 0: self._set("ALIGN_SMART_NA")
                else: s.align_points = 0; self._set("ALIGN_STAR_PICK")
            return
        if s.screen == "ALIGN_STAR_PICK":
            if self._move(key, len(STARS)): return
            if key == "9": self._set("ALIGN_CHOOSE", 1)
            elif key == ENC_PUSH: s.jog_target = STARS[s.index]; self._set("ALIGN_JOG")
            return
        if s.screen == "ALIGN_JOG":
            if self._jog(key): return
            if key == "7": self._speed("ALIGN_JOG")
            elif key == "9": self._set("ALIGN_CHOOSE", 1)
            elif key == ENC_PUSH:
                s.align_points += 1; self._set("ALIGN_STAR_PICK" if s.align_points < 2 else "ALIGN_MORE")
            return
        if s.screen == "ALIGN_MORE":
            if self._move(key, 2): return
            if key == "9": self._set("ALIGN_CHOOSE", 1)
            elif key == ENC_PUSH: self._set("ALIGN_STAR_PICK" if s.index == 0 else "ALIGN_CONFIRM")
            return
        if s.screen == "ALIGN_CONFIRM":
            if self._move(key, 2): return
            if key == "9": self._set("ALIGN_CHOOSE", 1)
            elif key == ENC_PUSH:
                if s.index == 0:
                    self.runtime.set("aligned", "true")
                    s.transition_at = self.clock() + 1.5
                    self._set("ALIGN_SAVE")
                else: self._set("ALIGN_STAR_PICK")
            return
        if s.screen == "PARK_CONFIRM":
            if self._move(key, 2): return
            if key == "9" or (key == ENC_PUSH and s.index == 1): self._set("MENU", 2)
            elif key == ENC_PUSH:
                try:
                    self.indi.park()
                except (NotImplementedError, ConnectionError) as exc:
                    logger.error("INDI-002 park failed: %s", exc)
                    return
                s.transition_at = self.clock() + 1.5
                self._set("PARKING")
            return
        if s.screen == "PARKED":
            if self._move(key, 2): return
            if key == ENC_PUSH and s.index == 0: self.runtime.set("parked", "false"); self._set("IDLE")
            elif key == ENC_PUSH: self.running = False; self._set("SHUTDOWN")
            return
        if s.screen == "WIFI_ACCESS":
            if key in ("9", ENC_PUSH): self._set("MENU", 3)
            return
        if s.screen == "BACKLIGHT":
            if self._move(key, 3): return
            if key == ENC_PUSH:
                s.backlight[s.index] = (s.backlight[s.index] + 1) % 3
                self.backlight.set(*s.backlight); self.render()
            elif key == "9": self._set("MENU", 5)
            return
        if s.screen == "LANGUAGE":
            if self._move(key, len(LANGUAGES)): return
            if key == "9": self._set("MENU", 6)
            elif key == ENC_PUSH:
                self.settings.set("language", LANGUAGES[s.index][1])
                self._set("MENU", 6)
            return
        if s.screen == "THEME":
            if self._move(key, len(THEMES)): return
            if key == "9": self._set("MENU", 7)
            elif key == ENC_PUSH:
                self.settings.set("ui_theme", THEMES[s.index].key)
                self._set("MENU", 7)
            return
        if s.screen in {"DEVTOOLS", "SUDO_SET"}: self._digits(key); return
        if s.screen == "DEV_REPO_SELECT":
            if self._move(key, len(self.REPOS)): return
            if key == "9": self._set("IDLE"); return
            if key == ENC_PUSH:
                self.settings.set("update_repo", self.REPOS[s.index])
                self._set("IDLE")
            return
        if s.screen == "DEV_CHANNEL_SELECT":
            if self._move(key, len(self.UPDATE_CHANNELS)): return
            if key == "9": self._set("IDLE"); return
            if key == ENC_PUSH:
                self.settings.set("update_channel", self.UPDATE_CHANNELS[s.index][0])
                self._set("IDLE")
            return
        if s.screen == "DEV_SCRIPT_SELECT":
            if self._move(key, max(1, len(s.dev_scripts)), wrap=False): return
            if key == "9": self._set("IDLE"); return
            if key == ENC_PUSH and s.dev_scripts: self._run_custom_script(s.dev_scripts[s.index])
            return
        if s.screen == "DEV_MESSAGE":
            if key in ("9", ENC_PUSH): self._set("IDLE")
            return
        if s.screen == "SYSTEM_CONFIRM":
            if key == "9": self._set("MENU", 9)
            elif key == ENC_PUSH: self.running = False; self._set("SHUTDOWN")
            return
        if s.screen in {"LOCATION", "ABOUT", "TIME_SYNC"}:
            if key in ("9", ENC_PUSH): self._set("MENU")
            return
        if s.screen == "ERROR" and key in ("9", ENC_PUSH):
            self._set(s.return_screen)
            return
        if s.screen in {"WIFI_SETUP", "DRIVER_SELECT", "IFACE_SELECT"} and key in ("9", ENC_PUSH):
            # All three are only reachable via Dev Tools codes (5000/5555/9600) — back always goes to IDLE.
            self._set("IDLE")
            return
        if s.screen in {"ALIGN_SMART_NA", "FN2_EASTER"} and key in ("9", ENC_PUSH):
            self._set("ALIGN_CHOOSE" if s.screen == "ALIGN_SMART_NA" else "IDLE")

    def _speed(self, return_screen: str) -> None:
        self.state.return_screen = return_screen; self._set("SPEED_ADJUST")

    def _select_menu(self) -> None:
        s = self.state
        if s.index == 0: self._set("TIME_SYNC")
        elif s.index == 1: self._set("ALIGN_CHOOSE")
        elif s.index == 2:
            if self._truth(self.runtime.get("parked", "false")): self.runtime.set("parked", "false"); self._set("IDLE")
            else: self._set("PARK_CONFIRM")
        elif s.index == 3:
            s.access_code = f"{random.SystemRandom().randrange(100000, 1000000)}"
            s.access_expires = self.clock() + 600; s.access_last_remaining = -1
            self.codes.issue(s.access_code, 600); self._set("WIFI_ACCESS")
        elif s.index == 4: self._set("LOCATION")
        elif s.index == 5: self._set("BACKLIGHT")
        elif s.index == 6:
            current = self.settings.get("language", DEFAULT_LANGUAGE)
            codes = [code for _, code in LANGUAGES]
            self._set("LANGUAGE", codes.index(current) if current in codes else 0)
        elif s.index == 7:
            current = self.settings.get("ui_theme", DEFAULT_THEME)
            keys = [theme.key for theme in THEMES]
            self._set("THEME", keys.index(current) if current in keys else 0)
        elif s.index == 8: s.digits = []; s.digit_value = 0; self._set("SUDO_SET")
        elif s.index == 9: self._set("SYSTEM_CONFIRM")
        else: self._set("ABOUT")

    def _open_catalog(self) -> None:
        s = self.state
        if s.index == 0: s.text = ""; s.t9_key = None; self._set("TYPE")
        elif s.index == 1: self._set("CUSTOM_CATALOGS")
        else:
            s.catalog_id = None; s.catalog_title = self.CATALOG[s.index]
            s.list_items = list(BUILTIN_CATALOGS[s.catalog_title]); self._set("LIST")

    def _local_objects(self) -> list[SearchResult]:
        objects = [item for values in BUILTIN_CATALOGS.values() for item in values]
        for catalog in self.catalogs.list_catalogs():
            objects.extend(SearchResult(i["name"], i["ra"], i["dec"], i["type"], i["source"]) for i in self.catalogs.list_items(catalog["id"]))
        return objects

    def _type(self, key: str) -> None:
        s = self.state
        if key == FN2: self._set("CATALOG_MENU"); return
        if key == ENC_PUSH and s.text:
            s.results, s.online_available = self.search.search(s.text, self._local_objects()); self._set("RESULTS"); return
        if key == BKSP: s.text = s.text[:-1]; s.t9_key = None; self.render(); return
        if key == "0": s.text += "0"; s.t9_key = None; self.render(); return
        if key not in T9: return
        now = self.clock(); letters = T9[key]
        if s.t9_key == key and now - s.t9_at <= 0.65 and s.text:
            s.t9_pos = (s.t9_pos + 1) % len(letters); s.text = s.text[:-1] + letters[s.t9_pos]
        else:
            s.t9_key = key; s.t9_pos = 0; s.text += letters[0]
        s.t9_at = now; self.render()

    def _confirm_slew(self, obj: SearchResult, return_screen: str) -> None:
        self.state.selected = obj; self.state.return_screen = return_screen
        if not self._truth(self.runtime.get("aligned", "false")) or (obj.alt is not None and obj.alt < 0): self._set("WARN")
        else: self._begin_slew()

    def _begin_slew(self) -> None:
        obj = self.state.selected
        if obj is None or not obj.ra or not obj.dec:
            self.state.error_message = "Missing RA / Dec"
            logger.warning("Cannot slew without both RA and Dec coordinates")
            self._set("ERROR")
            return
        try:
            self.indi.goto(obj.ra, obj.dec)
        except (NotImplementedError, ConnectionError) as exc:
            logger.error("INDI-002 goto failed: %s", exc)
            self._set(self.state.return_screen)
            return
        self.state.transition_at = self.clock() + 1.5
        self._set("SLEW")

    def _digits(self, key: str) -> None:
        s = self.state
        if key == "9": self._set("IDLE" if s.screen == "DEVTOOLS" else "MENU"); return
        if key == ENC_UP: s.digit_value = (s.digit_value + 1) % 10; self.render(); return
        if key == ENC_DOWN: s.digit_value = (s.digit_value - 1) % 10; self.render(); return
        if key == ENC_PUSH:
            s.digits.append(s.digit_value); s.digit_value = 0
            if len(s.digits) == 4:
                code = "".join(map(str, s.digits))
                if s.screen == "SUDO_SET":
                    self.settings.set_password("sudo_password", code)
                    self._set("MENU")
                else:
                    self._devtools_code(code)
            else: self.render()

    def _devtools_code(self, code: str) -> None:
        """Dispatch a 4-digit Dev Tools code — see docs/CODES.md for the
        full table, which must stay in sync with this method."""
        if code == "0000":
            self._set("IDLE")
        elif code == "0022":
            current = self.settings.get("update_repo", self.REPOS[0])
            self._set("DEV_REPO_SELECT", self.REPOS.index(current) if current in self.REPOS else 0)
        elif code == "0033":
            channels = [c for c, _ in self.UPDATE_CHANNELS]
            current = self.settings.get("update_channel", "stable")
            self._set("DEV_CHANNEL_SELECT", channels.index(current) if current in channels else 0)
        elif code == "0044":
            self._devtools_ssh()
        elif code == "1001":
            self._devtools_message(["More INDI drivers", "(camera, focuser, etc.)", "Coming soon"])
        elif code == "1111":
            self._devtools_restart_indi()
        elif code == "1234":
            self._devtools_system_info()
        elif code == "5000":
            self._set("WIFI_SETUP")
        elif code == "5555":
            self._set("DRIVER_SELECT")
        elif code == "9600":
            self._set("IFACE_SELECT")
        elif code == "9955":
            self.state.dev_scripts = self._list_custom_scripts()
            self._set("DEV_SCRIPT_SELECT")
        elif code == "9999":
            self._devtools_message(["Why did the astronomer", "break up with the Moon?", "Because it needed space."])
        elif code == "4200":
            self._devtools_message(["42.", "Now point it at something", "interesting."])
        elif code == "1957":
            self._devtools_message(["1957 — Sputnik beeped.", "This one just tracks quietly."])
        elif code == "0905":
            self._devtools_message(["Protocol 09:", "the code stays free.", "— JapySoft"])
        else:
            self._devtools_message(["Invalid code."])

    def _devtools_restart_indi(self) -> None:
        if self.indi_manager is None:
            self._devtools_message(["INDI restart unavailable", "(no managed indiserver", "in this mode)"])
            return
        try:
            self.indi_manager.restart()
            self._devtools_message(["INDI server restarted"])
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error("Dev Tools: INDI restart failed: %s", exc)
            self._devtools_message(["INDI restart failed", str(exc)[:32]])

    def _devtools_system_info(self) -> None:
        connected = self._truth(self.runtime.get("indi_connected", "false"))
        self._devtools_message([
            "System Info",
            f"{self._local_ip()} · {socket.gethostname()}.local",
            f"Uptime {self._uptime()} · INDI {'up' if connected else 'down'}",
        ])

    @staticmethod
    def _uptime() -> str:
        try:
            with open("/proc/uptime", encoding="ascii") as source:
                seconds = float(source.readline().split()[0])
        except (OSError, ValueError, IndexError):
            return "unknown"
        minutes, _ = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"

    def _devtools_message(self, lines: list[str]) -> None:
        self.state.dev_message = list(lines)
        self._set("DEV_MESSAGE")

    def _devtools_ssh(self) -> None:
        try:
            subprocess.run(["systemctl", "enable", "--now", "ssh"], check=True, timeout=10)
            status = "SSH enabled"
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Dev Tools: could not enable ssh: %s", exc)
            status = "Could not enable SSH"
        self._devtools_message([status, f"{self._local_ip()} · {socket.gethostname()}.local", "user: japyscope"])

    @staticmethod
    def _local_ip() -> str:
        # UDP "connect" never sends a packet — just asks the routing table
        # which local address would be used, which is all we need here.
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "unknown"
        finally:
            sock.close()

    @staticmethod
    def _custom_scripts_dir() -> Path:
        return Path(os.environ.get("JAPYSCOPE_CUSTOM_SCRIPTS_DIR", str(Path.home() / "custom")))

    def _list_custom_scripts(self) -> list[str]:
        try:
            return sorted(p.name for p in self._custom_scripts_dir().glob("*.sh") if p.is_file())
        except OSError:
            return []

    def _run_custom_script(self, name: str) -> None:
        path = self._custom_scripts_dir() / name
        try:
            subprocess.Popen(["/bin/sh", str(path)], cwd=str(path.parent))
            self._devtools_message([f"Running {name}", "", "(started in background)"])
        except OSError as exc:
            logger.error("Dev Tools: failed to run script %s: %s", name, exc)
            self._devtools_message([f"Failed to run {name}", str(exc)[:32]])
