import asyncio
import copy
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.api import dashboard
from backend.services import video_storage

SOURCE_ID = "22222222-2222-4222-8222-222222222222"


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *_conditions):
        return self

    def with_for_update(self):
        return self

    def one_or_none(self):
        return self.value

    def all(self):
        return self.value


class _Database:
    def __init__(self, camera, summary=None):
        self.camera = camera
        self.summary = summary

    def query(self, _model):
        return _Query(self.camera)

    def get(self, _model, _identity):
        return self.summary


def _request():
    return SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))


def _user(role="ADMIN", command_id="COMMAND_A"):
    return SimpleNamespace(id="user-1", role=role, command_id=command_id)


def _setup(monkeypatch, *, camera_id="cam-border-01", lifecycle="COMPLETED"):
    camera = SimpleNamespace(id=camera_id, is_active=True, owning_command_id="COMMAND_A")
    db = _Database(camera)
    active = {
        "session_id": SOURCE_ID,
        "camera_id": camera_id,
        "source_mode": "durable",
        "source_object_key": f"video-sessions/cam-border-01/{SOURCE_ID}/source.mp4",
        "analysis_state": lifecycle,
        "analysis_generation": 4,
        "source_generation": 2,
        "scenario": "paused",
        "latest_analysis_session_id": "old-run-4",
    }
    metadata = {
        "camera_id": camera_id,
        "session_id": SOURCE_ID,
        "source_object_key": active["source_object_key"],
    }
    old_history = [{"analysis_session_id": "old-run-4", "generation": 4}]
    starts = []
    audits = []
    wakes = []

    def start_active(_camera_id, session_id, *, request_id=None):
        assert session_id == SOURCE_ID
        if active.get("last_start_request_id") == request_id:
            return copy.deepcopy(active), False
        active.update({
            "scenario": "normal",
            "analysis_state": "WAKING",
            "analysis_generation": active["analysis_generation"] + 1,
            "video_time": 0.0,
            "latest_analysis_session_id": None,
            "last_start_request_id": request_id,
        })
        starts.append(request_id)
        return copy.deepcopy(active), True

    async def wake(_camera_id):
        wakes.append(_camera_id)
        return "waking"

    monkeypatch.setattr(dashboard, "_durable_video_enabled", lambda: True)
    monkeypatch.setattr(dashboard.settings, "AUDIT_LOG_ENABLED", True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda _camera_id: copy.deepcopy(active))
    monkeypatch.setattr(dashboard, "get_uploaded_session", lambda *_args: copy.deepcopy(metadata))
    monkeypatch.setattr(dashboard, "start_active_session", start_active)
    monkeypatch.setattr(dashboard, "_wake_edge_service", wake)
    monkeypatch.setattr(dashboard, "audit", lambda _db, action, **kwargs: audits.append((action, kwargs)))
    monkeypatch.setattr(dashboard, "store_uploaded_session", lambda **_kwargs: pytest.fail("reanalyze must not store or upload source bytes"))
    return db, camera, active, old_history, starts, audits, wakes


def _payload(request_id="11111111-1111-4111-8111-111111111111"):
    return {
        "camera_id": "cam-border-01",
        "video_session_id": SOURCE_ID,
        "request_id": request_id,
    }


def test_reanalyze_reuses_completed_source_creates_generation_and_audits(monkeypatch):
    db, _camera, active, old_history, starts, audits, wakes = _setup(monkeypatch)

    result = asyncio.run(dashboard.reanalyze_existing_video(_payload(), _request(), db, _user()))

    assert result == {
        "status": "success",
        "camera_id": "cam-border-01",
        "source_mode": "durable",
        "source_session_id": SOURCE_ID,
        "analysis_generation": 5,
        "analysis_state": "WAKING",
        "analysis_session_id": None,
        "scenario": "normal",
        "request_id": _payload()["request_id"],
        "idempotent_replay": False,
        "edge_status": "waking",
    }
    assert active["analysis_generation"] == 5
    assert active["last_start_request_id"] == _payload()["request_id"]
    assert starts == [_payload()["request_id"]]
    assert wakes == ["cam-border-01"]
    assert len(old_history) == 1
    assert audits[0][0] == "ANALYSIS_RESTARTED_FROM_EXISTING_SOURCE"
    assert audits[0][1]["resource_id"] == SOURCE_ID
    assert "analysis_generation=5" in audits[0][1]["detail"]


