from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.system import _completed_telemetry_view, _latest_frames, _record_run_summary
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
