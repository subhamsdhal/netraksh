import os
import pytest
import numpy as np
from unittest.mock import Mock, patch
from collections import deque

from shared.constants import DetectionClass, EventType
from shared.schemas import TrackData, BoundingBox, Point
from edge.detection.anpr import (
    PlateCrop,
    OCRResult,
    HeuristicPlateLocalizer,
    PlateQualityFilter,
    OCRPreprocessor,
    EasyOCREngine,
    PlateNormalizer,
    TemporalOCRFusion,
    EnhancedANPRModule,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_frame():
    return np.zeros((1080, 1920, 3), dtype=np.uint8)

@pytest.fixture
def mock_track():
    return TrackData(
        track_id=1,
        detection_class=DetectionClass.VEHICLE,
        bbox=BoundingBox(x1=100.0, y1=100.0, x2=300.0, y2=200.0), # w=200, h=100
        confidence=0.9
    )

# ---------------------------------------------------------------------------
# Tests: Localizer
# ---------------------------------------------------------------------------

def test_heuristic_localizer_valid_crop(mock_track, mock_frame):
    localizer = HeuristicPlateLocalizer()
    crops = localizer.locate(mock_track, mock_frame)
    
    assert len(crops) == 1
    crop = crops[0]
    
    # Check dimensions
    # w=200, h=100. plate_x1 = 100 + 20 = 120. plate_x2 = 300 - 20 = 280
    # plate_y1 = 100 + 55 = 155. plate_y2 = 200
    assert crop.bbox.x1 == 120
    assert crop.bbox.x2 == 280
    assert crop.bbox.y1 == 155
    assert crop.bbox.y2 == 200
    assert crop.method == "heuristic"
    assert crop.confidence is None

def test_heuristic_localizer_out_of_bounds(mock_frame):
    track = TrackData(
        track_id=1,
        detection_class=DetectionClass.VEHICLE,
        bbox=BoundingBox(x1=-100.0, y1=-100.0, x2=0.0, y2=0.0),
        confidence=0.9
    )
    localizer = HeuristicPlateLocalizer()
    crops = localizer.locate(track, mock_frame)
    assert len(crops) == 0

# ---------------------------------------------------------------------------
# Tests: Quality Filter
# ---------------------------------------------------------------------------

def test_quality_filter_low_resolution():
    filter = PlateQualityFilter(min_width=50, min_height=20)
    small_crop = np.zeros((10, 30, 3), dtype=np.uint8)
    ok, reason = filter.check(small_crop)
    assert not ok
    assert reason == "LOW_RESOLUTION"

def test_quality_filter_extreme_aspect_ratio():
    filter = PlateQualityFilter(max_aspect_ratio=5.0)
    # w=100, h=10 -> aspect 10
    wide_crop = np.zeros((10, 100, 3), dtype=np.uint8)
    ok, reason = filter.check(wide_crop)
    assert not ok
    assert reason == "EXTREME_ASPECT_RATIO"

def test_quality_filter_low_contrast():
    filter = PlateQualityFilter(min_contrast=15.0)
    # Uniform gray image (std=0)
    flat_crop = np.full((50, 150, 3), 128, dtype=np.uint8)
    ok, reason = filter.check(flat_crop)
    assert not ok
    assert reason == "LOW_CONTRAST"

def test_quality_filter_ok():
    filter = PlateQualityFilter()
    # High contrast image
    good_crop = np.zeros((50, 150, 3), dtype=np.uint8)
    good_crop[:, 75:] = 255 # half black, half white
    ok, reason = filter.check(good_crop)
    assert ok
    assert reason is None

# ---------------------------------------------------------------------------
# Tests: Preprocessor
# ---------------------------------------------------------------------------

def test_ocr_preprocessor():
    crop = np.full((50, 150, 3), 128, dtype=np.uint8)
    processed = OCRPreprocessor.process(crop)
    
    assert len(processed.shape) == 2 # Grayscale
    assert processed.shape == (50, 150)
    assert processed.dtype == np.uint8

# ---------------------------------------------------------------------------
# Tests: Normalization
# ---------------------------------------------------------------------------

def test_plate_normalizer():
    assert PlateNormalizer.normalize("abc-123") == "ABC123"
    assert PlateNormalizer.normalize("  Gj .01 AB 1234  ") == "GJ01AB1234"

def test_plate_validation_is_plausibility_based(monkeypatch):
    monkeypatch.setenv("ANPR_OCR_MIN_CONFIDENCE", "0.55")
    assert PlateNormalizer.validation_status("OD 02 AB 1234", 0.87) == "VALID"
    assert PlateNormalizer.validation_status("BH-12-AB-1234", 0.80) == "VALID"
    assert PlateNormalizer.validation_status("AB", 0.99) == "INVALID"
    assert PlateNormalizer.validation_status("OD02AB1234", 0.20) == "LOW_CONFIDENCE"

# ---------------------------------------------------------------------------
# Tests: Temporal Fusion
# ---------------------------------------------------------------------------

def test_temporal_fusion_confirmed():
    fusion = TemporalOCRFusion(confirm_threshold=2)
    
    # 1st read
    res1 = fusion.add_observation(1, OCRResult("ABC1234", 0.8))
    assert res1["fusion_state"] == "TENTATIVE"
    
    # 2nd read (same)
    res2 = fusion.add_observation(1, OCRResult("abc-1234", 0.9))
    assert res2["fusion_state"] == "CONFIRMED"
    assert res2["text"] == "ABC1234"
    assert res2["conf"] == pytest.approx(0.85)
    assert res2["count"] == 2

def test_temporal_fusion_unstable():
    fusion = TemporalOCRFusion(confirm_threshold=2)
    
    res1 = fusion.add_observation(2, OCRResult("ABC1234", 0.8))
    res2 = fusion.add_observation(2, OCRResult("XYZ9999", 0.8))
    res3 = fusion.add_observation(2, OCRResult("FOO0000", 0.8))
    res4 = fusion.add_observation(2, OCRResult("BAR1111", 0.8))
    
    assert res4["fusion_state"] == "UNSTABLE"
    assert res4["count"] == 4

def test_temporal_fusion_cleanup():
    fusion = TemporalOCRFusion()
    fusion.add_observation(3, OCRResult("ABC1234", 0.8))
    assert 3 in fusion.history
    fusion.cleanup_track(3)
    assert 3 not in fusion.history

def test_temporal_fusion_bounded_memory():
    fusion = TemporalOCRFusion(max_history=3)
    fusion.add_observation(4, OCRResult("A", 0.9))
    fusion.add_observation(4, OCRResult("B", 0.9))
    fusion.add_observation(4, OCRResult("C", 0.9))
    fusion.add_observation(4, OCRResult("D", 0.9))
    
    # Should only keep last 3
    assert len(fusion.history[4]) == 3
    assert fusion.history[4][0].text == "B"

# ---------------------------------------------------------------------------
# Tests: Feature Flag Integration (in modules.py)
# ---------------------------------------------------------------------------

def test_anpr_module_legacy_fallback(monkeypatch, mock_track, mock_frame):
    monkeypatch.setenv("ANPR_PIPELINE", "legacy")
    from edge.rules.modules import ANPRModule
    from shared.schemas import ZoneSchema, Polygon, Point
    
    zone = ZoneSchema(
        camera_id="cam1", name="z1", zone_type="checkpoint", 
        owning_command_id="cmd1", polygon=Polygon(points=[
            Point(x=0.0, y=0.0), Point(x=1.0, y=0.0),
            Point(x=1.0, y=1.0), Point(x=0.0, y=1.0)
        ])
    )
    mod = ANPRModule([zone])
    assert mod._pipeline == "legacy"

def test_anpr_module_enhanced_mode(monkeypatch, mock_track, mock_frame):
    monkeypatch.setenv("ANPR_PIPELINE", "enhanced")
    from edge.rules.modules import ANPRModule
    from shared.schemas import ZoneSchema, Polygon, Point
    
    zone = ZoneSchema(
        camera_id="cam1", name="z1", zone_type="checkpoint", 
        owning_command_id="cmd1", polygon=Polygon(points=[
            Point(x=0.0, y=0.0), Point(x=1.0, y=0.0),
            Point(x=1.0, y=1.0), Point(x=0.0, y=1.0)
        ])
    )
    mod = ANPRModule([zone])
    assert mod._pipeline == "enhanced"
    
    # Mock the enhanced module's process
    mod._enhanced_module.process = Mock(return_value={
        "fusion_state": "CONFIRMED",
        "plate_text": "MOCK123",
        "plate_confidence": 0.99,
        "raw_plate_text": "MOCK 123",
        "normalized_plate_text": "MOCK123",
        "localization_confidence": None,
        "ocr_confidence": 0.99,
        "observations_count": 2,
        "processing_method": "easyocr+clahe",
    })
    
    res = mod.process(mock_track, mock_frame)
    assert res is not None
    assert res["plate_text"] == "MOCK123"
    assert res["fusion_state"] == "CONFIRMED"
    assert res["observations_count"] == 2
