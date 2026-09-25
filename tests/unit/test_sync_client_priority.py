import time
import os
import sqlite3
from datetime import datetime

import pytest

from edge.sync.sync_client import SyncClient, severity_rank
from shared.constants import Severity
from shared.schemas import EvidencePackage


def _package(event_id="evt-1", severity=None) -> EvidencePackage:
    return EvidencePackage(
        event_id=event_id,
        camera_id="cam-1",
        timestamp=datetime.utcnow(),
        zone_id="zone-1",
        detection_class="person",
        confidence=0.8,
        scene_condition="CLEAR_DAY",
        camera_health_state="OK",
        decision_state="DETECTED",
        severity=severity,
    )


def _client(tmp_path, name="sync.db", batch_size=50) -> SyncClient:
    return SyncClient(
        edge_device_id="edge-1",
        backend_url="http://localhost:9999",
        db_path=os.path.join(str(tmp_path), name),
        auth_token="",
        batch_size=batch_size,
    )


class TestSeverityRank:
    def test_high_ranks_above_medium_above_low(self):
        assert severity_rank(Severity.HIGH) > severity_rank(Severity.MEDIUM) > severity_rank(Severity.LOW)

    def test_accepts_plain_string(self):
        assert severity_rank("HIGH") == severity_rank(Severity.HIGH)

    def test_none_ranks_below_every_known_level(self):
        assert severity_rank(None) < severity_rank(Severity.LOW)

    def test_unrecognized_string_ranks_like_none(self):
        assert severity_rank("NOT_A_REAL_SEVERITY") == severity_rank(None)


