import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.system import (
    _completed_telemetry_view,
    _latest_frames,
    _latest_telemetry,
    _record_run_summary,
    _tracking_timelines,
    post_telemetry,
)
from backend.models.orm import AnalysisRunSummary, Base
from shared.schemas import LiveTelemetryPayload


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _payload(**overrides):
    values = {
        "camera_id": "cam-border-01",
        "timestamp": 1000.0,
        "processed_timestamp": 1000.0,
        "sequence": 1,
        "stream_id": "source-1",
        "analysis_session_id": "run-1",
        "analysis_generation": 3,
        "analysis_state": "PROCESSING",
        "processing_fps": 12.5,
        "source_fps": 25.0,
        "person_count": 0,
        "vehicle_count": 2,
        "track_count": 2,
        "scene_condition": "LOW_LIGHT_NIGHT",
        "lighting_state": "LOW_LIGHT",
        "detection_method": "YOLO",
        "tracks": [],
    }
    values.update(overrides)
    return LiveTelemetryPayload(**values)


def test_sparse_completion_preserves_real_final_measurements():
    db = _session()
    _record_run_summary(db, _payload())
    db.commit()
    _record_run_summary(db, _payload(
        sequence=2,
        timestamp=1010.0,
        processed_timestamp=1010.0,
        analysis_state="COMPLETED",
        processing_fps=None,
        source_fps=None,
        person_count=None,
        vehicle_count=None,
        track_count=None,
        scene_condition=None,
        lighting_state=None,
        detection_method=None,
    ))
    db.commit()

    summary = db.get(AnalysisRunSummary, "run-1")
    assert summary.completed_at == 1010.0
    assert summary.processing_fps == 12.5
    assert summary.person_count == 0
    assert summary.vehicle_count == 2
    assert summary.track_count == 2
    assert summary.scene_condition == "LOW_LIGHT_NIGHT"


def test_completion_persists_only_the_exact_run_tracking_timeline():
    db = _session()
    identity = ("cam-border-01", "source-1", "run-1", 3)
    _tracking_timelines[identity] = [{
        "camera_id": "cam-border-01", "stream_id": "source-1",
        "analysis_session_id": "run-1", "analysis_generation": 3,
        "source_generation": 7, "frame_index": 12, "video_time": 0.5,
        "tracks": [],
    }]
    try:
        _record_run_summary(db, _payload(
            source_generation=7, detector_fps=1.5, hud_fps=10.0,
            analysis_state="COMPLETED",
        ))
        db.commit()
        summary = db.get(AnalysisRunSummary, "run-1")
        assert summary.source_generation == 7
        assert summary.tracking_sample_count == 1
        assert summary.tracking_timeline_json[0]["frame_index"] == 12
        assert summary.detector_fps == 1.5
        assert summary.hud_fps == 10.0
    finally:
        _tracking_timelines.pop(identity, None)


def test_run_identity_conflict_is_rejected():
    db = _session()
    _record_run_summary(db, _payload())
    db.commit()
    try:
        _record_run_summary(db, _payload(stream_id="different-source"))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("identity conflict was accepted")


def test_completed_telemetry_restores_final_real_sample_without_fabrication():
    db = _session()
    _record_run_summary(db, _payload(
        frame_index=42,
        video_time=1.75,
        person_count=1,
        vehicle_count=2,
        track_count=3,
    ))
    db.commit()
    _latest_frames["cam-border-01"] = {
        ("run-1", 42): {"person_count": 1, "vehicle_count": 2, "track_count": 3},
    }
    try:
        hydrated = _completed_telemetry_view(db, {
            "camera_id": "cam-border-01",
            "stream_id": "source-1",
            "analysis_session_id": "run-1",
            "analysis_generation": 3,
            "analysis_state": "COMPLETED",
            "frame_index": None,
            "person_count": None,
            "vehicle_count": None,
            "track_count": None,
            "preview_available": False,
            "tracks": [],
        })
    finally:
        _latest_frames.pop("cam-border-01", None)
    assert hydrated["frame_index"] == 42
    assert hydrated["person_count"] == 1
    assert hydrated["vehicle_count"] == 2
    assert hydrated["track_count"] == 3
    assert hydrated["preview_available"] is True
    assert hydrated["tracks"] == []


def test_completed_telemetry_never_hydrates_a_conflicting_run_identity():
    db = _session()
    _record_run_summary(db, _payload(frame_index=42, person_count=1))
    db.commit()
    marker = {
        "camera_id": "cam-checkpoint-01",
        "stream_id": "source-1",
        "analysis_session_id": "run-1",
        "analysis_generation": 3,
        "analysis_state": "COMPLETED",
        "frame_index": None,
        "person_count": None,
    }
    assert _completed_telemetry_view(db, marker) is marker


def test_sparse_completion_keeps_the_last_exact_available_frame_pair():
    db = _session()
    _record_run_summary(db, _payload(frame_index=43, person_count=2, vehicle_count=0, track_count=2))
    db.commit()
    previous = _payload(
        frame_index=42,
        video_time=1.75,
        person_count=1,
        vehicle_count=0,
        track_count=1,
    ).model_dump()
    _latest_frames["cam-border-01"] = {
        ("run-1", 42): {"person_count": 1, "vehicle_count": 0, "track_count": 1},
    }
    try:
        hydrated = _completed_telemetry_view(db, {
            **previous,
            "analysis_state": "COMPLETED",
            "timestamp": 1010.0,
            "processed_timestamp": 1010.0,
            "sequence": 2,
            "frame_index": None,
            "person_count": None,
            "vehicle_count": None,
            "track_count": None,
        }, previous)
    finally:
        _latest_frames.pop("cam-border-01", None)
    assert hydrated["analysis_state"] == "COMPLETED"
    assert hydrated["frame_index"] == 42
    assert hydrated["video_time"] == 1.75
    assert hydrated["person_count"] == 1
    assert hydrated["track_count"] == 1
    assert hydrated["preview_available"] is True


@pytest.mark.asyncio
async def test_sparse_completion_broadcast_delivers_the_real_final_sample(monkeypatch):
    db = _session()
    delivered = []

    async def capture(telemetry):
        delivered.append(telemetry)

    monkeypatch.setattr("backend.api.system.broadcast_telemetry", capture)
    _latest_telemetry.pop("cam-border-01", None)
    try:
        await post_telemetry(_payload(frame_index=42, person_count=1, vehicle_count=2, track_count=3), db, None)
        await post_telemetry(_payload(
            sequence=2,
            timestamp=1010.0,
            processed_timestamp=1010.0,
            analysis_state="COMPLETED",
            frame_index=None,
            person_count=None,
            vehicle_count=None,
            track_count=None,
        ), db, None)
    finally:
        _latest_telemetry.pop("cam-border-01", None)

    assert delivered[-1]["analysis_state"] == "COMPLETED"
    assert delivered[-1]["frame_index"] == 42
    assert delivered[-1]["person_count"] == 1
    assert delivered[-1]["vehicle_count"] == 2
    assert delivered[-1]["track_count"] == 3
