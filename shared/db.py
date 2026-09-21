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
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

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
"""

# Independently overridable hardware components during bring-up (see the
# hw_sim_* settings below) — shared between firmware/main.py (which reads
# them to pick real vs. simulated backends) and webui/app.py's Settings
# page (which lets you flip them without needing firmware's own heavier
# imports, e.g. RPi.GPIO attempts).
HARDWARE_COMPONENTS = ("keypad", "encoder", "display", "backlight", "mount")

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
}


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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
        conn.execute(
            "INSERT INTO settings(key, value) VALUES ('sudo_password', ?)",
            (hash_password("1234"),),
        )
    elif not row["value"].startswith(PASSWORD_SCHEME + "$"):
        conn.execute(
            "UPDATE settings SET value = ? WHERE key = 'sudo_password'",
            (hash_password(row["value"]),),
        )
    conn.commit()


@contextmanager
def db_session(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        init_db(conn)
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

    def purge_expired(self) -> None:
        self.conn.execute("DELETE FROM access_codes WHERE expires_at < ?", (time.time(),))
        self.conn.commit()
