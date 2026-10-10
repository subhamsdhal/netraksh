import hashlib
import asyncio
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.dashboard import _media_byte_range
from backend.api import dashboard
from backend.models.orm import Base, Camera, VideoMediaObject
from backend.services import postgres_video_storage as storage


@pytest.fixture
def media_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as db:
        db.add(Camera(id="cam-border-01", name="Border Post Alpha", location="Sector 7", owning_command_id="COMMAND_A"))
        db.add(Camera(id="cam-checkpoint-01", name="Checkpoint Bravo", location="Main checkpoint", owning_command_id="COMMAND_A"))
    monkeypatch.setattr(storage, "SessionLocal", factory)
    yield factory
    engine.dispose()


def test_postgres_video_store_preserves_approved_original_and_prepared_identity(media_db, monkeypatch):
    session_id = str(uuid.uuid4())
    original = b"\x00\x00\x00\x18ftypisom" + b"a" * 100
    prepared = b"\x00\x00\x00\x18ftypisom" + b"b" * 80
    monkeypatch.setitem(storage.APPROVED_ORIGINAL_SHA256, "cam-border-01", hashlib.sha256(original).hexdigest())
    original_key = f"video-preparation/cam-border-01/{session_id}/original.mp4"
    source_key = f"video-sessions/cam-border-01/{session_id}/source.mp4"
    store = storage.PostgresVideoStorage()
    store.put_object(original_key, original, "video/mp4")
    store.put_object(original_key, original, "video/mp4")
    store.put_object(source_key, prepared, "video/mp4")
    storage.record_prepared_metadata("cam-border-01", session_id, original_filename="vid 1.mp4", duration_seconds=79.5, fps=30.0, source_generation=1)
    with media_db() as db:
        assert db.query(VideoMediaObject).count() == 2
        source = db.get(VideoMediaObject, source_key)
        raw = db.get(VideoMediaObject, original_key)
        assert source.sha256 == hashlib.sha256(prepared).hexdigest()
        assert raw.sha256 == hashlib.sha256(original).hexdigest()
        assert raw.prepared_source_key == source_key
        assert source.original_filename == "vid 1.mp4"
        assert source.source_generation == 1
    store.delete_object(original_key)
    assert store.get_object(original_key) == original
    assert store.get_object(source_key) == prepared
    with pytest.raises(ValueError, match="different bytes"):
        store.put_object(source_key, original, "video/mp4")


def test_postgres_video_store_rejects_other_camera_and_wrong_original(media_db):
    session_id = str(uuid.uuid4())
    key = f"video-preparation/cam-border-01/{session_id}/original.mp4"
    with pytest.raises(ValueError, match="checksum"):
        storage.PostgresVideoStorage().put_object(key, b"\x00\x00\x00\x18ftypisomwrong", "video/mp4")
    with pytest.raises(ValueError, match="approved"):
        storage.PostgresVideoStorage().put_object(key.replace("cam-border-01", "other-camera"), b"\x00\x00\x00\x18ftypisomwrong", "video/mp4")


def test_postgres_video_control_records_are_idempotent(media_db):
    key = "video-control/cam-border-01.json"
    # The actual control convention has the camera ID as the last path segment.
    payload = {"camera_id": "cam-border-01", "scenario": "paused"}
    store = storage.PostgresVideoStorage()
    store.put_object(key, json.dumps(payload).encode(), "application/json")
    store.put_object(key, json.dumps(payload).encode(), "application/json")
    assert json.loads(store.get_object(key)) == payload


@pytest.mark.parametrize("header,size,expected", [
    (None, 100, (0, 99, 200)),
    ("bytes=0-9", 100, (0, 9, 206)),
    ("bytes=90-", 100, (90, 99, 206)),
    ("bytes=-10", 100, (90, 99, 206)),
    ("bytes=0-999", 100, (0, 99, 206)),
])
def test_media_byte_ranges(header, size, expected):
    assert _media_byte_range(header, size) == expected


@pytest.mark.parametrize("header", ["bytes=100-", "bytes=9-1", "bytes=-0", "bytes=0-1,4-5", "wat=0-1"])
def test_media_unsatisfiable_or_invalid_ranges(header):
    with pytest.raises(ValueError):
        _media_byte_range(header, 100)


def test_authenticated_postgres_media_response_has_200_206_and_416_contract(monkeypatch):
    from starlette.requests import Request

    camera_id = "cam-border-01"
    session_id = str(uuid.uuid4())
    key = f"video-sessions/{camera_id}/{session_id}/source.mp4"
    payload = b"0123456789"
    monkeypatch.setattr(dashboard, "get_uploaded_session", lambda *_args: {"source_object_key": key})
    monkeypatch.setattr(dashboard, "media_info", lambda *_args: {
        "camera_id": camera_id, "session_id": session_id, "byte_size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(), "ready": True,
    })
    monkeypatch.setattr(dashboard, "iter_media_chunks", lambda _key, start, end: iter([payload[start:end + 1]]))

    async def body(response):
        return b"".join([chunk async for chunk in response.body_iterator])

    def request(range_header=None):
        headers = [(b"range", range_header.encode())] if range_header else []
        return Request({"type": "http", "headers": headers})

    full = dashboard._postgres_media_response(camera_id, session_id, request())
    assert full.status_code == 200 and full.headers["content-length"] == "10"
    assert asyncio.run(body(full)) == payload
    partial = dashboard._postgres_media_response(camera_id, session_id, request("bytes=2-5"))
    assert partial.status_code == 206 and partial.headers["content-range"] == "bytes 2-5/10"
    assert partial.headers["content-length"] == "4"
    assert asyncio.run(body(partial)) == b"2345"
    invalid = dashboard._postgres_media_response(camera_id, session_id, request("bytes=10-"))
    assert invalid.status_code == 416 and invalid.headers["content-range"] == "bytes */10"
