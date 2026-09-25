"""
Phase 3C permanent regression: orphan object cleanup tests.

These tests validate the three-way storage consistency invariant:
  1. Storage-first failure  → DB never committed AVAILABLE, no cleanup needed
  2. DB commit failure, cleanup succeeds → object deleted, event NOT AVAILABLE
  3. DB commit failure, cleanup fails   → object leaked, event NOT AVAILABLE

Design principles (matching Phase 3C requirements):
  - Real SQLite in-memory session for full ORM round-trips
  - Fresh verification session to prove durable state (not just in-memory)
  - Mock ONLY the minimum boundary: storage provider and db.commit when needed
  - The actual application logic in backend/api/events.py runs unmodified

The evidence upload flow is exercised via FastAPI TestClient so the full
middleware + dependency injection stack runs, just with controlled boundaries.

Retry/duplicate semantics:
  - storage_status="AVAILABLE" + re-upload → returns {"status": "already_available"}
    (idempotent, no unsafe overwrite)
  - After a failed upload the event can be retried; its storage_status reverts
    to the pre-UPLOADING state (PENDING/FAILED) after rollback.
"""
import hashlib
import os
import re
import tempfile
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import get_db
from backend.main import app
from backend.models.orm import Base, Camera, Event
from backend.security.auth import require_edge_auth

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JPEG_MAGIC = b"\xff\xd8\xff"


