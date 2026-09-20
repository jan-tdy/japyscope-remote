import io
import re

from shared.db import AccessCodeRepo, CatalogRepo, db_session
from webui.app import create_app


def test_gen_code_cli_requires_dev_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("JAPYSCOPE_DEV_MODE", raising=False)
    app = create_app(str(tmp_path / "web.db"))
    result = app.test_cli_runner().invoke(args=["gen-code"])
    assert result.exit_code != 0  # command doesn't exist without dev mode


def test_gen_code_cli_issues_a_working_code(tmp_path, monkeypatch):
    monkeypatch.setenv("JAPYSCOPE_DEV_MODE", "1")
    db_path = str(tmp_path / "web.db")
    app = create_app(db_path)
    result = app.test_cli_runner().invoke(args=["gen-code"])
    assert result.exit_code == 0
    match = re.search(r"access code: (\d{6})", result.output)
    assert match, result.output
    with db_session(db_path) as conn:
        assert AccessCodeRepo(conn).is_valid(match.group(1))


def authenticated_client(tmp_path):
    db_path = str(tmp_path / "web.db")
    with db_session(db_path) as conn: AccessCodeRepo(conn).issue("123456", 60)
    app = create_app(db_path, wifi_configurator=lambda *_: None, action_runner=lambda *_: None)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.get("/")
    response = client.post("/", data={"code": "123456", "csrf_token": csrf(client)})
    assert response.status_code == 302
    return client, db_path


def csrf(client):
    with client.session_transaction() as session: return session["csrf_token"]


def test_status_live_view_is_opt_in(tmp_path):
    client, _ = authenticated_client(tmp_path)
    response = client.get("/status")
    assert b"Start live view" in response.data
    assert b'http-equiv="refresh"' not in response.data
    response = client.post("/status", data={"csrf_token": csrf(client), "action": "start"}, follow_redirects=True)
    assert b"Stop live view" in response.data
    assert b'http-equiv="refresh"' in response.data


def test_health_check_does_not_require_login(tmp_path):
    app = create_app(str(tmp_path / "health.db")); app.config.update(TESTING=True)
    response = app.test_client().get("/healthz")
    assert response.status_code == 200 and response.json == {"status": "ok"}


def test_multi_catalog_create_and_item_add(tmp_path):
    client, db_path = authenticated_client(tmp_path)
    client.post("/catalog/create", data={"csrf_token": csrf(client), "name": "Variables"})
    with db_session(db_path) as conn: catalog_id = CatalogRepo(conn).list_catalogs()[0]["id"]
    client.post(f"/catalog/{catalog_id}/items", data={"csrf_token": csrf(client), "name": "V445 Her", "ra": "18:24"})
    response = client.get("/catalog")
    assert b"Variables" in response.data and b"V445 Her" in response.data


def test_duplicate_catalog_rename_returns_message(tmp_path):
    client, db_path = authenticated_client(tmp_path)
    with db_session(db_path) as conn:
        repo = CatalogRepo(conn); first = repo.create_catalog("First"); repo.create_catalog("Second")
    response = client.post(
        f"/catalog/{first}/rename",
        data={"csrf_token": csrf(client), "name": "Second"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"already exists" in response.data


def test_invalid_csv_import_is_atomic(tmp_path):
    client, db_path = authenticated_client(tmp_path)
    with db_session(db_path) as conn: catalog_id = CatalogRepo(conn).create_catalog("Import")
    response = client.post(
        f"/catalog/{catalog_id}/import",
        data={
            "csrf_token": csrf(client),
            "file": (io.BytesIO(b"name,ra\nValid,12:00\nBad,1,2,3,4,5\n"), "objects.csv"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    with db_session(db_path) as conn: assert CatalogRepo(conn).list_items(catalog_id) == []


def test_malformed_csv_import_is_atomic(tmp_path):
    client, db_path = authenticated_client(tmp_path)
    with db_session(db_path) as conn: catalog_id = CatalogRepo(conn).create_catalog("Import")
    response = client.post(
        f"/catalog/{catalog_id}/import",
        data={
            "csrf_token": csrf(client),
            "file": (io.BytesIO(b'name,ra\nValid,12:00\n"unterminated\n'), "objects.csv"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    with db_session(db_path) as conn: assert CatalogRepo(conn).list_items(catalog_id) == []


def test_setup_requires_csrf(tmp_path):
    configured = []
    app = create_app(
        str(tmp_path / "setup.db"),
        wifi_configurator=lambda ssid, password: configured.append((ssid, password)),
    )
    app.config.update(TESTING=True)
    client = app.test_client()
    assert client.post("/setup", data={"ssid": "Home", "password": "password"}).status_code == 400
    client.get("/setup")
    response = client.post(
        "/setup",
        data={"csrf_token": csrf(client), "ssid": "Home", "password": "password"},
    )
    assert response.status_code == 200
    assert configured == [("Home", "password")]


def test_login_requires_csrf(tmp_path):
    app = create_app(str(tmp_path / "csrf.db"))
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.post("/", data={"code": "123456"})
    assert response.status_code == 400


def test_login_locks_after_five_failures(tmp_path):
    app = create_app(str(tmp_path / "lock.db"))
    app.config.update(TESTING=True)
    client = app.test_client()
    client.get("/")
    token = csrf(client)
    for _ in range(4): assert client.post("/", data={"code": "000000", "csrf_token": token}).status_code == 401
    assert client.post("/", data={"code": "000000", "csrf_token": token}).status_code == 429


def test_diagnostics_page_renders_logs_or_fallback(tmp_path, monkeypatch):
    client, _ = authenticated_client(tmp_path)
    response = client.get("/diagnostics?unit=app&lines=50")
    assert response.status_code == 200
    assert b"Diagnostics" in response.data
    assert b"journal" in response.data.lower()


def test_api_telemetry_endpoint(tmp_path):
    client, _ = authenticated_client(tmp_path)
    response = client.get("/api/telemetry")
    assert response.status_code == 200
    data = response.get_json()
    assert "cpu_temp" in data
    assert "cpu_load" in data
    assert "ram_usage" in data
    assert "disk_usage" in data
    assert "uptime" in data

