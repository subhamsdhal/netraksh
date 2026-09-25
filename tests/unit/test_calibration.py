"""
NETRAKSH — Unit tests for edge/detection/calibration.py
(CalibrationModule — per-condition confidence threshold fitting).

No test file existed for this module before this — it had never been
exercised by any real caller (see scripts/fit_detection_thresholds.py's
docstring for the first real attempt, and docs/LIMITATIONS.md for why it
found a real bug: fit() had no guard against a single-class labeled
dataset, which this project's own real, manually-reviewed fence-crossing
candidates turned out to be, across all three scene conditions).
"""
import numpy as np
import pytest

from edge.detection.calibration import CalibrationModule
from shared.constants import SceneCondition


class TestFitRefusesSingleClassLabels:
    """Real bug fix: fit() must not silently produce a meaningless
    threshold from a single-class labeled dataset."""

    def test_all_positive_labels_raises_instead_of_returning_a_threshold(self):
        cal = CalibrationModule()
        confidences = np.array([0.2, 0.4, 0.6, 0.8, 0.9])
        labels = np.array([1, 1, 1, 1, 1])
        with pytest.raises(ValueError):
            cal.fit(confidences, labels, SceneCondition.CLEAR_DAY)

    def test_all_negative_labels_raises_instead_of_returning_a_threshold(self):
        cal = CalibrationModule()
        confidences = np.array([0.2, 0.4, 0.6, 0.8, 0.9])
        labels = np.array([0, 0, 0, 0, 0])
        with pytest.raises(ValueError):
            cal.fit(confidences, labels, SceneCondition.FOG_RAIN)

    def test_refused_fit_leaves_thresholds_and_calibrated_state_unchanged(self):
        cal = CalibrationModule()
        prototype_threshold = cal.get_threshold(SceneCondition.CLEAR_DAY)
        assert cal.is_calibrated() is False

        confidences = np.array([0.2, 0.4, 0.6, 0.8, 0.9])
        labels = np.array([1, 1, 1, 1, 1])
        with pytest.raises(ValueError):
            cal.fit(confidences, labels, SceneCondition.CLEAR_DAY)

        assert cal.get_threshold(SceneCondition.CLEAR_DAY) == prototype_threshold
        assert cal.is_calibrated() is False


class TestFitWorksWithGenuineTwoClassData:
    """Regression protection: the original, real isotonic/Platt fitting
    logic must still work correctly once real negative examples exist —
    this predates the guard above and must not have been broken by it."""

    def test_isotonic_fit_returns_a_threshold_and_marks_calibrated(self):
        cal = CalibrationModule()
        rng = np.random.RandomState(0)
        # A separable synthetic case: low confidence -> false positive (0),
        # high confidence -> real detection (1).
        neg = rng.uniform(0.05, 0.35, size=30)
        pos = rng.uniform(0.55, 0.95, size=30)
        confidences = np.concatenate([neg, pos])
        labels = np.concatenate([np.zeros(30), np.ones(30)])

        threshold = cal.fit(confidences, labels, SceneCondition.CLEAR_DAY, method="isotonic")

        assert 0.1 <= threshold <= 0.95
        assert cal.is_calibrated() is True
        assert cal.get_threshold(SceneCondition.CLEAR_DAY) == threshold

    def test_platt_fit_returns_a_threshold_and_marks_calibrated(self):
        cal = CalibrationModule()
        rng = np.random.RandomState(1)
        neg = rng.uniform(0.05, 0.35, size=30)
        pos = rng.uniform(0.55, 0.95, size=30)
        confidences = np.concatenate([neg, pos])
        labels = np.concatenate([np.zeros(30), np.ones(30)])

        threshold = cal.fit(confidences, labels, SceneCondition.FOG_RAIN, method="platt")

        assert 0.1 <= threshold <= 0.95
        assert cal.is_calibrated() is True

    def test_unknown_method_raises(self):
        cal = CalibrationModule()
        confidences = np.array([0.2, 0.4, 0.6, 0.8])
        labels = np.array([0, 0, 1, 1])
        with pytest.raises(ValueError):
            cal.fit(confidences, labels, SceneCondition.CLEAR_DAY, method="not-a-real-method")


class TestPrototypeDefaults:
    def test_uncalibrated_module_reports_not_calibrated(self):
        cal = CalibrationModule()
        assert cal.is_calibrated() is False

    def test_unknown_condition_falls_back_to_default(self):
        cal = CalibrationModule()
        # get_threshold's own fallback (0.45) for a condition never registered.
        assert cal.get_threshold(None) == 0.45
