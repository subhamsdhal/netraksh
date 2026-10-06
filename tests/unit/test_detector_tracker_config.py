"""
NETRAKSH — Unit tests for DetectionTracker's tracker-config resolution
(architecture v4 §4 — the border-tuned bytetrack.yaml wiring).
Does not exercise YOLO/ultralytics itself — DetectionTracker.__init__ never
touches ultralytics; that only happens in .load().
"""
import os

from edge.detection.detector import (
    DetectionTracker,
    _DEFAULT_TRACKER_CONFIG,
    _NumpyByteTracker,
)
from edge.detection.runtime import DetectionResult
from shared.schemas import BoundingBox


class TestTrackerConfigResolution:
    def test_default_config_resolves_to_border_tuned_yaml(self):
        tracker = DetectionTracker()
        assert tracker.tracker_config == _DEFAULT_TRACKER_CONFIG
        assert os.path.exists(tracker.tracker_config)
        assert tracker.tracker_config.endswith("bytetrack_border.yaml")

    def test_default_config_path_is_absolute(self):
        assert os.path.isabs(_DEFAULT_TRACKER_CONFIG)

    def test_explicit_config_path_is_used_when_it_exists(self, tmp_path):
        custom = tmp_path / "custom_tracker.yaml"
        custom.write_text("tracker_type: bytetrack\ntrack_buffer: 999\n")
        tracker = DetectionTracker(tracker_config=str(custom))
        assert tracker.tracker_config == str(custom)

    def test_missing_explicit_config_falls_back_to_bundled_default(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.yaml")
        tracker = DetectionTracker(tracker_config=missing)
        assert tracker.tracker_config == "bytetrack.yaml"  # ultralytics' own bundled default

    def test_border_tuned_yaml_has_a_larger_track_buffer_than_ultralytics_default(self):
        """Sanity-check the actual shipped value, not just that the file exists."""
        with open(_DEFAULT_TRACKER_CONFIG) as f:
            content = f.read()
        assert "track_buffer: 120" in content  # ultralytics' own default is 30


class TestNumpyByteTrackerAssociation:
    def test_match_thresh_is_a_cost_limit_for_moving_detections(self):
        tracker = _NumpyByteTracker({
            "track_high_thresh": 0.25,
            "track_low_thresh": 0.1,
            "new_track_thresh": 0.25,
            "track_buffer": 120,
            "match_thresh": 0.8,
        })
        first = DetectionResult(BoundingBox(x1=100, y1=100, x2=200, y2=300), 0.9, 0)
        shifted = DetectionResult(BoundingBox(x1=120, y1=100, x2=220, y2=300), 0.9, 0)

        initial_tracks = tracker.update([first])
        next_tracks = tracker.update([shifted])

        assert len(initial_tracks) == len(next_tracks) == 1
        assert next_tracks[0].track_id == initial_tracks[0].track_id

    def test_class_mismatch_does_not_reuse_a_track(self):
        tracker = _NumpyByteTracker({"match_thresh": 0.8})
        person = DetectionResult(BoundingBox(x1=100, y1=100, x2=200, y2=300), 0.9, 0)
        vehicle = DetectionResult(BoundingBox(x1=100, y1=100, x2=200, y2=300), 0.9, 2)

        initial_tracks = tracker.update([person])
        next_tracks = tracker.update([vehicle])

        assert len(initial_tracks) == len(next_tracks) == 1
        assert next_tracks[0].track_id != initial_tracks[0].track_id
