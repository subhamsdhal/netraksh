"""Camera 1 recovers a real ongoing person without spawning low-score ghosts."""

from types import SimpleNamespace
import time

import numpy as np

from edge.detection.detector import DetectionTracker, _NumpyByteTracker
from edge.detection.runtime import DetectionResult
from edge.main import EdgePipeline
from edge.tracking.hybrid_tracker import AsyncDetectorWorker, DetectorJob
from shared.constants import SceneCondition
from shared.schemas import BoundingBox


def _detection(x1, score):
    return DetectionResult(BoundingBox(x1=x1, y1=220, x2=x1 + 35, y2=330), score, 0)


def _detector(batches):
    detector = DetectionTracker.__new__(DetectionTracker)
    detector._tracker = None
    detector._numpy_tracker = _NumpyByteTracker({
        "track_high_thresh": 0.25,
        "track_low_thresh": 0.1,
        "new_track_thresh": 0.25,
        "match_thresh": 0.8,
    })
    detector._numpy_default_new_threshold = detector._numpy_tracker.new
    detector._runtime = SimpleNamespace(detect=lambda *_args: batches.pop(0))
    detector.last_raw_detections = []
    detector.last_tracker_output_count = 0
    detector.last_tracker_ms = 0.0
    return detector


def test_existing_person_survives_0_429_detection_but_new_low_score_box_is_rejected():
    detector = _detector([
        [_detection(500, 0.58)],
        [_detection(503, 0.429), _detection(38, 0.42)],
    ])
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    first = detector.detect_and_track(frame, SceneCondition.CLEAR_DAY, 0.4, new_track_threshold=0.45)
    second = detector.detect_and_track(frame, SceneCondition.CLEAR_DAY, 0.4, new_track_threshold=0.45)

    assert len(first) == len(second) == 1
    assert second[0].track_id == first[0].track_id
    assert second[0].confidence == 0.429
    assert detector.last_tracker_output_count == 1


def test_camera1_only_lowers_clear_day_cutoff_for_existing_tracks():
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.calibration = SimpleNamespace(get_threshold=lambda _condition: 0.45)
    pipeline.adapter = SimpleNamespace(source_kind="LOCAL_FINITE_FILE", preserve_finite_frames=True)
    pipeline.camera_id = "cam-border-01"
    assert pipeline._detector_confidence_threshold(SceneCondition.CLEAR_DAY) == 0.40
    assert pipeline._detector_new_track_threshold(SceneCondition.CLEAR_DAY) == 0.45

    pipeline.camera_id = "cam-checkpoint-01"
    assert pipeline._detector_confidence_threshold(SceneCondition.CLEAR_DAY) == 0.35
    assert pipeline._detector_new_track_threshold(SceneCondition.CLEAR_DAY) is None


def test_async_detector_forwards_camera1_new_track_gate():
    observed = []

    class FakeDetector:
        last_raw_detections = []
        last_tracker_output_count = 0
        last_tracker_ms = 0.0
        _runtime = None

        def detect_and_track(self, _frame, _condition, threshold, *, new_track_threshold):
            observed.append((threshold, new_track_threshold))
            return []

    worker = AsyncDetectorWorker(FakeDetector())
    frame = np.zeros((16, 16, 3), dtype=np.uint8)
    worker.start()
    try:
        assert worker.submit(DetectorJob(
            frame=frame,
            detector_frame=frame,
            frame_index=1,
            meta=None,
            health=None,
            condition=SimpleNamespace(condition=SceneCondition.CLEAR_DAY),
            confidence_threshold=0.40,
            enhancement_applied=False,
            submitted_at=time.time(),
            new_track_threshold=0.45,
        ))
        deadline = time.monotonic() + 2
        while not observed and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        worker.stop()
    assert observed == [(0.40, 0.45)]
