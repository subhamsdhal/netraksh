import json
import uuid
from pathlib import Path

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
