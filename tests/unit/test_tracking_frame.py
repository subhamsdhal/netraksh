import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api.system import _latest_tracking_sequence, _tracking_timelines, post_tracking_frame
from backend.models.orm import AnalysisRunSummary, AnalysisTrackingSample, Base
from shared.schemas import TrackingFramePayload


def _run_sync_async_handler(coroutine):
    """Run a handler that has no await points without creating a Windows loop."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("handler unexpectedly yielded control")


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _payload():
    return TrackingFramePayload(
        camera_id="cam-checkpoint-01",
        timestamp=1.0,
        sequence=4,
        frame_index=12,
        video_time=0.5,
        stream_id="source-1",
        analysis_session_id="run-1",
        analysis_generation=2,
        tracks=[{
            "track_id": 7,
            "detection_class": "person",
            "confidence": 0.83,
            "detector_confirmed": False,
            "confidence_semantics": "LAST_DETECTION_CONFIDENCE",
            "last_detection_confidence": 0.83,
            "bbox_x": 0.1,
            "bbox_y": 0.2,
            "bbox_w": 0.2,
            "bbox_h": 0.4,
        }],
    )


def test_tracking_frame_is_visualization_only_and_durably_checkpointed():
    payload = _payload()
    db = _session()
    _latest_tracking_sequence.clear()
    assert payload.visualization_only is True
    assert payload.bbox_format == "XYWH"
    assert payload.coordinate_space == "NORMALIZED_FRAME"
    assert payload.tracks[0].detector_confirmed is False
    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        result = asyncio.run(post_tracking_frame(
            payload,
            SimpleNamespace(edge_id="cam-checkpoint-01"),
            db,
        ))
    assert result == {"status": "ok"}
    broadcast.assert_awaited_once()
    stored = db.get(AnalysisTrackingSample, ("run-1", 4, 12))
    assert stored is not None
    assert stored.sample_json["frame_index"] == 12
    summary = db.get(AnalysisRunSummary, "run-1")
    assert summary is not None
    assert (summary.final_frame_index, summary.final_video_time) == (12, 0.5)


def test_duplicate_sample_can_reconstruct_a_missing_run_summary():
    payload = _payload().model_copy(update={
        "person_count": 2, "vehicle_count": 1, "track_count": 3,
    })
    db = _session()
    db.add(AnalysisTrackingSample(
        analysis_session_id=payload.analysis_session_id,
        sequence=payload.sequence,
        frame_index=payload.frame_index,
        camera_id=payload.camera_id,
        stream_id=payload.stream_id,
        analysis_generation=payload.analysis_generation,
        video_time=payload.video_time,
        sample_json={"frame_index": payload.frame_index, "video_time": payload.video_time},
    ))
    db.commit()
    _latest_tracking_sequence.clear()

    with (
        patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock),
        patch("backend.api.system.promote_active_session"),
    ):
        result = asyncio.run(post_tracking_frame(
            payload, SimpleNamespace(edge_id=payload.camera_id), db,
        ))

    summary = db.get(AnalysisRunSummary, payload.analysis_session_id)
    assert result == {"status": "ok"}
    assert summary is not None
    assert summary.final_frame_index == payload.frame_index
    assert summary.final_video_time == payload.video_time
    assert (summary.person_count, summary.vehicle_count, summary.track_count) == (2, 1, 3)


def test_tracking_frame_rejects_a_different_authenticated_edge_identity():
    _latest_tracking_sequence.clear()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(post_tracking_frame(
            _payload(),
            SimpleNamespace(edge_id="cam-border-01"),
            _session(),
        ))
    assert exc_info.value.status_code == 403


def test_tracking_frame_keeps_out_of_order_packet_for_replay_without_rebroadcast():
    newest = _payload().model_copy(update={"sequence": 9, "frame_index": 27})
    delayed = _payload().model_copy(update={"sequence": 8, "frame_index": 24})
    _latest_tracking_sequence.clear()

    identity = ("cam-checkpoint-01", "source-1", "run-1", 2)
    _tracking_timelines.pop(identity, None)
    db = _session()
    try:
        with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
            accepted = asyncio.run(post_tracking_frame(
                newest, SimpleNamespace(edge_id="cam-checkpoint-01"), db
            ))
            delayed_result = asyncio.run(post_tracking_frame(
                delayed, SimpleNamespace(edge_id="cam-checkpoint-01"), db
            ))

        assert accepted == {"status": "ok"}
        assert delayed_result == {"status": "accepted_for_replay", "live_broadcast": False}
        assert {item["frame_index"] for item in _tracking_timelines[identity]} == {24, 27}
        assert {item["bbox_format"] for item in _tracking_timelines[identity]} == {"XYWH"}
        assert {item["coordinate_space"] for item in _tracking_timelines[identity]} == {"NORMALIZED_FRAME"}
        assert db.query(AnalysisTrackingSample).count() == 2
        broadcast.assert_awaited_once()
    finally:
        _tracking_timelines.pop(identity, None)


@pytest.mark.parametrize("camera_id", ["cam-border-01", "cam-checkpoint-01"])
def test_delayed_or_duplicate_tracking_frames_do_not_roll_back_summary(camera_id):
    _latest_tracking_sequence.clear()
    identity = (camera_id, "source-1", "run-1", 2)
    _tracking_timelines.pop(identity, None)
    db = _session()
    newest = _payload().model_copy(update={
        "camera_id": camera_id,
        "sequence": 9, "frame_index": 27, "video_time": 1.08,
        "person_count": 3, "vehicle_count": 1, "track_count": 4,
        "timestamp": 2.0, "processed_timestamp": 2.0,
    })
    delayed = _payload().model_copy(update={
        "camera_id": camera_id,
        "sequence": 8, "frame_index": 24, "video_time": 0.96,
        "person_count": 1, "vehicle_count": 0, "track_count": 1,
        "timestamp": 1.8, "processed_timestamp": 1.8,
    })
    try:
        with (
            patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock),
            patch("backend.api.system.promote_active_session"),
        ):
            asyncio.run(post_tracking_frame(
                newest, SimpleNamespace(edge_id=camera_id), db
            ))
            # A retried duplicate with conflicting ancillary counts must remain
            # idempotent and cannot replace the values for the accepted frame.
            duplicate = newest.model_copy(update={
                "person_count": 99, "vehicle_count": 99, "track_count": 198,
            })
            asyncio.run(post_tracking_frame(
                duplicate, SimpleNamespace(edge_id=camera_id), db
            ))
            result = asyncio.run(post_tracking_frame(
                delayed, SimpleNamespace(edge_id=camera_id), db
            ))

        assert result == {"status": "accepted_for_replay", "live_broadcast": False}
        summary = db.get(AnalysisRunSummary, "run-1")
        assert summary.final_frame_index == 27
        assert summary.final_video_time == 1.08
        assert (summary.person_count, summary.vehicle_count, summary.track_count) == (3, 1, 4)
        assert db.query(AnalysisTrackingSample).count() == 2
        assert {item["frame_index"] for item in _tracking_timelines[identity]} == {24, 27}
    finally:
        _tracking_timelines.pop(identity, None)


def test_tracking_frame_accepts_sequence_reset_for_new_run():
    previous = _payload().model_copy(update={"sequence": 50})
    next_run = _payload().model_copy(update={
        "sequence": 1,
        "analysis_session_id": "run-2",
    })
    _latest_tracking_sequence.clear()
    db = _session()

    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        asyncio.run(post_tracking_frame(previous, SimpleNamespace(edge_id="cam-checkpoint-01"), db))
        result = asyncio.run(post_tracking_frame(next_run, SimpleNamespace(edge_id="cam-checkpoint-01"), db))

    assert result == {"status": "ok"}
    assert broadcast.await_count == 2


def test_tracking_frame_accepts_empty_image_grounded_sample_to_clear_stale_boxes():
    payload = _payload().model_copy(update={"sequence": 10, "frame_index": 30, "tracks": []})
    _latest_tracking_sequence.clear()

    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        result = asyncio.run(post_tracking_frame(
            payload,
            SimpleNamespace(edge_id="cam-checkpoint-01"),
            _session(),
        ))

    assert result == {"status": "ok"}
    broadcast.assert_awaited_once()
    assert broadcast.await_args.args[0]["tracks"] == []


def test_completion_uses_durable_samples_after_memory_loss():
    from backend.api.system import _record_run_summary

    db = _session()
    payload = _payload()
    asyncio.run(post_tracking_frame(payload, SimpleNamespace(edge_id="cam-checkpoint-01"), db))
    identity = ("cam-checkpoint-01", "source-1", "run-1", 2)
    _tracking_timelines.pop(identity, None)

    from shared.schemas import LiveTelemetryPayload
    completion = LiveTelemetryPayload(**{
        **payload.model_dump(),
        "analysis_state": "COMPLETED",
    })
    _record_run_summary(db, completion)
    db.commit()

    summary = db.get(AnalysisRunSummary, "run-1")
    assert summary.tracking_sample_count == 1
    assert summary.tracking_timeline_json[0]["frame_index"] == 12


def test_camera1_eof_completion_requires_exact_durable_final_sample(monkeypatch):
    from backend.api import dashboard

    identity = ("cam-border-01", "source-1", "run-1", 2)
    _tracking_timelines.pop(identity, None)
    db = _session()
    accepted = []
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda _camera: {
        "session_id": "source-1", "analysis_generation": 2,
        "latest_analysis_session_id": "run-1", "analysis_state": "ACTIVE",
    })

    def complete_after_summary_commit(camera, source, generation, changes):
        committed = db.get(AnalysisRunSummary, "run-1")
        assert committed.completed_at is not None
        assert committed.tracking_sample_count == 1
        accepted.append(changes)
        return {"analysis_generation": generation, "analysis_state": "COMPLETED"}

    monkeypatch.setattr(
        dashboard, "complete_active_session", complete_after_summary_commit,
    )
    completion = {
        "camera_id": "cam-border-01", "video_session_id": "source-1",
        "analysis_session_id": "run-1", "analysis_generation": 2,
        "final_frame_index": 2385, "final_video_time": 79.4666667,
        "final_processed_frame_index": 2385, "final_processed_video_time": 79.4666667,
        "final_authoritative_sample_frame_index": 2385,
        "final_authoritative_sample_video_time": 79.4666667,
    }
    with pytest.raises(HTTPException) as exc_info:
        _run_sync_async_handler(dashboard.complete_dashboard_video(
            completion, SimpleNamespace(edge_id="cam-border-01"), db,
        ))
    assert exc_info.value.status_code == 409
    assert accepted == []

    final_sample = _payload().model_copy(update={
        "camera_id": "cam-border-01", "stream_id": "source-1",
        "analysis_session_id": "run-1", "analysis_generation": 2,
        "sequence": 701, "frame_index": 2385, "video_time": 79.4666667,
    })
    promoted = []
    with (
        patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock),
        patch("backend.api.system.promote_active_session", side_effect=lambda *args: promoted.append(args)),
    ):
        _run_sync_async_handler(post_tracking_frame(
            final_sample, SimpleNamespace(edge_id="cam-border-01"), db,
        ))
        _run_sync_async_handler(post_tracking_frame(
            final_sample, SimpleNamespace(edge_id="cam-border-01"), db,
        ))
    assert promoted == [
        ("cam-border-01", "source-1", 2, "run-1"),
        ("cam-border-01", "source-1", 2, "run-1"),
    ]
    assert db.query(AnalysisTrackingSample).filter_by(
        analysis_session_id="run-1", frame_index=2385,
    ).count() == 1
    analysis_summary = db.get(AnalysisRunSummary, "run-1")
    assert analysis_summary is not None
    assert db.get(AnalysisTrackingSample, ("run-1", 701, 2385)) is not None

    result = _run_sync_async_handler(dashboard.complete_dashboard_video(
        completion, SimpleNamespace(edge_id="cam-border-01"), db,
    ))
    assert result["analysis_state"] == "COMPLETED"
    assert len(accepted) == 1
    assert analysis_summary.completed_at is not None
    assert analysis_summary.tracking_sample_count == 1
    assert analysis_summary.tracking_timeline_json[0]["frame_index"] == 2385
