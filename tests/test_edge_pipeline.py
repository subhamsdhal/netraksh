from edge.reliability.decision import make_reliability_decision
from shared.schemas import CameraHealthReport, SceneConditionReport
from shared.constants import CameraHealthState, SceneCondition, HealthReason

def test_edge_reliability_engine_bounds():
    rel = make_reliability_decision(
        health_report=CameraHealthReport(
            camera_id="cam_01", health_state=CameraHealthState.OK, health_reason=HealthReason.OK
        ),
        condition_report=SceneConditionReport(
            camera_id="cam_01", condition=SceneCondition.CLEAR_DAY, brightness_mean=100.0, contrast_std=50.0, glare_fraction=0.0
        ),
        detector_confidence=0.8,
        calibration_threshold=0.5,
        temporal_score=0.9
    )
    assert 0.0 <= rel.score_r <= 1.0

def test_edge_engine_failure_gates():
    rel = make_reliability_decision(
        health_report=CameraHealthReport(
            camera_id="cam_01", health_state=CameraHealthState.FAILED, health_reason=HealthReason.FROZEN_STREAM
        ),
        condition_report=SceneConditionReport(
            camera_id="cam_01", condition=SceneCondition.CLEAR_DAY, brightness_mean=100.0, contrast_std=50.0, glare_fraction=0.0
        ),
        detector_confidence=0.9,
        calibration_threshold=0.5,
        temporal_score=1.0
    )
    # Failed health or abstention logic should result in None for score_r or 0.0
    assert rel.score_r is None or rel.score_r == 0.0
