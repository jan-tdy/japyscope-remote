import io
import re
import subprocess

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


def test_diagnostics_reports_real_failure_instead_of_lying(tmp_path, monkeypatch):
    from webui import app as app_module

    def fake_run(command, **kwargs):
        if command[0] == "sudo":
            return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="sudo: a password is required\n")
        return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="Failed to open system journal: Permission denied\n")

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    client, _ = authenticated_client(tmp_path)
    response = client.get("/diagnostics?unit=app&lines=50")
    assert response.status_code == 200
    assert b"Log retrieval failed" in response.data
    assert b"password is required" in response.data


def test_diagnostics_requests_reverse_order_and_displays_oldest_first(tmp_path, monkeypatch):
    # journalctl's -n combined with multiple -u filters is unreliable on
    # some systemd versions and can return the OLDEST N matches instead of
    # the newest N. --reverse forces a tail-anchored seek (guaranteed
    # newest N); the app then flips the lines back to the usual
    # oldest-on-top reading order.
    from webui import app as app_module

    def fake_run(command, **kwargs):
        assert "--reverse" in command
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=(
                "Sep 20 12:00:03 pi japyscope-app[1]: third\n"
                "Sep 20 12:00:02 pi japyscope-app[1]: second\n"
                "Sep 20 12:00:01 pi japyscope-app[1]: first\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    client, _ = authenticated_client(tmp_path)
    response = client.get("/diagnostics?unit=app&lines=50")
    body = response.data.decode("utf-8")
    assert body.index("first") < body.index("second") < body.index("third")


def test_diagnostics_uses_sudo_fallback_output(tmp_path, monkeypatch):
    from webui import app as app_module

    def fake_run(command, **kwargs):
        if command[0] == "sudo":
            return subprocess.CompletedProcess(
                command, returncode=0, stdout="Sep 20 12:00:00 pi japyscope-app[1]: started\n", stderr=""
            )
        return subprocess.CompletedProcess(command, returncode=1, stdout="", stderr="Failed to open system journal: Permission denied\n")

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)
    client, _ = authenticated_client(tmp_path)
    response = client.get("/diagnostics?unit=app&lines=50")
    assert response.status_code == 200
    assert b"japyscope-app[1]: started" in response.data
    assert b"No log entries found" not in response.data


def test_catalog_import_template_download(tmp_path):
    client, _ = authenticated_client(tmp_path)
    response = client.get("/catalog/import-template")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    assert response.data.decode("utf-8").splitlines()[0] == "name,ra,dec,type,note"


def test_system_update_action_starts_update_service(tmp_path):
    triggered = []
    db_path = str(tmp_path / "web.db")
    with db_session(db_path) as conn: AccessCodeRepo(conn).issue("123456", 60)
    app = create_app(db_path, wifi_configurator=lambda *_: None, action_runner=triggered.append)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.get("/")
    client.post("/", data={"code": "123456", "csrf_token": csrf(client)})
    response = client.post(
        "/system", data={"csrf_token": csrf(client), "action": "update-now"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert triggered == [["sudo", "systemctl", "start", "japyscope-update.service"]]


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

