import os
import tempfile

import pytest

from shared.db import TelescopeEventOutboxRepo, connect, init_db
from shared.visual_astro import PairFetchResult, VisualAstroClient, _functions_url, flush_outbox, sha256_hex


@pytest.fixture
def conn():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    c = connect(path)
    init_db(c)
    yield c
    c.close()
    os.unlink(path)


class FakeResponse:
    def __init__(self, ok=True, status_code=200, json_data=None):
        self.ok = ok
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def test_functions_url_derives_functions_host_from_project_url():
    assert _functions_url("https://abc123.supabase.co", "telescope-ingest") == "https://abc123.functions.supabase.co/telescope-ingest"


def test_sha256_hex_is_stable():
    assert sha256_hex("123456") == sha256_hex("123456")
    assert sha256_hex("123456") != sha256_hex("654321")


def test_pair_init_posts_hash_not_plaintext(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResponse(ok=True)

    monkeypatch.setattr("shared.visual_astro.requests.post", fake_post)
    client = VisualAstroClient(project_url="https://abc123.supabase.co", anon_key="anon-key")
    assert client.pair_init("pairing-1", "123456") is True
    assert captured["url"] == "https://abc123.functions.supabase.co/telescope-pair-init"
    assert captured["json"]["pairing_id"] == "pairing-1"
    assert captured["json"]["code_hash"] == sha256_hex("123456")
    assert "123456" not in captured["json"].values()
    assert captured["headers"]["apikey"] == "anon-key"
    assert "Authorization" not in captured["headers"]


def test_pair_fetch_claimed_returns_device_token(monkeypatch):
    monkeypatch.setattr(
        "shared.visual_astro.requests.post",
        lambda *a, **k: FakeResponse(ok=True, json_data={"status": "claimed", "device_token": "tok-abc"}),
    )
    result = VisualAstroClient().pair_fetch("pairing-1")
    assert result == PairFetchResult(status="claimed", device_token="tok-abc")


def test_pair_fetch_network_failure_reports_pending_not_expired(monkeypatch):
    import requests

    def raise_error(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr("shared.visual_astro.requests.post", raise_error)
    result = VisualAstroClient().pair_fetch("pairing-1")
    assert result.status == "pending"


def test_ingest_sends_bearer_token(monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["headers"] = headers
        captured["json"] = json
        return FakeResponse(ok=True)

    monkeypatch.setattr("shared.visual_astro.requests.post", fake_post)
    client = VisualAstroClient()
    assert client.ingest("device-token", [{"event_id": "e1"}]) is True
    assert captured["headers"]["Authorization"] == "Bearer device-token"
    assert captured["json"]["events"] == [{"event_id": "e1"}]


def test_flush_outbox_sends_and_removes_rows_on_success(conn, monkeypatch):
    outbox = TelescopeEventOutboxRepo(conn)
    outbox.enqueue("event-1", "V445Her", started_at=1000.0, ended_at=1100.0, ra="18h", dec="+45d")
    outbox.enqueue("event-2", "AG Dra", started_at=1200.0, ended_at=1260.0)

    sent_events = []

    class StubClient:
        def ingest(self, device_token, events):
            sent_events.extend(events)
            return True

    sent = flush_outbox(conn, StubClient(), "device-token")
    assert sent == 2
    assert outbox.count() == 0
    assert sent_events[0]["event_id"] == "event-1"
    assert sent_events[0]["ra"] == "18h" and sent_events[0]["dec"] == "+45d"
    assert "ra" not in sent_events[1] and "dec" not in sent_events[1]
    assert sent_events[0]["started_at"] == "1970-01-01T00:16:40Z"


def test_flush_outbox_keeps_rows_on_failure(conn):
    outbox = TelescopeEventOutboxRepo(conn)
    outbox.enqueue("event-1", "V445Her", started_at=1000.0, ended_at=1100.0)

    class StubClient:
        def ingest(self, device_token, events):
            return False

    sent = flush_outbox(conn, StubClient(), "device-token")
    assert sent == 0
    assert outbox.count() == 1


def test_flush_outbox_noop_when_empty(conn):
    class StubClient:
        def ingest(self, device_token, events):
            raise AssertionError("should not be called with no queued events")

    assert flush_outbox(conn, StubClient(), "device-token") == 0
