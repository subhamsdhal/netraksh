import os
import pytest
from unittest.mock import patch, mock_open

from shared.constants import CameraHealthState, SceneCondition, DecisionState, HealthReason
from shared.schemas import CameraHealthReport, SceneConditionReport
from edge.reliability.decision import (
    LegacyReliabilityEngine,
    CalibratedReliabilityEngine,
    get_reliability_engine,
    make_reliability_decision,
)


@pytest.fixture
def dummy_health_ok():
    return CameraHealthReport(camera_id="cam1", health_state=CameraHealthState.OK, health_reason=HealthReason.OK)


@pytest.fixture
def dummy_health_failed():
    return CameraHealthReport(camera_id="cam1", health_state=CameraHealthState.FAILED, health_reason=HealthReason.STREAM_UNAVAILABLE)


@pytest.fixture
def dummy_condition_clear():
    return SceneConditionReport(
        camera_id="cam1",
        condition=SceneCondition.CLEAR_DAY,
        brightness_mean=128.0,
        contrast_std=60.0,
        glare_fraction=0.0,
    )


def test_legacy_reliability_engine(dummy_health_ok, dummy_condition_clear):
    engine = LegacyReliabilityEngine()
    
    # Perfect scenario (D=1.0, T=1.0, S=1.0, H=1.0) => R = 1.0
    result = engine.evaluate(
        health_report=dummy_health_ok,
        condition_report=dummy_condition_clear,
        detector_confidence=1.0,
        calibration_threshold=0.5,
        temporal_score=1.0,
    )
    assert result.decision_state == DecisionState.DETECTED
    assert result.score_r == 1.0


@patch("os.path.exists", return_value=False)
def test_calibrated_engine_missing_model_fallback(mock_exists, dummy_health_ok, dummy_condition_clear):
    engine = CalibratedReliabilityEngine(model_path="non_existent_model.pkl")
    assert engine.model is None
    
    result = engine.evaluate(
        health_report=dummy_health_ok,
        condition_report=dummy_condition_clear,
        detector_confidence=0.9,
        calibration_threshold=0.5,
        temporal_score=1.0,
    )
    
    assert result.decision_state == DecisionState.UNCERTAIN
    assert "CALIBRATED_ENGINE_UNAVAILABLE" in result.decision_reason
    assert result.score_r is None


def test_gate1_hard_override(dummy_health_failed, dummy_condition_clear):
    # Regardless of the engine, Gate 1 MUST force ABSTAIN.
    # The make_reliability_decision wrapper enforces this before engines are even called.
    result = make_reliability_decision(
        health_report=dummy_health_failed,
        condition_report=dummy_condition_clear,
        detector_confidence=0.99,  # Strong detection
        calibration_threshold=0.5,
        temporal_score=1.0,  # Strong temporal consistency
    )
    
    assert result.decision_state == DecisionState.ABSTAIN
    assert "CAMERA_FAILED" in result.decision_reason


@patch.dict(os.environ, {"RELIABILITY_ENGINE": "calibrated"})
@patch("os.path.exists", return_value=False)
def test_factory_selection(mock_exists):
    engine = get_reliability_engine()
    assert isinstance(engine, CalibratedReliabilityEngine)


@patch.dict(os.environ, {"RELIABILITY_ENGINE": "legacy"})
def test_factory_selection_legacy():
    engine = get_reliability_engine()
    assert isinstance(engine, LegacyReliabilityEngine)


@patch.dict(os.environ, {"RELIABILITY_ENGINE": "invalid_value"})
def test_factory_selection_fallback():
    engine = get_reliability_engine()
    assert isinstance(engine, LegacyReliabilityEngine)