def test_reanalyze_camera_2_reuses_its_completed_source_without_upload(monkeypatch):
    db, _camera, active, history, starts, audits, wakes = _setup(
        monkeypatch, camera_id="cam-checkpoint-01"
    )
    payload = {**_payload(), "camera_id": "cam-checkpoint-01"}

    result = asyncio.run(dashboard.reanalyze_existing_video(payload, _request(), db, _user()))

    assert result["camera_id"] == "cam-checkpoint-01"
    assert result["source_session_id"] == SOURCE_ID
    assert result["analysis_generation"] == 5
    assert result["analysis_state"] == "WAKING"
    assert active["last_start_request_id"] == payload["request_id"]
    assert starts == [payload["request_id"]]
    assert wakes == ["cam-checkpoint-01"]
    assert len(history) == 1
    assert len(audits) == 1


def test_same_reanalysis_request_is_idempotent_after_start(monkeypatch):
    db, _camera, _active, _history, starts, audits, wakes = _setup(monkeypatch)
    payload = _payload()

    first = asyncio.run(dashboard.reanalyze_existing_video(payload, _request(), db, _user()))
    repeated = asyncio.run(dashboard.reanalyze_existing_video(payload, _request(), db, _user()))

    assert first["analysis_generation"] == repeated["analysis_generation"] == 5
    assert repeated["idempotent_replay"] is True
    assert starts == [payload["request_id"]]
    assert len(audits) == 1
    assert wakes == ["cam-border-01"]


def test_reanalyze_rejects_an_active_run_and_does_not_start_another(monkeypatch):
    db, _camera, _active, _history, starts, audits, wakes = _setup(monkeypatch, lifecycle="ACTIVE")

    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard.reanalyze_existing_video(_payload(), _request(), db, _user()))

    assert error.value.status_code == 409
    assert starts == []
    assert audits == []
    assert wakes == []


def test_reanalyze_enforces_camera_command_ownership(monkeypatch):
    db, _camera, _active, _history, starts, audits, wakes = _setup(monkeypatch)

    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard.reanalyze_existing_video(_payload(), _request(), db, _user("OPERATOR", "COMMAND_B")))

    assert error.value.status_code == 403
    assert starts == []
    assert audits == []
    assert wakes == []


def test_reanalyze_rejects_invalid_request_id_before_mutating(monkeypatch):
    db, _camera, _active, _history, starts, audits, wakes = _setup(monkeypatch)
    payload = _payload(request_id="not-a-uuid")

    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard.reanalyze_existing_video(payload, _request(), db, _user()))

    assert error.value.status_code == 422
    assert starts == []
    assert audits == []
    assert wakes == []


def test_reanalyze_on_camera_1_does_not_change_camera_2_control(monkeypatch):
    db, _camera, _active, _history, starts, _audits, _wakes = _setup(monkeypatch)
    camera2_before = {"analysis_state": "COMPLETED", "analysis_generation": 3, "session_id": "camera-2-source"}
    camera2_after = copy.deepcopy(camera2_before)

    asyncio.run(dashboard.reanalyze_existing_video(_payload(), _request(), db, _user()))

    assert camera2_after == camera2_before
    assert starts == [_payload()["request_id"]]


def test_start_active_session_persists_same_request_identity(monkeypatch):
    current = {
        "camera_id": "cam-border-01",
        "session_id": SOURCE_ID,
        "source_object_key": "source.mp4",
        "analysis_state": "COMPLETED",
        "scenario": "paused",
        "analysis_generation": 9,
    }
    writes = []
    monkeypatch.setattr(video_storage, "get_valid_active_session", lambda _camera_id: copy.deepcopy(current))
    monkeypatch.setattr(video_storage, "_put_json", lambda _key, value: writes.append(copy.deepcopy(value)))

    first, created = video_storage.start_active_session("cam-border-01", SOURCE_ID, request_id="request-1")
    current.update(first)
    repeated, repeated_created = video_storage.start_active_session("cam-border-01", SOURCE_ID, request_id="request-1")

    assert created is True
    assert first["analysis_generation"] == repeated["analysis_generation"] == 10
    assert repeated_created is False
    assert len(writes) == 1


