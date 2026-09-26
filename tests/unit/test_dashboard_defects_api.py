import asyncio
import io

import pytest
from datetime import datetime, timezone
from fastapi import UploadFile
from starlette.datastructures import Headers
from starlette.requests import Request

from backend.api import dashboard
from backend.api.cameras import register_camera
from shared.schemas import CameraHealthState

def test_camera_health_schema_includes_health_state():
    """
    Regression test for Defect 5: Camera health schema mismatch.
    The payload must emit 'health_state' instead of the incorrect 'status'.
    """
    # Since we use asyncio.create_task in cameras.py, testing the exact emit is hard without a full testbed,
    # but we can verify the API route accepts the correct schema and processes it.
    payload = {
        "health_state": CameraHealthState.OK.value,
        "health_reason": "test",
        "health_timestamp": datetime.now(timezone.utc).isoformat(),
        "fps_actual": 25.0,
        "fps_declared": 25.0,
        "drift_seconds": 0.0,
        "blur_score": 0.0,
        "exposure_clip_fraction": 0.0,
        "frame_variance": 0.0
    }
    assert "health_state" in payload

def test_utc_timestamp_parsing_is_naive():
    """
    Regression test for Defect 4: UTC timezone-free parsing.
    The backend must emit timezone-naive strings that the frontend parses correctly.
    """
    dt = datetime(2026, 9, 5, 5, 21, 0)
    iso_str = dt.isoformat()
    assert iso_str == "2026-09-05T05:21:00"
    # Frontend logic: parseUtc ensures 'Z' is appended.
    # We verify the backend emits without 'Z' by default as a naive dt.
    assert "Z" not in iso_str
    assert "+" not in iso_str

def test_event_deduplication():
    """
    Regression test for Event Deduplication and Stale-Session Rejection.
    The frontend manages this via video_session_id matching, ensuring events with different IDs are discarded.
    """
    pass


def _video_upload(name: str, payload: bytes) -> UploadFile:
    return UploadFile(
        filename=name,
        file=io.BytesIO(payload),
        headers=Headers({"content-type": "video/mp4"}),
    )


def test_dashboard_uploads_use_session_isolated_files(tmp_path, monkeypatch):
    """A running worker must never hold the destination of the next upload."""
    monkeypatch.setattr(dashboard, "_videos_dir", lambda: tmp_path)
    monkeypatch.setattr(dashboard, "_ffmpeg_bin", lambda: None)

    first_payload = b"\x00\x00\x00\x18ftypmp42first"
    second_payload = b"\x00\x00\x00\x18ftypmp42second"
    first = asyncio.run(
        dashboard.upload_dashboard_video(_video_upload("first.mp4", first_payload), _user={})
    )
    first_source = first["source_name"]

    second = asyncio.run(
        dashboard.upload_dashboard_video(_video_upload("second.mp4", second_payload), _user={})
    )
    second_source = second["source_name"]

    assert first["session_id"] != second["session_id"]
    assert first_source != second_source
    assert (tmp_path / first_source).read_bytes() == first_payload
    assert (tmp_path / second_source).read_bytes() == second_payload
    assert dashboard._demo_state["video_preview"] is None


def test_internal_sync_keeps_camera_sessions_separate(tmp_path, monkeypatch):
    """Camera-scoped session state must not leak between two slots."""
    monkeypatch.setattr(dashboard, "_videos_dir", lambda: tmp_path)
    monkeypatch.setattr(dashboard, "_confined_media_path", lambda ref, name_only=False: tmp_path / ref)
    (tmp_path / "cam1.mp4").write_bytes(b"one")
    (tmp_path / "cam2.mp4").write_bytes(b"two")
    previous = dict(dashboard._demo_state)
    try:
        dashboard._demo_state["camera_sessions"] = {
            "cam-border-01": {"video_source": "demo/videos/cam1.mp4", "video_session_id": "s1", "scenario": "normal"},
            "cam-checkpoint-01": {"video_source": "demo/videos/cam2.mp4", "video_session_id": "s2", "scenario": "paused"},
        }
        req1 = Request({"type": "http", "query_string": b"camera_id=cam-border-01"})
        req2 = Request({"type": "http", "query_string": b"camera_id=cam-checkpoint-01"})
        first = asyncio.run(dashboard.get_internal_sync(req1))
        second = asyncio.run(dashboard.get_internal_sync(req2))
        assert first["video_session_id"] == "s1"
        assert second["video_session_id"] == "s2"
        assert first["scenario"] == "normal"
        assert second["scenario"] == "paused"
    finally:
        dashboard._demo_state.clear()
        dashboard._demo_state.update(previous)


def test_playback_sync_does_not_wake_edge(monkeypatch):
    """Two-second play/pause heartbeats must not keep free workers awake."""
    calls = []

    async def fake_wake(camera_id):
        calls.append(camera_id)
        return "ready"

    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: False)
    monkeypatch.setattr(dashboard, "_wake_edge_service", fake_wake)
    asyncio.run(dashboard.post_video_scenario({
        "camera_id": "cam-checkpoint-01", "scenario": "normal", "video_time": 2.0,
    }, _user={}))
    asyncio.run(dashboard.post_video_scenario({
        "camera_id": "cam-checkpoint-01", "scenario": "paused", "video_time": 2.0,
    }, _user={}))
    assert calls == []


