from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import numpy as np
import pytest

from edge.telemetry import build_active_track_snapshot, build_frame_snapshot, render_snapshot, telemetry_is_newer
from backend.api.system import _telemetry_is_newer as backend_telemetry_is_newer
from shared.constants import DetectionClass
from shared.schemas import BoundingBox


def _track(track_id, detection_class, confidence=0.9, matched=True):
    is_vehicle = detection_class == DetectionClass.VEHICLE
    return SimpleNamespace(
        track_id=track_id,
        detection_class=detection_class,
        confidence=confidence,
        bbox=BoundingBox(x1=10, y1=20, x2=110, y2=220),
        vehicle_subtype="car" if is_vehicle else None,
        source_class_id=2 if is_vehicle else 0,
        tracker_state="TRACKED_CURRENT_FRAME" if matched else "PREDICTED_ONLY",
        matched_current_frame=matched,
    )


def test_counts_come_from_unique_current_tracker_ids():
    snapshot = build_active_track_snapshot([
        _track(7, DetectionClass.PERSON),
        _track(8, DetectionClass.VEHICLE),
        _track(7, DetectionClass.PERSON, confidence=0.8),
    ], 640, 480)
    assert snapshot["person_count"] == 1
    assert snapshot["vehicle_count"] == 1
    assert snapshot["track_count"] == 2
    assert snapshot["active_track_ids"] == [7, 8]
    assert snapshot["tracker_output_count"] == 3


def test_lost_or_historical_tracks_are_not_carried_into_current_frame():
    previous = build_active_track_snapshot([_track(1, DetectionClass.PERSON)], 640, 480)
    current = build_active_track_snapshot([_track(2, DetectionClass.VEHICLE)], 640, 480)
    assert previous["active_track_ids"] == [1]
    assert current["active_track_ids"] == [2]
    assert current["person_count"] == 0
    assert current["vehicle_count"] == 1


def test_predicted_only_tracker_state_is_excluded():
    snapshot = build_active_track_snapshot([
        _track(1, DetectionClass.PERSON),
        _track(99, DetectionClass.PERSON, matched=False),
    ], 640, 480)
    assert snapshot["active_track_ids"] == [1]
    assert snapshot["person_count"] == 1


def test_malformed_collapsed_and_off_frame_boxes_are_rejected_before_transmission():
    valid = _track(1, DetectionClass.PERSON)
    collapsed = _track(2, DetectionClass.PERSON)
    collapsed.bbox = SimpleNamespace(x1=20, y1=20, x2=20, y2=100)
    non_finite = _track(3, DetectionClass.PERSON)
    non_finite.bbox = SimpleNamespace(x1=float("nan"), y1=20, x2=100, y2=100)
    off_frame = _track(4, DetectionClass.PERSON)
    off_frame.bbox = SimpleNamespace(x1=700, y1=20, x2=800, y2=100)
    snapshot = build_active_track_snapshot(
        [valid, collapsed, non_finite, off_frame], 640, 480
    )
    assert snapshot["active_track_ids"] == [1]
    assert snapshot["track_count"] == 1
    assert len(snapshot["tracks"]) == 1


def test_render_and_counts_share_one_immutable_snapshot():
    snapshot = build_frame_snapshot(
        camera_id="cam-border-01", analysis_session_id="session-1234",
        frame_index=42, source_timestamp=1, processed_at=2, source_video_time=3,
        tracks=[_track(1, DetectionClass.PERSON), _track(2, DetectionClass.VEHICLE)],
        frame_width=320, frame_height=240,
    )
    assert snapshot.person_count == 1
    assert snapshot.vehicle_count == 1
    assert snapshot.track_count == 2
    assert len(snapshot.live_tracks()) == len(snapshot.objects) == 2
    rendered = render_snapshot(np.zeros((240, 320, 3), dtype=np.uint8), snapshot, hud=True)
    clean = render_snapshot(np.zeros((240, 320, 3), dtype=np.uint8), snapshot, hud=False)
    assert np.count_nonzero(rendered) > 0
    assert np.count_nonzero(clean) == 0
    with pytest.raises(FrozenInstanceError):
        snapshot.frame_index = 43


def test_same_session_out_of_order_frame_is_rejected():
    current = {"analysis_session_id": "s1", "frame_index": 20, "sequence": 5, "processed_timestamp": 200}
    assert not telemetry_is_newer(current, {"analysis_session_id": "s1", "frame_index": 19, "sequence": 6, "processed_timestamp": 201})
    assert telemetry_is_newer(current, {"analysis_session_id": "s1", "frame_index": 21, "sequence": 1, "processed_timestamp": 201})


def test_old_session_packet_cannot_replace_new_replay_session():
    current = {"analysis_session_id": "replay-2", "frame_index": 1, "processed_timestamp": 300}
    assert not telemetry_is_newer(current, {"analysis_session_id": "replay-1", "frame_index": 999, "processed_timestamp": 299})
    assert telemetry_is_newer(current, {"analysis_session_id": "replay-3", "frame_index": 1, "processed_timestamp": 301})
    assert not backend_telemetry_is_newer(current, {"analysis_session_id": "replay-1", "frame_index": 999, "processed_timestamp": 299})
