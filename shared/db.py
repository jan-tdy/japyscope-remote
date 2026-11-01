"""Shared SQLite data layer used by both the firmware app and the Web UI.

A single SQLite file (default: /var/lib/japyscope/japyscope.db on the device,
overridable via the JAPYSCOPE_DB_PATH env var) is the source of truth for:

- user-created catalogs (the controller's "My Catalog" screen shows one of
  these per catalog; the Web UI creates/edits them) — NOT the built-in
  reference catalogs (Basic/Messier/NGC/Caldwell), which are static data
  shipped with the firmware, not stored here.
- settings (location, timezone, park position, sudo password hash, ...)
- runtime state written by the firmware app and read by the Web UI
  (aligned, parked, current RA/Dec/Alt/Az, ...)
- Web UI access codes shown on the controller and entered on the login page

Kept as plain stdlib sqlite3 (no ORM) — this runs on a Pi Zero W, and the
schema is small enough that an ORM would add dependency weight for no
benefit.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("JAPYSCOPE_DB_PATH", "/var/lib/japyscope/japyscope.db")
PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 210_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    catalog_id INTEGER NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    ra TEXT NOT NULL DEFAULT '',
    dec TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'webui',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_items_catalog_id ON catalog_items(catalog_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS access_codes (
    code TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

-- Offline outbox for observed-target events headed to Visual Astro's
-- telescope-ingest Edge Function (see shared/visual_astro.py). One row per
-- closed, above-threshold observing event not yet confirmed delivered.
CREATE TABLE IF NOT EXISTS telescope_event_outbox (
    event_id TEXT PRIMARY KEY,
    object_name TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL NOT NULL,
    ra TEXT NOT NULL DEFAULT '',
    dec TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_telescope_event_outbox_created_at ON telescope_event_outbox(created_at);

-- A single in-flight Visual Astro pairing attempt (Web UI Connectors page).
-- Singleton row (id = 1): only one pairing can be in progress at a time --
-- starting a new one overwrites whatever the previous attempt left behind.
CREATE TABLE IF NOT EXISTS telescope_pairing (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    pairing_id TEXT NOT NULL,
    code TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""

# Independently overridable hardware components during bring-up (see the
# hw_sim_* settings below) — shared between firmware/main.py (which reads
# them to pick real vs. simulated backends) and webui/app.py's Settings
# page (which lets you flip them without needing firmware's own heavier
# imports, e.g. RPi.GPIO attempts). "joystick"'s hw_sim flag only matters
# when the accessory is actually enabled — see joystick_enabled below.
HARDWARE_COMPONENTS = ("keypad", "encoder", "display", "backlight", "mount", "joystick")

DEFAULT_SETTINGS = {
    "latitude": "0.0",
    "longitude": "0.0",
    "elevation_m": "0",
    "timezone": "UTC",
    "park_mode": "zenith",  # zenith | home | custom
    "park_alt": "45",
    "park_az": "180",
    "backlight_r": "1",  # index into ("Off","Med","High")
    "backlight_g": "0",
    "backlight_b": "0",
    "language": "en",  # see firmware/ui/i18n.py LANGUAGES for supported codes
    "update_repo": "jan-tdy/japyscope-remote",  # OTA source repo — Dev Tools code 0022
    "update_channel": "stable",  # stable | prerelease — Dev Tools code 0033
    # rj12 | bluetooth — Dev Tools code 9600. "bluetooth" assumes the mount
    # has already been paired via install/bluetooth-mount.sh (see docs/
    # WIRING.md); this setting only records which interface the device
    # should use, it doesn't perform the pairing itself.
    "mount_interface": "rj12",
    # Whether the external joystick module (docs/WIRING.md, firmware/hal/
    # input/joystick.py) is physically connected at all. Unlike the other
    # HARDWARE_COMPONENTS, the joystick is a genuinely optional accessory —
    # defaults to "0" so a fresh install with no joystick wired up never
    # tries to open an I2C ADC that isn't there. "1" (Web UI Settings ->
    # Joystick) makes firmware/main.py build a joystick input source, real
    # or simulated per hw_sim_joystick below. --simulate always enables a
    # simulated joystick regardless of this setting, for laptop-only dev.
    "joystick_enabled": "0",
    # Per-component hardware bring-up overrides: "1" = simulated, "0"/absent
    # = real hardware. Independent of --simulate (which forces everything
    # simulated regardless of these) — for wiring up one piece at a time
    # (e.g. keypad on real GPIO while the encoder isn't soldered yet).
    # See firmware/main.py's resolve_simulation_flags().
    "hw_sim_keypad": "0",
    "hw_sim_encoder": "0",
    "hw_sim_display": "0",
    "hw_sim_backlight": "0",
    "hw_sim_mount": "0",
    "hw_sim_joystick": "0",
    # Minimum tracked-on-target duration (seconds) before an observing event
    # is queued for Visual Astro at all -- the "1.42 min (~85s)" default from
    # the JapyScope <-> Visual Astro spec. Applied locally, before an event
    # ever reaches the offline outbox, so a brief mis-slew never costs a
    # queue slot or an upload. Visual Astro's own "pending" confirmation step
    # is a separate, manual decision on top of this -- this setting only
    # keeps obvious noise out of the queue.
    "japyscope_min_duration_seconds": "85",
    # Visual Astro's Supabase project -- overridable in case this device
    # should ever point at a different deployment than the shipped default.
    "visual_astro_project_url": "https://tbmyxbratepxomskzzsq.supabase.co",
    "visual_astro_anon_key": (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRibXl4YnJhdGVweG9tc2t6enNxIiwi"
        "cm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4ODQxOTAsImV4cCI6MjA5MzQ2MDE5MH0."
        "ZwkV2ztqLMMEZlyVfyqVkh6FMKLdrFq7-fojXywj3OM"
    ),
    # visual_astro_device_token is deliberately absent here -- it only
    # exists once a pairing actually completes (see TelescopePairingRepo /
    # webui/app.py's connectors routes), not as an empty default row.
}

# Oldest-first eviction cap for telescope_event_outbox -- a Pi Zero's SD
# card/RAM is small, and a device with no network for a long stretch (or no
# Visual Astro link set up yet) must not grow this table without bound.
MAX_TELESCOPE_EVENT_OUTBOX_ROWS = 2000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return (
        f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}$"
        f"{_encode_base64(salt)}${_encode_base64(digest)}"
    )


def _encode_base64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_text, salt_text, digest_text = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iterations_text)
        if iterations != PASSWORD_ITERATIONS:
            return False
        expected = _decode_base64(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _decode_base64(salt_text), iterations
        )
    except (binascii.Error, TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def connect(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # The firmware app (one long-lived connection) and the Web UI (one
    # short-lived connection per request) both write to the same file
    # concurrently. WAL lets readers proceed while a writer commits, and
    # busy_timeout makes SQLite retry instead of raising "database is
    # locked" immediately when the two do collide on a write.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value)
        )
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'sudo_password'"
    ).fetchone()
    if row is None:
        # Fresh install: a hardcoded default here used to be the literal
        # string "1234" — a well-known password shared by every device,
        # visible to anyone reading this file on GitHub. Generate one at
        # random per device instead, and leave the plaintext in `state`
        # (cleared the moment the owner changes it via Menu -> Sudo
        # Password) so ControllerUI can keep showing it on the Menu screen
        # until then — see MENU rendering in firmware/ui/controller.py.
        default_password = f"{secrets.randbelow(10_000):04d}"
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('sudo_password', ?)",
            (hash_password(default_password),),
        )
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('sudo_password_is_default', '1')"
        )
        conn.execute(
            "INSERT INTO state(key, value, updated_at) VALUES ('sudo_password_first_boot', ?, ?)",
            (default_password, time.time()),
        )
    elif not row["value"].startswith(PASSWORD_SCHEME + "$"):
        conn.execute(
            "UPDATE settings SET value = ? WHERE key = 'sudo_password'",
            (hash_password(row["value"]),),
        )
    conn.commit()


# Initialize schema/default rows once per database path in this process instead of
# repeating DDL and write transactions for every short-lived request session.
_initialized_db_paths: set[str] = set()
_init_db_lock = threading.Lock()


@contextmanager
def db_session(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        normalized_path = os.path.realpath(db_path)
        with _init_db_lock:
            if normalized_path not in _initialized_db_paths:
                init_db(conn)
                _initialized_db_paths.add(normalized_path)
        yield conn
    finally:
        conn.close()


@dataclass
class CatalogItem:
    id: int
    catalog_id: int
    name: str
    ra: str
    dec: str
    type: str
    note: str
    source: str


class CatalogRepo:
    """Multiple named user catalogs (see docs/ARCHITECTURE.md — v0 no longer
    assumes a single flat 'My Catalog')."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_catalogs(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM catalogs ORDER BY name"
        ).fetchall()

    def get_catalog(self, catalog_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM catalogs WHERE id = ?", (catalog_id,)
        ).fetchone()

    def create_catalog(self, name: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO catalogs(name, created_at) VALUES (?, ?)",
            (name, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def rename_catalog(self, catalog_id: int, new_name: str) -> None:
        self.conn.execute(
            "UPDATE catalogs SET name = ? WHERE id = ?", (new_name, catalog_id)
        )
        self.conn.commit()

    def delete_catalog(self, catalog_id: int) -> None:
        self.conn.execute("DELETE FROM catalogs WHERE id = ?", (catalog_id,))
        self.conn.commit()

    def list_items(self, catalog_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM catalog_items WHERE catalog_id = ? ORDER BY name",
            (catalog_id,),
        ).fetchall()

    def get_item(self, item_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM catalog_items WHERE id = ?", (item_id,)
        ).fetchone()

    def add_item(
        self,
        catalog_id: int,
        name: str,
        ra: str = "",
        dec: str = "",
        type_: str = "",
        note: str = "",
        source: str = "webui",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO catalog_items
               (catalog_id, name, ra, dec, type, note, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (catalog_id, name, ra, dec, type_, note, source, time.time()),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_items(
        self,
        catalog_id: int,
        items: list[tuple[str, str, str, str, str]],
        source: str = "import",
    ) -> None:
        created_at = time.time()
        with self.conn:
            self.conn.executemany(
                """INSERT INTO catalog_items
                   (catalog_id, name, ra, dec, type, note, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (catalog_id, name, ra, dec, type_, note, source, created_at)
                    for name, ra, dec, type_, note in items
                ],
            )

    def delete_item(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM catalog_items WHERE id = ?", (item_id,))
        self.conn.commit()

    def update_item(
        self,
        item_id: int,
        name: str,
        ra: str = "",
        dec: str = "",
        type_: str = "",
        note: str = "",
    ) -> None:
        self.conn.execute(
            """UPDATE catalog_items
               SET name = ?, ra = ?, dec = ?, type = ?, note = ?
               WHERE id = ?""",
            (name, ra, dec, type_, note, item_id),
        )
        self.conn.commit()


class SettingsRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def set_password(self, key: str, password: str) -> None:
        self.set(key, hash_password(password))

    def verify_password(self, key: str, password: str) -> bool:
        encoded = self.get(key)
        return encoded is not None and verify_password(password, encoded)

    def all(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.conn.execute("SELECT * FROM settings")}


class StateRepo:
    """Runtime status written by the firmware app, read (never written) by
    the Web UI. Deliberately separate from `settings`, which is user-editable
    configuration."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state(key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, time.time()),
        )
        self.conn.commit()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def delete(self, key: str) -> None:
        self.conn.execute("DELETE FROM state WHERE key = ?", (key,))
        self.conn.commit()

    def all(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.conn.execute("SELECT * FROM state")}


class AccessCodeRepo:
    """Dynamic Web UI login codes shown on the controller (Menu -> Wi-Fi /
    Web Access). Deliberately low-security (a deterrent, not a real auth
    system) per the mockup/memory."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def issue(self, code: str, ttl_seconds: int) -> None:
        now = time.time()
        self.purge_expired()
        self.conn.execute(
            "INSERT OR REPLACE INTO access_codes(code, created_at, expires_at) VALUES (?, ?, ?)",
            (code, now, now + ttl_seconds),
        )
        self.conn.commit()

    def is_valid(self, code: str) -> bool:
        row = self.conn.execute(
            "SELECT expires_at FROM access_codes WHERE code = ?", (code,)
        ).fetchone()
        return bool(row) and row["expires_at"] >= time.time()

    def consume(self, code: str) -> bool:
        """Atomically validate and remove a one-time login code."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            row = self.conn.execute(
                "SELECT expires_at FROM access_codes WHERE code = ?", (code,)
            ).fetchone()
            valid = bool(row) and row["expires_at"] >= time.time()
            if valid:
                self.conn.execute("DELETE FROM access_codes WHERE code = ?", (code,))
            self.conn.commit()
            return valid
        except Exception:
            self.conn.rollback()
            raise

    def purge_expired(self) -> None:
        self.conn.execute("DELETE FROM access_codes WHERE expires_at < ?", (time.time(),))
        self.conn.commit()


class TelescopeEventOutboxRepo:
    """Offline outbox for observed-target events bound for Visual Astro.

    Written by `firmware.ui.controller.ControllerUI`'s tick loop (one row
    per closed, above-threshold event); drained by the background flush
    loop in `firmware.main` via `shared.visual_astro.flush_outbox()`, which
    deletes each row only once Visual Astro's telescope-ingest Edge
    Function has actually confirmed it (never on a timeout/connection
    error) -- `event_id` is the idempotency key on both ends, so sending
    the same row twice after an ambiguous failure is harmless.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def enqueue(
        self,
        event_id: str,
        object_name: str,
        started_at: float,
        ended_at: float,
        ra: str = "",
        dec: str = "",
    ) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO telescope_event_outbox
               (event_id, object_name, started_at, ended_at, ra, dec, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, object_name, started_at, ended_at, ra, dec, time.time()),
        )
        self.conn.commit()
        self._evict_overflow()

    def _evict_overflow(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) AS c FROM telescope_event_outbox").fetchone()["c"]
        overflow = count - MAX_TELESCOPE_EVENT_OUTBOX_ROWS
        if overflow <= 0:
            return
        self.conn.execute(
            """DELETE FROM telescope_event_outbox WHERE event_id IN (
                   SELECT event_id FROM telescope_event_outbox ORDER BY created_at ASC LIMIT ?
               )""",
            (overflow,),
        )
        self.conn.commit()
        logger.warning("telescope_event_outbox exceeded %d rows -- dropped %d oldest", MAX_TELESCOPE_EVENT_OUTBOX_ROWS, overflow)

    def list_batch(self, limit: int = 25) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM telescope_event_outbox ORDER BY created_at ASC LIMIT ?", (limit,)
        ).fetchall()

    def delete_many(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        self.conn.executemany(
            "DELETE FROM telescope_event_outbox WHERE event_id = ?", [(event_id,) for event_id in event_ids]
        )
        self.conn.commit()

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM telescope_event_outbox").fetchone()["c"]


class TelescopePairingRepo:
    """The single in-flight Visual Astro pairing attempt, if any (Web UI
    Connectors page). A fresh `start()` replaces whatever attempt came
    before it -- only one code can be on screen at a time."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def start(self, pairing_id: str, code: str, ttl_seconds: int) -> None:
        now = time.time()
        self.conn.execute(
            """INSERT INTO telescope_pairing(id, pairing_id, code, created_at, expires_at)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   pairing_id = excluded.pairing_id, code = excluded.code,
                   created_at = excluded.created_at, expires_at = excluded.expires_at""",
            (pairing_id, code, now, now + ttl_seconds),
        )
        self.conn.commit()

    def current(self) -> Optional[sqlite3.Row]:
        row = self.conn.execute("SELECT * FROM telescope_pairing WHERE id = 1").fetchone()
        if row is None or row["expires_at"] < time.time():
            return None
        return row

    def clear(self) -> None:
        self.conn.execute("DELETE FROM telescope_pairing WHERE id = 1")
        self.conn.commit()
