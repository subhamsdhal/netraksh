"""
NETRAKSH — Unit tests for edge/condition/preprocessing.py
(CLAHE preprocessing — architecture v4 §3).
"""
import numpy as np
import os
import pytest

from edge.condition.preprocessing import enhance_for_detection, ConditionProcessingPolicy, ConditionRouter
from shared.constants import SceneCondition


def _dark_frame(shape=(64, 64, 3)) -> np.ndarray:
    """A low-contrast, dark synthetic frame — the kind CLAHE should visibly change."""
    rng = np.random.RandomState(42)
    return (rng.rand(*shape) * 40).astype(np.uint8)  # values in [0, 40) — dark, low contrast


class TestConditionGating:
    def test_clear_day_returns_frame_unchanged(self):
        frame = _dark_frame()
        result = enhance_for_detection(frame, ConditionProcessingPolicy.STANDARD)
        assert result is frame  # same object — no copy, no processing

    def test_glare_returns_frame_unchanged(self):
        frame = _dark_frame()
        result = enhance_for_detection(frame, ConditionProcessingPolicy.GLARE_AWARE)
        assert result is frame

    def test_low_light_night_is_enhanced(self):
        frame = _dark_frame()
        result = enhance_for_detection(frame, ConditionProcessingPolicy.LOW_LIGHT)
        assert result is not frame  # a genuinely new array
        assert result.shape == frame.shape
        assert result.dtype == frame.dtype

    def test_fog_rain_is_enhanced(self):
        frame = _dark_frame()
        result = enhance_for_detection(frame, ConditionProcessingPolicy.ADVERSE_WEATHER)
        assert result is not frame
        assert result.shape == frame.shape


class TestEnhancementEffect:
    def test_enhancement_increases_contrast_on_a_dark_frame(self):
        """The actual point of CLAHE: a dark, low-contrast frame should come
        out with meaningfully higher pixel-value spread."""
        frame = _dark_frame()
        enhanced = enhance_for_detection(frame, ConditionProcessingPolicy.LOW_LIGHT)
        assert float(np.std(enhanced)) > float(np.std(frame))

    def test_does_not_mutate_the_input_frame(self):
        frame = _dark_frame()
        original_copy = frame.copy()
        enhance_for_detection(frame, ConditionProcessingPolicy.LOW_LIGHT)
        assert np.array_equal(frame, original_copy)

    def test_preserves_spatial_dimensions_for_bbox_coordinate_validity(self):
        """Detector output bboxes must remain valid against the ORIGINAL
        frame's coordinate space — this only holds if CLAHE never resizes."""
        frame = _dark_frame(shape=(100, 200, 3))
        enhanced = enhance_for_detection(frame, ConditionProcessingPolicy.ADVERSE_WEATHER)
        assert enhanced.shape[:2] == frame.shape[:2]


class TestConditionRouter:
    @pytest.fixture(autouse=True)
    def restore_env(self):
        original = os.environ.get("ADVERSE_PROCESSING")
        yield
        if original is None:
            os.environ.pop("ADVERSE_PROCESSING", None)
        else:
            os.environ["ADVERSE_PROCESSING"] = original

    def test_router_disabled_mode(self):
        os.environ["ADVERSE_PROCESSING"] = "disabled"
        router = ConditionRouter()
        assert router.route(SceneCondition.LOW_LIGHT_NIGHT) == ConditionProcessingPolicy.STANDARD
        assert router.route(SceneCondition.CLEAR_DAY) == ConditionProcessingPolicy.STANDARD

    def test_router_adaptive_mode(self):
        os.environ["ADVERSE_PROCESSING"] = "adaptive"
        router = ConditionRouter()
        assert router.route(SceneCondition.LOW_LIGHT_NIGHT) == ConditionProcessingPolicy.LOW_LIGHT
        assert router.route(SceneCondition.FOG_RAIN) == ConditionProcessingPolicy.ADVERSE_WEATHER
        assert router.route(SceneCondition.GLARE) == ConditionProcessingPolicy.GLARE_AWARE
        assert router.route(SceneCondition.CLEAR_DAY) == ConditionProcessingPolicy.STANDARD

    def test_router_invalid_mode_defaults_to_disabled(self):
        os.environ["ADVERSE_PROCESSING"] = "foo"
        router = ConditionRouter()
        assert router.mode == "disabled"
        assert router.route(SceneCondition.LOW_LIGHT_NIGHT) == ConditionProcessingPolicy.STANDARD