def test_interrupt_exact_generation_preserves_history_and_audits(monkeypatch):
    camera = SimpleNamespace(id="cam-border-01", is_active=True, owning_command_id="COMMAND_A")
    summary = SimpleNamespace(
        camera_id="cam-border-01",
        stream_id=SOURCE_ID,
        analysis_generation=6,
        analysis_session_id="16d1d6ec-1144-4690-8713-c3e16d0475ab",
        last_telemetry_at=time.time() - 120,
        completed_at=None,
    )
    class _InterruptDatabase(_Database):
        def query(self, model):
            if model is dashboard.Camera:
                return _Query(camera)
            return _Query([(summary.analysis_session_id,)])
    db = _InterruptDatabase(camera, summary)
    audits = []
    interrupted = []
    monkeypatch.setattr(dashboard.settings, "AUDIT_LOG_ENABLED", True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda _camera_id: {
        "session_id": SOURCE_ID, "analysis_generation": 6,
    })
    monkeypatch.setattr(dashboard, "interrupt_active_session", lambda *args, **kwargs: interrupted.append((args, kwargs)) or {
        "analysis_state": "INTERRUPTED", "scenario": "paused",
    })
    monkeypatch.setattr(dashboard, "audit", lambda _db, action, **kwargs: audits.append((action, kwargs)))

    result = asyncio.run(dashboard.interrupt_stale_video_analysis({
        "camera_id": "cam-border-01",
        "video_session_id": SOURCE_ID,
        "analysis_session_id": summary.analysis_session_id,
        "analysis_generation": 6,
        "reason": "deployment_interrupted",
    }, _request(), db, _user()))

    assert result["analysis_state"] == "INTERRUPTED"
    assert result["analysis_generation"] == 6
    assert interrupted[0][0] == ("cam-border-01", SOURCE_ID, 6)
    assert audits[0][0] == "ANALYSIS_INTERRUPTED"
    assert audits[0][1]["resource_id"] == "cam-border-01:6"


def test_interrupt_rejects_mismatched_generation_without_mutation(monkeypatch):
    camera = SimpleNamespace(id="cam-border-01", is_active=True, owning_command_id="COMMAND_A")
    summary = SimpleNamespace(
        camera_id="cam-border-01",
        stream_id=SOURCE_ID,
        analysis_generation=6,
        analysis_session_id="16d1d6ec-1144-4690-8713-c3e16d0475ab",
        last_telemetry_at=time.time(),
        completed_at=None,
    )
    db = _Database(camera, summary)
    monkeypatch.setattr(dashboard.settings, "AUDIT_LOG_ENABLED", True)
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda _camera_id: {
        "session_id": SOURCE_ID, "analysis_generation": 7,
    })
    monkeypatch.setattr(dashboard, "interrupt_active_session", lambda *_args, **_kwargs: pytest.fail("recent run must not be interrupted"))

    with pytest.raises(HTTPException) as error:
        asyncio.run(dashboard.interrupt_stale_video_analysis({
            "camera_id": "cam-border-01",
            "video_session_id": SOURCE_ID,
            "analysis_session_id": summary.analysis_session_id,
            "analysis_generation": 6,
            "reason": "deployment_interrupted",
        }, _request(), db, _user()))

    assert error.value.status_code == 409


def test_interrupt_active_session_requires_exact_run_identity(monkeypatch):
    current = {
        "camera_id": "cam-border-01",
        "session_id": SOURCE_ID,
        "analysis_state": "ACTIVE",
        "scenario": "normal",
        "analysis_generation": 6,
        "latest_analysis_session_id": "16d1d6ec-1144-4690-8713-c3e16d0475ab",
    }
    writes = []
    monkeypatch.setattr(video_storage, "get_valid_active_session", lambda _camera_id: copy.deepcopy(current))
    monkeypatch.setattr(video_storage, "_put_json", lambda _key, value: writes.append(copy.deepcopy(value)))

    assert video_storage.interrupt_active_session(
        "cam-border-01", SOURCE_ID, 5, reason="deployment_interrupted",
    ) is None
    settled = video_storage.interrupt_active_session(
        "cam-border-01", SOURCE_ID, 6, reason="deployment_interrupted",
    )

    assert settled["analysis_state"] == "INTERRUPTED"
    assert settled["scenario"] == "paused"
    assert settled["analysis_generation"] == 6
    assert settled["latest_analysis_session_id"] == current["latest_analysis_session_id"]
    assert settled["interruption_reason"] == "deployment_interrupted"
    assert len(writes) == 1
