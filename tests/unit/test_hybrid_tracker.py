import time

import cv2
import numpy as np

from edge.tracking.hybrid_tracker import AsyncDetectorWorker, DetectorJob, OpticalFlowBoxTracker
from shared.constants import DetectionClass, SceneCondition
from shared.schemas import BoundingBox, TrackData


def _frame(offset=0):
    image = np.zeros((120, 200, 3), dtype=np.uint8)
    for y in range(35, 75, 8):
        for x in range(40 + offset, 90 + offset, 8):
            color = 255 if (x + y) % 16 == 0 else 120
            cv2.rectangle(image, (x, y), (x + 4, y + 4), (color, color, color), -1)
    return image


def _track(x1=38, x2=94):
    return TrackData(
        track_id=7,
        detection_class=DetectionClass.PERSON,
        bbox=BoundingBox(x1=x1, y1=32, x2=x2, y2=80),
        confidence=0.83,
        source_class_id=0,
    )


def test_intermediate_tracker_consumes_image_and_preserves_identity_without_fake_confidence():
    tracker = OpticalFlowBoxTracker(max_width=200, max_detector_age_frames=20)
    first = _frame(0)
    tracker.observe(first, 0)
    anchored = tracker.reanchor([_track()], 0, first)
    assert anchored[0].track_id == 7
    moved = tracker.observe(_frame(6), 1)
    assert moved[0].track_id == 7
    assert moved[0].bbox.x1 > 41
    assert moved[0].tracker_state == "IMAGE_TRACKER_UPDATED"
    assert moved[0].detector_confirmed is False
    assert moved[0].confidence_semantics == "LAST_DETECTION_CONFIDENCE"
    assert moved[0].last_detection_confidence == 0.83
    assert moved[0].confidence == 0.83


def test_detector_refresh_reanchors_drift_and_lost_tracks_expire():
    tracker = OpticalFlowBoxTracker(max_width=200, max_detector_age_frames=1)
    first = _frame(0)
    tracker.observe(first, 0)
    tracker.reanchor([_track()], 0, first)
    tracker.observe(_frame(5), 1)
    corrected = tracker.reanchor([_track(60, 116)], 1, _frame(5))
    assert corrected[0].bbox.x1 == 60
    assert tracker.observe(_frame(10), 2)
    assert tracker.observe(_frame(15), 3) == []


def test_new_object_is_not_invented_before_detector_refresh():
    tracker = OpticalFlowBoxTracker(max_width=200, max_detector_age_frames=20)
    tracker.observe(_frame(0), 0)
    assert tracker.current_tracks() == []
    tracker.observe(_frame(4), 1)
    assert tracker.current_tracks() == []
    refreshed = tracker.reanchor([_track(42, 98)], 1, _frame(4))
    assert [track.track_id for track in refreshed] == [7]
    assert refreshed[0].detector_confirmed is True
    assert refreshed[0].confidence_semantics == "DETECTOR_CURRENT_FRAME"


class _Condition:
    condition = SceneCondition.CLEAR_DAY


class _Detector:
    def __init__(self):
        self.calls = 0
        self.last_raw_detections = []
        self.last_tracker_ms = 0.1
        self._runtime = type("Runtime", (), {"last_stage_ms": {"total": 1.0}})()

    def detect_and_track(self, frame, condition, confidence_threshold):
        self.calls += 1
        return [_track()]


def test_async_detector_reuses_one_detector_and_bounds_pending_work():
    detector = _Detector()
    worker = AsyncDetectorWorker(detector)
    worker.start()
    job = DetectorJob(
        frame=_frame(), detector_frame=_frame(), frame_index=0, meta=None,
        health=None, condition=_Condition(), confidence_threshold=0.3,
        enhancement_applied=False, submitted_at=time.time(),
    )
    assert worker.submit(job) is True
    assert worker.submit(job) is False
    deadline = time.time() + 2
    packet = None
    while packet is None and time.time() < deadline:
        packet = worker.poll_latest()
        time.sleep(0.01)
    worker.stop()
    assert packet is not None
    assert detector.calls == 1
    assert packet.tracks[0].track_id == 7
    assert worker.queue_depth == 0
