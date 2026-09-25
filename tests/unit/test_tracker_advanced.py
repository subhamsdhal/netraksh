import os
import pytest
from unittest.mock import patch

from edge.detection.detector import DetectionTracker
from shared.schemas import SceneCondition
import numpy as np

@pytest.fixture
def dummy_frame():
    return np.zeros((640, 640, 3), dtype=np.uint8)

def test_detection_tracker_loads_bytetrack_default(monkeypatch):
    monkeypatch.setenv("TRACKER", "bytetrack")
    detector = DetectionTracker()
    assert "bytetrack_border.yaml" in detector.tracker_config or "bytetrack.yaml" in detector.tracker_config

def test_detection_tracker_loads_botsort(monkeypatch):
    monkeypatch.setenv("TRACKER", "botsort")
    detector = DetectionTracker()
    assert "botsort_border.yaml" in detector.tracker_config or "botsort.yaml" in detector.tracker_config

def test_detection_tracker_invalid_config_fallback(monkeypatch):
    monkeypatch.setenv("TRACKER", "botsort")
    # Even if botsort_border doesn't exist, it should fallback safely.
    detector = DetectionTracker(tracker_config="/fake/path/doesnt/exist.yaml")
    assert detector.tracker_config == "botsort.yaml"

def test_tracker_returns_unified_schema(dummy_frame):
    from pathlib import Path
    config_path = str(Path(__file__).resolve().parent.parent.parent / "edge" / "config" / "bytetrack_border.yaml")
    detector = DetectionTracker(model_size="yolov8n.pt", tracker_config=config_path)
    detector.load()
    
    # We won't find objects in a blank frame, but we can verify it doesn't crash 
    # and returns a list.
    tracks = detector.detect_and_track(dummy_frame, SceneCondition.CLEAR_DAY, 0.5)
    assert isinstance(tracks, list)
    assert len(tracks) == 0

    # Test botsort
    config_path_botsort = str(Path(__file__).resolve().parent.parent.parent / "edge" / "config" / "botsort_border.yaml")
    detector = DetectionTracker(model_size="yolov8n.pt", tracker_config=config_path_botsort)
    detector.load()
    tracks = detector.detect_and_track(dummy_frame, SceneCondition.CLEAR_DAY, 0.5)
    assert isinstance(tracks, list)
    assert len(tracks) == 0
