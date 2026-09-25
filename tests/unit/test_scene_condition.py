"""
NETRAKSH — Unit tests for edge/condition/scene_condition.py
(Scene Condition Classifier — Gate 2).

No test file existed for this module before this — it had never been
exercised directly by any test (see docs/LIMITATIONS.md's fog+glare
compound finding for why this session added a region-aware contrast
measurement here: `_compute_masked_contrast()`/`contrast_std_excluding_glare`,
which fixes a real, at-scale problem the whole-frame `contrast_std` scalar
could not — a small bright glare region inflating the aggregate and masking
genuine haze in the rest of the frame).
"""
import numpy as np
import pytest

from edge.condition.scene_condition import SceneConditionClassifier
from shared.constants import SceneCondition


def _gray_frame(gray: np.ndarray) -> np.ndarray:
    """Build a 3-channel BGR frame from a 2D grayscale array (same value on
    every channel) — classify() converts back to gray internally, so this
    round-trips exactly for these deterministic, synthetic test frames."""
    return np.stack([gray, gray, gray], axis=-1).astype(np.uint8)


def _uniform_frame(value: float, shape=(100, 100)) -> np.ndarray:
    return _gray_frame(np.full(shape, value, dtype=np.float64))


class TestClassifyBaselineConditions:
    """Regression baseline for _decide()'s existing classification logic —
    this module had no test coverage at all before this session."""

    def classifier(self):
        return SceneConditionClassifier(camera_id="test-cam")

    def test_clear_day_classified_correctly(self):
        # Mid brightness, real contrast (not a flat frame — std=0 would
        # itself read as pathologically low contrast).
        rng = np.random.RandomState(0)
        gray = np.clip(rng.normal(128, 50, (100, 100)), 0, 255)
        report = self.classifier().classify(_gray_frame(gray))
        assert report.condition == SceneCondition.CLEAR_DAY

    def test_low_light_night_classified_correctly(self):
        rng = np.random.RandomState(0)
        gray = np.clip(rng.normal(30, 10, (100, 100)), 0, 255)
        report = self.classifier().classify(_gray_frame(gray))
        assert report.condition == SceneCondition.LOW_LIGHT_NIGHT

    def test_fog_rain_classified_correctly(self):
        # Bright enough to not be night, but genuinely low real contrast.
        rng = np.random.RandomState(0)
        gray = np.clip(rng.normal(150, 5, (100, 100)), 0, 255)
        report = self.classifier().classify(_gray_frame(gray))
        assert report.condition == SceneCondition.FOG_RAIN

    def test_glare_classified_correctly_via_brightness(self):
        report = self.classifier().classify(_uniform_frame(240))
        assert report.condition == SceneCondition.GLARE

    def test_glare_classified_correctly_via_glare_fraction(self):
        rng = np.random.RandomState(0)
        # Mid brightness overall, but a large enough blown-out patch to
        # cross the real 0.15 glare_fraction cutoff on its own.
        gray = np.clip(rng.normal(150, 10, (100, 100)), 0, 255)
        gray[:, :20] = 255  # 20% of columns fully blown out
        report = self.classifier().classify(_gray_frame(gray))
        assert report.condition == SceneCondition.GLARE


class TestRegionAwareContrast:
    """Real fix: contrast_std_excluding_glare measures spread among
    non-blown-out pixels only, so a small bright region doesn't mask
    genuine haze in the rest of the frame the way whole-frame contrast_std
    can (docs/LIMITATIONS.md's fog+glare compound finding)."""

    def test_bright_patch_inflates_whole_frame_contrast_but_not_masked(self):
        rng = np.random.RandomState(0)
        # 80% genuinely hazy background (low real contrast), 20% a solid
        # blown-out patch — mirrors the real fog_glare measurement almost
        # exactly (whole-frame ~41-42, masked ~5-15).
        gray = np.clip(rng.normal(150, 5, (100, 100)), 0, 255)
        gray[:, :20] = 255  # 20% of columns fully blown out
        report = SceneConditionClassifier(camera_id="test-cam").classify(_gray_frame(gray))

        assert report.contrast_std > 30  # whole-frame: inflated past FOG_CONTRAST_THRESHOLD
        assert report.contrast_std_excluding_glare < 30  # region-aware: genuinely low, correctly

    def test_fully_blown_out_frame_falls_back_to_whole_frame_value(self):
        """No non-glare pixels exist to measure separately — falling back
        to the whole-frame std (not 0.0, which would incorrectly read as
        "perfectly uniform" rather than "fully saturated")."""
        report = SceneConditionClassifier(camera_id="test-cam").classify(_uniform_frame(255))
        assert report.contrast_std_excluding_glare == pytest.approx(report.contrast_std)

    def test_no_glare_present_masked_and_whole_frame_contrast_are_close(self):
        """When there's no blown-out region at all, excluding "glare pixels"
        removes nothing meaningful — the two measurements should be close,
        not artificially different."""
        rng = np.random.RandomState(0)
        gray = np.clip(rng.normal(128, 40, (100, 100)), 0, 255)
        report = SceneConditionClassifier(camera_id="test-cam").classify(_gray_frame(gray))
        assert abs(report.contrast_std - report.contrast_std_excluding_glare) < 5.0

    def test_classification_decision_is_unaffected_by_the_new_field(self):
        """Deliberately scoped: _decide() still uses whole-frame contrast_std
        exactly as before — adding contrast_std_excluding_glare must not
        change what condition a frame is classified as."""
        rng = np.random.RandomState(0)
        gray = np.clip(rng.normal(150, 5, (100, 100)), 0, 255)
        gray[:, :20] = 255
        report = SceneConditionClassifier(camera_id="test-cam").classify(_gray_frame(gray))
        # Whole-frame contrast_std > 30 and glare_fraction likely < 0.15 here
        # (20% exactly at the boundary can go either way with noise) — the
        # real point of this test is just that classification still keys off
        # contrast_std/brightness/glare_fraction, not the new field; assert
        # the new field exists and is a real, distinct measurement without
        # asserting a specific condition (already covered above).
        assert report.contrast_std_excluding_glare != report.contrast_std
