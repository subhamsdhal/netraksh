import json
import uuid
import asyncio
from pathlib import Path

import pytest

from backend.services import video_storage
from backend.services.evidence_storage import EvidenceNotFoundError


class MemoryStorage:
    def __init__(self):
        self.objects = {}

    def put_object(self, key, data, content_type="application/octet-stream"):
        self.objects[key] = bytes(data)

    def put_file(self, key, file_path, content_type="application/octet-stream"):
        self.objects[key] = Path(file_path).read_bytes()

    def get_object(self, key):
        if key not in self.objects:
            raise EvidenceNotFoundError(key)
        return self.objects[key]

    def generate_signed_url(self, key, expires_in=900):
        return f"https://storage.example.test/{key}?signed=yes"

    def object_exists(self, key):
        return key in self.objects


def test_uploaded_video_state_uses_logical_object_keys(monkeypatch, tmp_path):
    storage = MemoryStorage()
    monkeypatch.setattr(video_storage, "get_evidence_storage", lambda: storage)
    session_id = str(uuid.uuid4())
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video-bytes")

    metadata = video_storage.store_uploaded_session(
        camera_id="cam-border-01",
        session_id=session_id,
        source_path=source,
        preview_path=None,
        source_name=f"uploaded_{session_id}.mp4",
        content_type="video/mp4",
    )

    assert metadata["source_object_key"].startswith("video-sessions/cam-border-01/")
    assert "https://" not in json.dumps(metadata)
    active = video_storage.activate_session("cam-border-01", session_id)
    assert active["scenario"] == "paused"
    assert video_storage.get_active_session("cam-border-01")["session_id"] == session_id


def test_active_video_control_updates_without_changing_source(monkeypatch, tmp_path):
    storage = MemoryStorage()
    monkeypatch.setattr(video_storage, "get_evidence_storage", lambda: storage)
    session_id = str(uuid.uuid4())
    source = tmp_path / "source.avi"
    source.write_bytes(b"RIFF-video")
    video_storage.store_uploaded_session(
        camera_id="cam-checkpoint-01",
        session_id=session_id,
        source_path=source,
        preview_path=None,
        source_name=f"uploaded_{session_id}.avi",
        content_type="video/x-msvideo",
    )
    before = video_storage.activate_session("cam-checkpoint-01", session_id)
    after = video_storage.update_active_session(
        "cam-checkpoint-01",
        {"scenario": "normal", "video_time": 12.5, "video_time_updated_at": 99.0},
    )
    assert after["source_object_key"] == before["source_object_key"]
    assert after["scenario"] == "normal"
    assert after["video_time"] == 12.5


def test_get_active_session_returns_none_when_control_object_is_missing(monkeypatch):
    class EmptyStorage:
        def get_object(self, key):
            raise EvidenceNotFoundError(key)

    monkeypatch.setattr(video_storage, "get_evidence_storage", lambda: EmptyStorage())
    assert video_storage.get_active_session("cam-border-01") is None


def test_valid_active_session_rejects_a_control_whose_source_is_missing(monkeypatch):
    storage = MemoryStorage()
    monkeypatch.setattr(video_storage, "get_evidence_storage", lambda: storage)
    session_id = str(uuid.uuid4())
    metadata = {
        "session_id": session_id,
        "camera_id": "cam-checkpoint-01",
        "source_object_key": f"video-sessions/cam-checkpoint-01/{session_id}/source.mp4",
    }
    storage.put_object(video_storage.session_metadata_key("cam-checkpoint-01", session_id), json.dumps(metadata).encode())
    storage.put_object(video_storage.control_key("cam-checkpoint-01"), json.dumps(metadata).encode())

    assert video_storage.get_valid_active_session("cam-checkpoint-01") is None


def test_valid_active_session_accepts_matching_metadata_and_source(monkeypatch):
    storage = MemoryStorage()
    monkeypatch.setattr(video_storage, "get_evidence_storage", lambda: storage)
    session_id = str(uuid.uuid4())
    source_key = f"video-sessions/cam-checkpoint-01/{session_id}/source.mp4"
    metadata = {
        "session_id": session_id,
        "camera_id": "cam-checkpoint-01",
        "source_object_key": source_key,
    }
    storage.put_object(video_storage.session_metadata_key("cam-checkpoint-01", session_id), json.dumps(metadata).encode())
    storage.put_object(video_storage.control_key("cam-checkpoint-01"), json.dumps(metadata).encode())
    storage.put_object(source_key, b"video")

    assert video_storage.get_valid_active_session("cam-checkpoint-01")["session_id"] == session_id


def test_internal_sync_empty_camera_control_returns_200_shape(monkeypatch):
    from starlette.requests import Request
    from backend.api import dashboard

    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: None)
    request = Request({"type": "http", "query_string": b"camera_id=cam-border-01"})
    result = asyncio.run(dashboard.get_internal_sync(request))
    assert result["camera_id"] == "cam-border-01"
    assert "download_url" not in result


def test_scenario_rejects_obsolete_session_when_no_durable_control_exists(monkeypatch):
    """An expired browser slot must not pause the configured cloud replay."""
    from backend.api import dashboard
    from fastapi import HTTPException

    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: None)
    payload = {
        "camera_id": "cam-border-01",
        "video_session_id": "obsolete-browser-session",
        "scenario": "paused",
        "video_time": 0,
    }

    with pytest.raises(HTTPException) as exc:
        asyncio.run(dashboard.post_video_scenario(payload))

    assert exc.value.status_code == 409