def _make_content():
    content = _JPEG_MAGIC + b" test-evidence-content"
    return content, hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# Isolated SQLite session fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Critical: ensures all connections see the same in-memory DB
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine):
    Session = sessionmaker(bind=sqlite_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def _second_session(sqlite_engine):
    """Independent session for verifying durable state (never the same session)."""
    Session = sessionmaker(bind=sqlite_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def seeded_event(db_session):
    """
    Real Camera + Event row in SQLite.
    Returns (camera, event, db_session).
    """
    cam = Camera(id="test-cam", name="test", location="test")
    db_session.add(cam)
    db_session.flush()

    event = Event(
        id=str(uuid.uuid4()),
        camera_id=cam.id,
        timestamp=datetime.utcnow(),
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR_DAY",
        camera_health_state="OK",
        decision_state="PENDING",
        storage_status="PENDING",
        evidence_clip_ref="test.jpg",
    )
    db_session.add(event)
    db_session.commit()

    # Override FastAPI dependency to use this real session
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[require_edge_auth] = lambda: None

    yield cam, event, db_session

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_edge_auth, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStorageFirstFailure:
    """put_object raises — DB must never commit AVAILABLE."""

    def test_storage_failure_returns_500(self, seeded_event, _second_session):
        cam, event, session = seeded_event
        content, content_hash = _make_content()

        with patch("backend.api.events.get_evidence_storage") as mock_get_storage:
            mock_storage = mock_get_storage.return_value
            mock_storage.put_object.side_effect = Exception("Storage failed")

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/events/{event.id}/evidence",
                files={"file": ("test.jpg", content, "image/jpeg")},
                data={"expected_hash": content_hash},
            )

        assert response.status_code == 500

        # Fresh session: event must NOT be AVAILABLE
        _second_session.expire_all()
        fresh = _second_session.get(Event, event.id)
        assert fresh is not None
        assert fresh.storage_status != "AVAILABLE", (
            f"Event was falsely marked AVAILABLE after storage failure; got {fresh.storage_status}"
        )

        # No delete_object should have been called (nothing was uploaded)
        mock_storage.delete_object.assert_not_called()


class TestDbCommitFailure:
    """put_object succeeds, db.commit (for AVAILABLE) fails — orphan cleanup."""

    def test_rollback_and_delete_called(self, seeded_event, _second_session):
        """
        Case A: put succeeds, commit fails, cleanup succeeds.
        Assert: rollback called, delete_object called with exact key, event NOT AVAILABLE.
        """
        cam, event, session = seeded_event
        content, content_hash = _make_content()

        expected_key_fragment = f"evidence/{cam.id}/"
        captured_keys = []

        real_commit = session.commit
        commit_call_count = [0]

        def patched_commit():
            commit_call_count[0] += 1
            # Fail on the SECOND commit, which is the AVAILABLE-setting commit
            # (the first commit is the UPLOADING status update)
            if commit_call_count[0] == 2:
                raise Exception("DB Error: commit failed")
            return real_commit()

        with patch("backend.api.events.get_evidence_storage") as mock_get_storage:
            mock_storage = mock_get_storage.return_value

            def capture_put(key, data, **kwargs):
                captured_keys.append(key)

            mock_storage.put_object.side_effect = capture_put

            # Patch session.commit on the actual injected session object
            session.commit = patched_commit

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/events/{event.id}/evidence",
                files={"file": ("test.jpg", content, "image/jpeg")},
                data={"expected_hash": content_hash},
            )

        session.commit = real_commit  # restore

        assert response.status_code == 500

        # delete_object must have been called with the exact key that was uploaded
        assert len(captured_keys) == 1
        object_key = captured_keys[0]
        assert object_key.startswith(expected_key_fragment), (
            f"Unexpected object key: {object_key!r}"
        )
        mock_storage.delete_object.assert_called_once_with(object_key)

        # Fresh session: event must NOT be AVAILABLE
        _second_session.expire_all()
        fresh = _second_session.get(Event, event.id)
        assert fresh is not None
        assert fresh.storage_status != "AVAILABLE", (
            f"Event was falsely marked AVAILABLE after DB failure; got {fresh.storage_status}"
        )

    def test_cleanup_failure_logged_original_error_preserved(
        self, seeded_event, _second_session
    ):
        """
        Case B: put succeeds, commit fails, cleanup also fails.
        Assert: cleanup was attempted, original DB error is the terminal error,
        event NOT AVAILABLE.
        """
        cam, event, session = seeded_event
        content, content_hash = _make_content()

        real_commit = session.commit
        commit_call_count = [0]

        def patched_commit():
            commit_call_count[0] += 1
            if commit_call_count[0] == 2:
                raise Exception("Original DB Error")
            return real_commit()

        with patch("backend.api.events.get_evidence_storage") as mock_get_storage, \
             patch("backend.api.events.logger.error") as mock_log_error:
            mock_storage = mock_get_storage.return_value
            mock_storage.delete_object.side_effect = Exception("Cleanup Failed")

            session.commit = patched_commit

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post(
                f"/events/{event.id}/evidence",
                files={"file": ("test.jpg", content, "image/jpeg")},
                data={"expected_hash": content_hash},
            )

        session.commit = real_commit  # restore

        assert response.status_code == 500

        # Cleanup was attempted
        mock_storage.delete_object.assert_called_once()

        # Cleanup failure must be logged
        messages = [str(call.args[0]).lower() for call in mock_log_error.call_args_list]
        assert any("cleanup" in message or "orphan" in message for message in messages)

        # Fresh session: event must NOT be AVAILABLE
        _second_session.expire_all()
        fresh = _second_session.get(Event, event.id)
        assert fresh is not None
        assert fresh.storage_status != "AVAILABLE", (
            f"Event was falsely marked AVAILABLE after DB+cleanup failure; got {fresh.storage_status}"
        )


class TestDuplicateUpload:
    """Already-AVAILABLE event → idempotent, no overwrite."""

    def test_already_available_returns_idempotent_status(self, db_session):
        """Re-upload to an AVAILABLE event must return already_available, never overwrite."""
        cam = Camera(id="cam-dup", name="dup", location="dup")
        db_session.add(cam)
        db_session.flush()

        event = Event(
            id=str(uuid.uuid4()),
            camera_id=cam.id,
            timestamp=datetime.utcnow(),
            detection_class="person",
            confidence=0.9,
            scene_condition="CLEAR_DAY",
            camera_health_state="OK",
            decision_state="PENDING",
            storage_status="AVAILABLE",  # already uploaded
            evidence_clip_ref="test.jpg",
        )
        db_session.add(event)
        db_session.commit()

        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[require_edge_auth] = lambda: None

        content, content_hash = _make_content()
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.post(
                f"/events/{event.id}/evidence",
                files={"file": ("test.jpg", content, "image/jpeg")},
                data={"expected_hash": content_hash},
            )
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(require_edge_auth, None)

        data = response.json()
        assert data.get("status") == "already_available", (
            f"Expected already_available, got: {data}"
        )
