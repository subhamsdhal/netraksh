"""Regression tests for backend-scoped edge durable outboxes."""
from datetime import datetime

import httpx

from edge.demo_runner import _runtime_state_paths
from edge.sync.sync_client import SyncClient


class _Response:
    def __init__(self, status_code=201, text=""):
        self.status_code = status_code
        self.text = text


class _Client:
    def __init__(self, responses):
        self._responses = responses

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        return self._responses.pop(0)


def _enqueue_raw(client: SyncClient, sequence_number: int) -> None:
    with client._get_conn() as conn:
        conn.execute(
            """INSERT INTO sync_queue
               (sequence_number, event_id, payload_json, queued_at, status)
               VALUES (?, ?, ?, ?, 'QUEUED')""",
            (
                sequence_number,
                f"event-{sequence_number}",
                '{"evidence_package":{"event_id":"event-%s"}}' % sequence_number,
                datetime.utcnow().isoformat(),
            ),
        )


def test_development_queue_is_physically_preserved_and_not_replayed_to_production(tmp_path, monkeypatch):
    """A new backend scope must never open or drain the prior scope's DB."""
    development = _runtime_state_paths("cam-border-01", "http://127.0.0.1:8443")
    production = _runtime_state_paths("cam-border-01", "https://api.example.test")
    assert development["sync_db_path"] != production["sync_db_path"]

    legacy_client = SyncClient("cam-border-01", "http://127.0.0.1:8443", str(tmp_path / "legacy.db"), "test")
    _enqueue_raw(legacy_client, 101)

    production_client = SyncClient("cam-border-01", "https://api.example.test", str(tmp_path / "production.db"), "test")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _Client([]))

    assert production_client.sync_once() == {"status": "nothing_to_sync", "queued": 0}
    assert legacy_client.get_queue_depth() == 1


def test_production_queue_remains_durable_across_a_temporary_outage_then_retries(tmp_path, monkeypatch):
    client = SyncClient("cam-border-01", "https://api.example.test", str(tmp_path / "production.db"), "test")
    _enqueue_raw(client, 202)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _Client([_Response(503, "temporary")]))
    first_attempt = client.sync_once()
    assert first_attempt["uploaded"] == 0
    assert client.get_queue_depth() == 1

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _Client([_Response(201)]))
    second_attempt = client.sync_once()
    assert second_attempt["uploaded"] == 1
    assert client.get_queue_depth() == 0
