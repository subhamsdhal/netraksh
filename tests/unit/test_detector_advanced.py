import pytest
import os
import numpy as np
from unittest.mock import patch, MagicMock
from edge.detection.detector import DetectionTracker
from shared.schemas import TrackData, BoundingBox

def test_detector_model_selection_default():
    if "DETECTOR_MODEL" in os.environ:
        del os.environ["DETECTOR_MODEL"]
    
    detector = DetectionTracker()
    assert detector.model_size == "yolov8n.pt"

def test_detector_model_selection_override():
    os.environ["DETECTOR_MODEL"] = "yolov8s.pt"
    detector = DetectionTracker()
    assert detector.model_size == "yolov8s.pt"
    del os.environ["DETECTOR_MODEL"]

def test_missing_weight_file_blocks_download(monkeypatch):
    monkeypatch.setenv("DETECTOR_MODEL", "nonexistent_model_123.pt")
    detector = DetectionTracker()
    
    with pytest.raises(FileNotFoundError, match="Model artifact unavailable.*"):
        detector.load()

def test_output_schema_compatibility():
    detector = DetectionTracker("dummy.pt")
    
    mock_runtime = MagicMock()
    # Mock return from detect()
    mock_detection = MagicMock()
    mock_detection.bbox.x1 = 10
    mock_detection.bbox.y1 = 10
    mock_detection.bbox.x2 = 100
    mock_detection.bbox.y2 = 100
    mock_detection.confidence = 0.9
    mock_detection.class_id = 0
    mock_runtime.detect.return_value = [mock_detection]
    detector._runtime = mock_runtime
    
    mock_tracker = MagicMock()
    mock_tracked = MagicMock()
    mock_tracked.tlbr = [10, 10, 100, 100]
    mock_tracked.track_id = 1
    mock_tracked.cls = 0
    mock_tracked.score = 0.9
    mock_tracker.update.return_value = [mock_tracked]
    detector._tracker = mock_tracker
    
    frame = np.zeros((640, 640, 3), dtype=np.uint8)
    tracks = detector.detect_and_track(frame, "DAY_CLEAR", 0.3)
    
    assert len(tracks) == 1
    assert isinstance(tracks[0], TrackData)
    assert tracks[0].track_id == 1
    assert tracks[0].bbox.x1 == 10
    
