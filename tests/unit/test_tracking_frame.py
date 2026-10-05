import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.api.system import _latest_tracking_sequence, post_tracking_frame
from shared.schemas import TrackingFramePayload


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


def test_tracking_frame_is_visualization_only_and_broadcast_without_database_write():
    payload = _payload()
    _latest_tracking_sequence.clear()
    assert payload.visualization_only is True
    assert payload.tracks[0].detector_confirmed is False
    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        result = asyncio.run(post_tracking_frame(
            payload,
            SimpleNamespace(edge_id="cam-checkpoint-01"),
        ))
    assert result == {"status": "ok"}
    broadcast.assert_awaited_once()


def test_tracking_frame_rejects_a_different_authenticated_edge_identity():
    _latest_tracking_sequence.clear()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(post_tracking_frame(
            _payload(),
            SimpleNamespace(edge_id="cam-border-01"),
        ))
    assert exc_info.value.status_code == 403


def test_tracking_frame_ignores_out_of_order_packet_from_same_run():
    newest = _payload().model_copy(update={"sequence": 9, "frame_index": 27})
    delayed = _payload().model_copy(update={"sequence": 8, "frame_index": 24})
    _latest_tracking_sequence.clear()

    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        accepted = asyncio.run(post_tracking_frame(
            newest, SimpleNamespace(edge_id="cam-checkpoint-01")
        ))
        ignored = asyncio.run(post_tracking_frame(
            delayed, SimpleNamespace(edge_id="cam-checkpoint-01")
        ))

    assert accepted == {"status": "ok"}
    assert ignored == {"status": "stale_ignored"}
    broadcast.assert_awaited_once()


def test_tracking_frame_accepts_sequence_reset_for_new_run():
    previous = _payload().model_copy(update={"sequence": 50})
    next_run = _payload().model_copy(update={
        "sequence": 1,
        "analysis_session_id": "run-2",
    })
    _latest_tracking_sequence.clear()

    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        asyncio.run(post_tracking_frame(previous, SimpleNamespace(edge_id="cam-checkpoint-01")))
        result = asyncio.run(post_tracking_frame(next_run, SimpleNamespace(edge_id="cam-checkpoint-01")))

    assert result == {"status": "ok"}
    assert broadcast.await_count == 2


def test_tracking_frame_accepts_empty_image_grounded_sample_to_clear_stale_boxes():
    payload = _payload().model_copy(update={"sequence": 10, "frame_index": 30, "tracks": []})
    _latest_tracking_sequence.clear()

    with patch("backend.api.system.broadcast_telemetry", new_callable=AsyncMock) as broadcast:
        result = asyncio.run(post_tracking_frame(
            payload,
            SimpleNamespace(edge_id="cam-checkpoint-01"),
        ))

    assert result == {"status": "ok"}
    broadcast.assert_awaited_once()
    assert broadcast.await_args.args[0]["tracks"] == []
