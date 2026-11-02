"""HTTP client for Visual Astro's Supabase Edge Functions.

This is the JapyScope Remote <-> Visual Astro telescope-events integration
(JapyScope Remote spec v1.1): a short-lived pairing code shown on the Web UI
Connectors page is entered in Visual Astro, which issues a device token this
device then uses to upload observing events. Kept as a small, self-contained
client (not folded into webui/app.py) so both the pairing flow (Web UI
request/response cycle) and the background offline-queue flush (firmware's
own thread, see firmware/main.py) share one implementation of the HTTP
contract instead of each reinventing it.

Every endpoint lives at ``https://<project-ref>.functions.supabase.co/<name>``
-- a different host than the project's own REST API
(``https://<project-ref>.supabase.co``), which is what Visual Astro's own
``.env``/Web UI settings store as the "project URL". ``_functions_url()``
below derives the former from the latter.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_URL = "https://tbmyxbratepxomskzzsq.supabase.co"
DEFAULT_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRibXl4YnJhdGVweG9tc2t6enNxIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3Nzc4ODQxOTAsImV4cCI6MjA5MzQ2MDE5MH0.ZwkV2ztqLMMEZlyVfyqVkh6FMKLdrFq7-fojXywj3OM"
)
REQUEST_TIMEOUT_SECONDS = 10
INGEST_BATCH_SIZE = 25


def _functions_url(project_url: str, name: str) -> str:
    ref = project_url.strip().rstrip("/").split("//", 1)[-1].split(".", 1)[0]
    return f"https://{ref}.functions.supabase.co/{name}"


def _iso_utc(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class PairFetchResult:
    status: str  # "pending" | "claimed" | "expired"
    device_token: Optional[str] = None


@dataclass
class PairInitResult:
    pairing_id: str
    code: str


class VisualAstroClient:
    def __init__(self, project_url: str = DEFAULT_PROJECT_URL, anon_key: str = DEFAULT_ANON_KEY):
        self.project_url = project_url
        self.anon_key = anon_key

    def _post(self, name: str, json_body: dict, bearer: Optional[str] = None) -> requests.Response:
        headers = {"apikey": self.anon_key}
        if bearer is not None:
            headers["Authorization"] = f"Bearer {bearer}"
        return requests.post(
            _functions_url(self.project_url, name), json=json_body, headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def pair_init(self) -> Optional[PairInitResult]:
        """Asks Visual Astro to mint a fresh pairing_id + 6-digit code,
        which this call then displays to the user. Both are generated
        server-side, not here -- telescope-pair-init has no auth (the Pi
        has no Visual Astro user session yet), so a value this device
        picked itself and merely told the server about could be
        pre-empted by anyone else calling the same endpoint first."""
        try:
            response = self._post("telescope-pair-init", {})
            if not response.ok:
                return None
            data = response.json()
            pairing_id, code = data.get("pairing_id"), data.get("code")
            if not isinstance(pairing_id, str) or not isinstance(code, str):
                return None
            return PairInitResult(pairing_id=pairing_id, code=code)
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Visual Astro pair-init failed: %s", exc)
            return None

    def pair_fetch(self, pairing_id: str) -> PairFetchResult:
        """Polled from the Connectors page while a pairing code is
        displayed. Any transport failure is reported as still "pending"
        rather than "expired" -- a flaky connection must not make an
        otherwise-valid, still-unclaimed code look dead."""
        try:
            response = self._post("telescope-pair-fetch", {"pairing_id": pairing_id})
            if not response.ok:
                return PairFetchResult(status="expired" if response.status_code == 404 else "pending")
            data = response.json()
            return PairFetchResult(status=data.get("status", "pending"), device_token=data.get("device_token"))
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Visual Astro pair-fetch failed: %s", exc)
            return PairFetchResult(status="pending")

    def revoke(self, device_token: str) -> bool:
        try:
            response = self._post("telescope-revoke", {}, bearer=device_token)
            return response.ok
        except requests.RequestException as exc:
            logger.warning("Visual Astro revoke failed: %s", exc)
            return False

    def ingest(self, device_token: str, events: list[dict]) -> bool:
        try:
            response = self._post("telescope-ingest", {"events": events}, bearer=device_token)
            return response.ok
        except requests.RequestException as exc:
            logger.warning("Visual Astro ingest failed: %s", exc)
            return False


def flush_outbox(conn, client: VisualAstroClient, device_token: str, batch_size: int = INGEST_BATCH_SIZE) -> int:
    """Sends one batch of queued events and deletes them from the outbox on
    success. Returns how many rows were sent (0 means either the outbox was
    empty or the upload failed -- callers distinguish by checking the
    outbox's own row count if they care which)."""
    from shared.db import TelescopeEventOutboxRepo  # local import: avoids a hard import-time dependency for callers that only need the HTTP client

    repo = TelescopeEventOutboxRepo(conn)
    rows = repo.list_batch(batch_size)
    if not rows:
        return 0
    events = []
    for row in rows:
        event: dict = {
            "event_id": row["event_id"],
            "object_name": row["object_name"],
            "started_at": _iso_utc(row["started_at"]),
            "ended_at": _iso_utc(row["ended_at"]),
        }
        if row["ra"]:
            event["ra"] = row["ra"]
        if row["dec"]:
            event["dec"] = row["dec"]
        events.append(event)
    if not client.ingest(device_token, events):
        return 0
    repo.delete_many([row["event_id"] for row in rows])
    return len(rows)