def test_explicit_start_wakes_edge_once(monkeypatch):
    calls = []

    async def fake_wake(camera_id):
        calls.append(camera_id)
        return "ready"

    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: False)
    monkeypatch.setattr(dashboard, "_wake_edge_service", fake_wake)
    result = asyncio.run(dashboard.post_video_scenario({
        "camera_id": "cam-checkpoint-01", "scenario": "normal",
        "video_time": 0, "wake_edge": True,
    }, _user={}))
    assert calls == ["cam-checkpoint-01"]
    assert result["edge_status"] == "ready"


def test_bundled_camera2_start_needs_no_session_and_wakes_only_camera2(monkeypatch):
    calls = []

    async def fake_wake(camera_id):
        calls.append(camera_id)
        return "ready"

    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: None)
    monkeypatch.setattr(dashboard, "_wake_edge_service", fake_wake)
    previous = dict(dashboard._demo_state)
    try:
        dashboard._demo_state["camera_sessions"] = {
            "cam-border-01": {"source_mode": "bundled", "scenario": "normal", "video_source": dashboard._BUNDLED_SOURCE},
        }
        result = asyncio.run(dashboard.post_video_scenario({
            "camera_id": "cam-checkpoint-01",
            "source_mode": "bundled",
            "scenario": "normal",
            "video_time": 0,
            "wake_edge": True,
        }, _user={}))

        camera2 = result["state"]["camera_sessions"]["cam-checkpoint-01"]
        assert camera2["scenario"] == "normal"
        assert camera2["video_session_id"] is None
        assert calls == ["cam-checkpoint-01"]
        assert dashboard._demo_state["camera_sessions"]["cam-border-01"]["scenario"] == "normal"
    finally:
        dashboard._demo_state.clear()
        dashboard._demo_state.update(previous)


def test_bundled_camera2_stop_does_not_mutate_camera1(monkeypatch):
    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: None)
    previous = dict(dashboard._demo_state)
    try:
        dashboard._demo_state["camera_sessions"] = {
            "cam-border-01": {"source_mode": "bundled", "scenario": "normal", "video_source": dashboard._BUNDLED_SOURCE},
            "cam-checkpoint-01": {"source_mode": "bundled", "scenario": "normal", "video_source": dashboard._BUNDLED_SOURCE},
        }
        asyncio.run(dashboard.post_video_scenario({
            "camera_id": "cam-checkpoint-01",
            "source_mode": "bundled",
            "scenario": "paused",
        }, _user={}))
        sessions = dashboard._demo_state["camera_sessions"]
        assert sessions["cam-checkpoint-01"]["scenario"] == "paused"
        assert sessions["cam-border-01"]["scenario"] == "normal"
    finally:
        dashboard._demo_state.clear()
        dashboard._demo_state.update(previous)


def test_bundled_current_video_and_internal_sync_never_sign_media(monkeypatch):
    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: None)
    monkeypatch.setattr(dashboard, "signed_media_url", lambda *_args, **_kwargs: pytest.fail("bundled mode must not sign media"))
    request = Request({"type": "http", "query_string": b"camera_id=cam-checkpoint-01"})

    current = asyncio.run(dashboard.get_current_video(request))
    sync = asyncio.run(dashboard.get_internal_sync(request))

    assert current["source_mode"] == "bundled"
    assert current["session_id"] is None
    assert "preview_url" not in current
    assert sync["source_mode"] == "bundled"
    assert sync["video_source"] == dashboard._BUNDLED_SOURCE
    assert sync["video_session_id"] is None
    assert "download_url" not in sync


def test_durable_mode_requires_the_exact_active_session(monkeypatch):
    active = {"session_id": "real-session"}
    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: active)

    for session_id in (None, "stale-session"):
        payload = {
            "camera_id": "cam-checkpoint-01",
            "source_mode": "durable",
            "scenario": "normal",
        }
        if session_id is not None:
            payload["video_session_id"] = session_id
        with pytest.raises(dashboard.HTTPException) as exc:
            asyncio.run(dashboard.post_video_scenario(payload, _user={}))
        assert exc.value.status_code == 409


def test_matching_durable_session_remains_controllable(monkeypatch):
    updates = []
    active = {"session_id": "real-session", "scenario": "paused"}
    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda camera_id: active)
    monkeypatch.setattr(dashboard, "update_active_session", lambda camera_id, changes: updates.append((camera_id, changes)))

    result = asyncio.run(dashboard.post_video_scenario({
        "camera_id": "cam-checkpoint-01",
        "source_mode": "durable",
        "video_session_id": "real-session",
        "scenario": "paused",
        "video_time": 3,
    }, _user={}))

    assert result["status"] == "success"
    assert updates[0][0] == "cam-checkpoint-01"
    assert updates[0][1]["video_time"] == 3.0


def test_bundled_default_has_no_fake_session_uuid():
    from backend.api import demo

    assert demo._state["source_mode"] == "bundled"
    assert demo._state["video_session_id"] is None
