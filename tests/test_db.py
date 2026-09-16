import os
import tempfile

import pytest

from shared.db import AccessCodeRepo, CatalogRepo, SettingsRepo, StateRepo, connect, init_db


@pytest.fixture
def conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = connect(path)
    init_db(c)
    yield c
    c.close()
    os.unlink(path)


def test_default_settings_seeded(conn):
    settings = SettingsRepo(conn)
    assert settings.get("timezone") == "UTC"
    assert settings.get("sudo_password") == "1234"


def test_settings_roundtrip(conn):
    settings = SettingsRepo(conn)
    settings.set("timezone", "Europe/Madrid")
    assert settings.get("timezone") == "Europe/Madrid"


def test_multiple_catalogs_are_independent(conn):
    repo = CatalogRepo(conn)
    a = repo.create_catalog("Variable stars")
    b = repo.create_catalog("Alignment references")
    repo.add_item(a, "V445 Her", ra="18h24m11s", dec="+12°09′", type_="star")
    repo.add_item(b, "Chimney reference point", type_="reference")

    assert [row["name"] for row in repo.list_items(a)] == ["V445 Her"]
    assert [row["name"] for row in repo.list_items(b)] == ["Chimney reference point"]
    assert {row["name"] for row in repo.list_catalogs()} == {"Variable stars", "Alignment references"}


def test_deleting_catalog_cascades_items(conn):
    repo = CatalogRepo(conn)
    cat_id = repo.create_catalog("Temp")
    repo.add_item(cat_id, "Object 1")
    repo.delete_catalog(cat_id)
    assert repo.list_items(cat_id) == []


def test_state_is_separate_from_settings(conn):
    state = StateRepo(conn)
    state.set("parked", "true")
    state.set("aligned", "false")
    assert state.get("parked") == "true"
    assert SettingsRepo(conn).get("parked") is None


def test_access_code_expiry(conn):
    codes = AccessCodeRepo(conn)
    codes.issue("123456", ttl_seconds=60)
    assert codes.is_valid("123456") is True
    assert codes.is_valid("000000") is False

    codes.issue("999999", ttl_seconds=-1)  # already expired
    assert codes.is_valid("999999") is False
