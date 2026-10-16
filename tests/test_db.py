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
    state = StateRepo(conn)
    assert settings.get("timezone") == "UTC"
    # A fresh install no longer seeds the well-known "1234" default
    # (jan-tdy/japyscope-remote#35) — it gets a random per-device code
    # instead, left in `state` (not `settings`) so ControllerUI can show
    # it to the owner until they pick their own.
    assert settings.get("sudo_password_is_default") == "1"
    default_password = state.get("sudo_password_first_boot")
    assert default_password is not None
    assert len(default_password) == 4 and default_password.isdigit()
    assert settings.get("sudo_password") != default_password
    assert settings.verify_password("sudo_password", default_password) is True


def test_fresh_install_does_not_use_well_known_default_password(conn):
    # Regression test for jan-tdy/japyscope-remote#35: the seeded password
    # must not be the old hardcoded "1234" that every device used to share.
    settings = SettingsRepo(conn)
    state = StateRepo(conn)
    assert state.get("sudo_password_first_boot") != "1234"
    assert settings.verify_password("sudo_password", "1234") is False


def test_fresh_install_password_is_randomized_per_device():
    fd1, path1 = tempfile.mkstemp(suffix=".db")
    os.close(fd1)
    fd2, path2 = tempfile.mkstemp(suffix=".db")
    os.close(fd2)
    conn1 = connect(path1)
    conn2 = connect(path2)
    try:
        init_db(conn1)
        init_db(conn2)
        password1 = StateRepo(conn1).get("sudo_password_first_boot")
        password2 = StateRepo(conn2).get("sudo_password_first_boot")
        assert password1 != password2
    finally:
        conn1.close()
        conn2.close()
        os.unlink(path1)
        os.unlink(path2)


def test_passwords_are_salted_and_verified(conn):
    settings = SettingsRepo(conn)
    settings.set_password("sudo_password", "9876")
    first = settings.get("sudo_password")
    settings.set_password("sudo_password", "9876")
    assert settings.get("sudo_password") != first
    assert settings.verify_password("sudo_password", "9876") is True
    assert settings.verify_password("sudo_password", "1234") is False


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
