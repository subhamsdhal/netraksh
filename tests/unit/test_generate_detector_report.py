import pytest
import os
from generate_detector_report import generate_report

def test_generate_report_no_yolov8s():
    # Setup mock file system
    mock_data = {
        "docs/yolov8n_vtest.json": {
            "hardware": "win32",
            "config": {"confidence_threshold": 0.3},
            "latency": {"end_to_end": [0.048, 0.052, 0.05, 0.07]},
            "memory": {"rss_during_peak": 1024},
            "counts": {"objects_detected": 100},
            "tracking": {"tracks_created": 10, "tracks_terminated": 5, "continuity_interventions": 2},
            "pixel_area_distribution": {"small": 10, "medium": 50, "large": 40}
        },
        "docs/yolov8n_demo.json": {
            "hardware": "win32",
            "config": {"confidence_threshold": 0.3},
            "latency": {"end_to_end": [0.058, 0.062, 0.06, 0.08]},
            "memory": {"rss_during_peak": 1050},
            "counts": {"objects_detected": 150},
            "tracking": {"tracks_created": 15, "tracks_terminated": 7, "continuity_interventions": 3},
            "pixel_area_distribution": {"small": 20, "medium": 60, "large": 70}
        }
    }
    
    def mock_exists(path):
        if path == "yolov8s.pt": return False
        return path in mock_data
        
    def mock_read(path):
        return mock_data[path]
        
    mock_fs = {"exists": mock_exists, "read": mock_read}
    
    report = generate_report(mock_fs=mock_fs)
    
    # Assert specific required language is in the report
    assert "YOLOv8s: **NOT BENCHMARKED**" in report
    assert "Candidate weight yolov8s.pt was not available locally" in report
    assert "YOLOv8n remains the current default." in report
    assert "This is NOT a result proving YOLOv8n is superior to YOLOv8s." in report
    assert "NOT MEASURABLE" in report
    assert "**Precision**: NOT MEASURABLE" in report
    assert "TRACK FRAGMENTATION / REASSOCIATION PROXY, NOT ID SWITCH COUNT" in report
    assert "Pixel-area categories are merely size bins, NOT real-world distance categories" in report

def test_generate_report_missing_artifacts():
    def mock_exists(path):
        return False
        
    def mock_read(path):
        return {}
        
    mock_fs = {"exists": mock_exists, "read": mock_read}
    
    with pytest.raises(SystemExit):
        generate_report(mock_fs=mock_fs)