class TestFetchOrdering:
    def test_high_severity_syncs_before_older_low_severity(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-low", severity=Severity.LOW), sequence_number=1)
        client.enqueue(_package("evt-high", severity=Severity.HIGH), sequence_number=2)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-high", "evt-low"]

    def test_same_severity_breaks_tie_by_sequence_number(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-a", severity=Severity.MEDIUM), sequence_number=5)
        client.enqueue(_package("evt-b", severity=Severity.MEDIUM), sequence_number=3)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-b", "evt-a"]  # lower sequence_number first

    def test_missing_severity_sorts_last(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-none", severity=None), sequence_number=1)
        client.enqueue(_package("evt-low", severity=Severity.LOW), sequence_number=2)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-low", "evt-none"]

    def test_three_tier_ordering_end_to_end(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-low", severity=Severity.LOW), sequence_number=1)
        client.enqueue(_package("evt-high", severity=Severity.HIGH), sequence_number=2)
        client.enqueue(_package("evt-medium", severity=Severity.MEDIUM), sequence_number=3)
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        assert event_ids == ["evt-high", "evt-medium", "evt-low"]


class TestMigration:
    def test_pre_v4_database_gets_severity_rank_column_added(self, tmp_path):
        db_path = os.path.join(str(tmp_path), "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE sync_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence_number INTEGER NOT NULL UNIQUE,
                event_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'QUEUED',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_attempt TEXT,
                error TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO sync_queue (sequence_number, event_id, payload_json, queued_at, status) "
            "VALUES (1, 'legacy-evt', '{}', ?, 'QUEUED')",
            (datetime.utcnow().isoformat(),),
        )
        conn.commit()
        conn.close()

        client = SyncClient(
            edge_device_id="edge-1", backend_url="http://localhost:9999",
            db_path=db_path, auth_token="",
        )
        cols = [row[1] for row in sqlite3.connect(db_path).execute("PRAGMA table_info(sync_queue)").fetchall()]
        assert "severity_rank" in cols

        pending = client._fetch_pending()
        assert len(pending) == 1
        assert pending[0][2] == "legacy-evt"

    def test_migration_is_idempotent(self, tmp_path):
        db_path = os.path.join(str(tmp_path), "sync.db")
        SyncClient(edge_device_id="edge-1", backend_url="http://localhost:9999", db_path=db_path, auth_token="")
        SyncClient(edge_device_id="edge-1", backend_url="http://localhost:9999", db_path=db_path, auth_token="")


class TestQueueDepthUnaffected:
    def test_queue_depth_counts_regardless_of_severity(self, tmp_path):
        client = _client(tmp_path)
        client.enqueue(_package("evt-1", severity=Severity.HIGH), sequence_number=1)
        client.enqueue(_package("evt-2", severity=Severity.LOW), sequence_number=2)
        assert client.get_queue_depth() == 2


class TestBoundedFairness:
    def _update_queued_at(self, client: SyncClient, event_id: str, new_time: str):
        with client._get_conn() as conn:
            conn.execute("UPDATE sync_queue SET queued_at=? WHERE event_id=?", (new_time, event_id))
            
    def test_batch_size_50_allocates_49_priority_and_1_fairness(self, tmp_path):
        client = _client(tmp_path, batch_size=50)
        # Enqueue 50 HIGH severity records
        for i in range(1, 51):
            client.enqueue(_package(f"evt-high-{i}", severity=Severity.HIGH), sequence_number=i)
        
        # Enqueue 1 very old LOW severity record
        client.enqueue(_package("evt-old-low", severity=Severity.LOW), sequence_number=100)
        self._update_queued_at(client, "evt-old-low", "2000-01-01T00:00:00")
        
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        
        # Should contain 49 HIGH and exactly 1 LOW
        assert len(event_ids) == 50
        assert event_ids[-1] == "evt-old-low"
        assert all("evt-high-" in eid for eid in event_ids[:-1])

    def test_fairness_record_not_duplicated_if_already_in_priority(self, tmp_path):
        client = _client(tmp_path, batch_size=5)
        # Queue has only 3 HIGH items
        client.enqueue(_package("evt-1", severity=Severity.HIGH), sequence_number=1)
        client.enqueue(_package("evt-2", severity=Severity.HIGH), sequence_number=2)
        client.enqueue(_package("evt-3", severity=Severity.HIGH), sequence_number=3)
        self._update_queued_at(client, "evt-1", "2000-01-01T00:00:00") # Oldest
        
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        
        # Output should be exactly those 3, without duplicating evt-1
        assert len(event_ids) == 3
        assert event_ids == ["evt-1", "evt-2", "evt-3"]
        
    def test_queued_at_determines_oldest_record_with_sequence_number_tiebreaker(self, tmp_path):
        client = _client(tmp_path, batch_size=2)
        client.enqueue(_package("evt-high-1", severity=Severity.HIGH), sequence_number=1)
        
        # Two old records with exactly the same queued_at timestamp
        client.enqueue(_package("evt-old-100", severity=Severity.LOW), sequence_number=100)
        client.enqueue(_package("evt-old-99", severity=Severity.LOW), sequence_number=99)
        
        t = "2000-01-01T00:00:00"
        self._update_queued_at(client, "evt-old-100", t)
        self._update_queued_at(client, "evt-old-99", t)
        
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        
        # batch_size=2 means 1 priority slot (evt-high-1) and 1 fair slot
        # Fair slot must pick evt-old-99 because of sequence_number ASC tiebreaker
        assert len(event_ids) == 2
        assert event_ids[0] == "evt-high-1"
        assert event_ids[1] == "evt-old-99"

    def test_batch_size_1_preserves_strict_priority(self, tmp_path):
        client = _client(tmp_path, batch_size=1)
        client.enqueue(_package("evt-high", severity=Severity.HIGH), sequence_number=2)
        client.enqueue(_package("evt-old-low", severity=Severity.LOW), sequence_number=1)
        self._update_queued_at(client, "evt-old-low", "2000-01-01T00:00:00")
        
        pending = client._fetch_pending()
        event_ids = [row[2] for row in pending]
        
        # Fair limit should be 0, urgent limit 1. HIGH takes precedence over old LOW.
        assert len(event_ids) == 1
        assert event_ids[0] == "evt-high"

    def test_empty_queue_returns_empty_list(self, tmp_path):
        client = _client(tmp_path, batch_size=50)
        pending = client._fetch_pending()
        assert pending == []

    def test_returned_result_count_never_exceeds_batch_size(self, tmp_path):
        client = _client(tmp_path, batch_size=10)
        for i in range(1, 20):
            client.enqueue(_package(f"evt-{i}", severity=Severity.HIGH), sequence_number=i)
        
        pending = client._fetch_pending()
        assert len(pending) == 10
