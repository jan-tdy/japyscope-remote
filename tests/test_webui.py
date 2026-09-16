from shared.db import AccessCodeRepo, CatalogRepo, db_session
from webui.app import create_app


def authenticated_client(tmp_path):
    db_path = str(tmp_path / "web.db")
    with db_session(db_path) as conn: AccessCodeRepo(conn).issue("123456", 60)
    app = create_app(db_path, wifi_configurator=lambda *_: None, action_runner=lambda *_: None)
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.post("/", data={"code": "123456"})
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


def test_login_locks_after_five_failures(tmp_path):
    app = create_app(str(tmp_path / "lock.db"))
    app.config.update(TESTING=True)
    client = app.test_client()
    for _ in range(4): assert client.post("/", data={"code": "000000"}).status_code == 401
    assert client.post("/", data={"code": "000000"}).status_code == 429
