"""
Phase 7.4.5: Sync Queue Head-of-Line Blocking Regression Test
"""
import pytest
from datetime import datetime
from edge.sync.sync_client import SyncClient

class MockResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

class MockClient:
    def __init__(self, responses):
        self.responses = responses
        self.posts = []
    
    def post(self, url, content=None, data=None, files=None, headers=None):
        self.posts.append(url)
        return self.responses.pop(0) if self.responses else MockResponse(201)
    
    def __enter__(self):
        return self
        
    def __exit__(self, *args):
        pass

def test_sync_queue_safe_4xx_handling(tmp_path, monkeypatch):
    """
    Test that a 4xx validation failure permanently fails the payload and
    does NOT block subsequent valid payloads from being uploaded.
    """
    db_path = tmp_path / "sync.db"
    client = SyncClient("edge-1", "http://localhost", str(db_path), auth_token="dummy-token")
    
    with client._get_conn() as conn:
        conn.execute(
            """INSERT INTO sync_queue (sequence_number, event_id, severity_rank, payload_json, status, queued_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (4429, "evt-4429", 0, '{"evidence_package": {"event_id": "evt-4429"}}', "QUEUED", datetime.utcnow().isoformat())
        )
        conn.execute(
            """INSERT INTO sync_queue (sequence_number, event_id, severity_rank, payload_json, status, queued_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (4430, "evt-4430", 0, '{"evidence_package": {"event_id": "evt-4430"}}', "QUEUED", datetime.utcnow().isoformat())
        )
        conn.execute(
            """INSERT INTO sync_queue (sequence_number, event_id, severity_rank, payload_json, status, queued_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (4431, "evt-4431", 0, '{"evidence_package": {"event_id": "evt-4431"}}', "QUEUED", datetime.utcnow().isoformat())
        )
        conn.execute(
            """INSERT INTO sync_queue (sequence_number, event_id, severity_rank, payload_json, status, queued_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (4432, "evt-4432", 0, '{"evidence_package": {"event_id": "evt-4432"}}', "QUEUED", datetime.utcnow().isoformat())
        )
        
    import httpx
    mock_responses = [
        MockResponse(422, "Unprocessable Entity"),
        MockResponse(201),
        MockResponse(503, "Service Unavailable"),
    ]
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: MockClient(mock_responses))
    
    result = client.sync_once()
    
    assert result["uploaded"] == 1
    assert result["failed"] == 2
    
    with client._get_conn() as conn:
        r_4429 = conn.execute("SELECT status FROM sync_queue WHERE sequence_number=4429").fetchone()[0]
        r_4430 = conn.execute("SELECT status FROM sync_queue WHERE sequence_number=4430").fetchone()[0]
        r_4431 = conn.execute("SELECT status FROM sync_queue WHERE sequence_number=4431").fetchone()[0]
        r_4432 = conn.execute("SELECT status FROM sync_queue WHERE sequence_number=4432").fetchone()[0]
        
    assert r_4429 == "FAILED"   # Permanent failure
    assert r_4430 == "SYNCED"   # Success despite previous item failing
    assert r_4431 == "QUEUED"   # Transient failure retains QUEUED to retry
    assert r_4432 == "QUEUED"   # Never reached, remains QUEUED
