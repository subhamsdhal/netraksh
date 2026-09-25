"""Controlled, non-sensitive low-light behavior checks.

These tests validate measured state transitions and noise gating; they are not
real-world night accuracy benchmarks.
"""
import numpy as np
from datetime import datetime

from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.detector import NightMotionFallback
from shared.schemas import EvidencePackage


def _frame(value: int, size=(160, 160)):
    return np.full((*size, 3), value, dtype=np.uint8)


def test_scene_classifier_exposes_day_low_and_very_low_states():
    classifier = SceneConditionClassifier("test-night")
    assert classifier.classify(_frame(180)).lighting_state == "DAYLIGHT"
    assert classifier.classify(_frame(45)).lighting_state == "LOW_LIGHT"
    assert classifier.classify(_frame(5)).lighting_state == "VERY_LOW_LIGHT"


def test_black_frame_is_low_light_not_camera_failure_signal():
    report = SceneConditionClassifier("test-night").classify(_frame(0))
    assert str(report.condition) == "LOW_LIGHT_NIGHT"
    assert report.lighting_state == "VERY_LOW_LIGHT"
    assert report.mean_luminance == 0.0


def test_motion_requires_temporal_persistence_and_reports_area():
    fallback = NightMotionFallback()
    base = _frame(8)
    moved = base.copy()
    moved[45:115, 45:115] = 120
    assert fallback.detect_motion_details(base)["motion"] is False
    first = fallback.detect_motion_details(moved, min_area=500, required_frames=2)
    assert first["motion"] is False
    moved_again = base.copy()
    moved_again[45:115, 50:120] = 120
    second = fallback.detect_motion_details(moved_again, min_area=500, required_frames=2)
    assert second["motion"] is True
    assert second["area"] >= 500
    assert second["persistence"] == 2


def test_static_dark_scene_rejects_noise_and_small_changes():
    fallback = NightMotionFallback()
    base = _frame(8)
    fallback.detect_motion_details(base)
    noisy = base.copy()
    noisy[10:14, 10:14] = 80
    result = fallback.detect_motion_details(noisy, min_area=500, required_frames=2)
    assert result["motion"] is False
    assert result["persistence"] == 0


def test_night_metadata_survives_evidence_schema_serialization():
    package = EvidencePackage(
        camera_id="cam-night", zone_id="default", detection_class="unknown",
        timestamp=datetime.utcnow(),
        confidence=0.0, scene_condition="LOW_LIGHT_NIGHT",
        camera_health_state="OK", decision_state="UNCERTAIN",
        lighting_state="VERY_LOW_LIGHT", mean_luminance=8.5,
        enhancement_applied=True, detection_method="MOTION_FALLBACK",
        motion_area=3195.0, motion_persistence=2,
    )
    data = package.model_dump()
    assert data["lighting_state"] == "VERY_LOW_LIGHT"
    assert data["detection_method"] == "MOTION_FALLBACK"
    assert data["motion_persistence"] == 2
