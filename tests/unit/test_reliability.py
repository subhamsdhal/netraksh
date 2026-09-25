"""
NETRAKSH — Unit tests for the Hybrid Reliability Decision Layer.
These are the most critical tests in the system — the core correctness guarantee.
All branches must pass.
"""
import pytest

from shared.constants import CameraHealthState, DecisionState, FOG_CONTRAST_THRESHOLD, HealthReason, SceneCondition
from shared.schemas import CameraHealthReport, SceneConditionReport
from edge.reliability.decision import (
    make_reliability_decision,
    make_abstain,
    make_uncertain,
    _scene_quality_score,
    _SCENE_CONTRAST_GOOD_NIGHT,
    RELIABILITY_R_THRESHOLD,
    RELIABILITY_WEIGHT_D,
    RELIABILITY_WEIGHT_T,
    RELIABILITY_WEIGHT_S,
    RELIABILITY_WEIGHT_H,
)
from datetime import datetime


def _health(state: CameraHealthState, reason: HealthReason = HealthReason.OK) -> CameraHealthReport:
    return CameraHealthReport(
        camera_id="test-cam",
        health_state=state,
        health_reason=reason,
        health_timestamp=datetime.utcnow(),
    )


def _condition(cond: SceneCondition = SceneCondition.CLEAR_DAY) -> SceneConditionReport:
    return SceneConditionReport(
        camera_id="test-cam",
        condition=cond,
        brightness_mean=128.0,
        contrast_std=50.0,
        glare_fraction=0.01,
    )


def _condition_with(
    cond: SceneCondition,
    contrast_std: float,
    brightness_mean: float = 128.0,
    glare_fraction: float = 0.0,
    contrast_std_excluding_glare: "float | None" = None,
) -> SceneConditionReport:
    """Like _condition(), but with explicit control over contrast_std —
    used to isolate _scene_quality_score's per-condition contrast reference.
    contrast_std_excluding_glare defaults to None (matching the schema
    default), so existing calls that don't care about the region-aware
    contrast fix are unaffected — decision.py falls back to contrast_std."""
    return SceneConditionReport(
        camera_id="test-cam",
        condition=cond,
        brightness_mean=brightness_mean,
        contrast_std=contrast_std,
        contrast_std_excluding_glare=contrast_std_excluding_glare,
        glare_fraction=glare_fraction,
    )


THRESHOLD = 0.45  # example calibrated threshold


class TestGate1HealthFailed:
    """Gate 1: FAILED → always ABSTAIN regardless of gates 2/3."""

    def test_failed_clear_day_high_confidence(self):
        """Even with perfect conditions and high confidence, FAILED = ABSTAIN."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.99,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.ABSTAIN
        assert "CAMERA_FAILED" in result.decision_reason
        assert result.camera_health == CameraHealthState.FAILED

    def test_failed_night_zero_confidence(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.STREAM_UNAVAILABLE),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.0,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.ABSTAIN

    def test_failed_fog_medium_confidence(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.CLOCK_DRIFT),
            condition_report=_condition(SceneCondition.FOG_RAIN),
            detector_confidence=0.50,
            calibration_threshold=0.35,
        )
        assert result.decision_state == DecisionState.ABSTAIN

    def test_failed_reason_in_decision_reason(self):
        """Decision reason must include the health failure reason for explainability."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(),
            detector_confidence=0.95,
            calibration_threshold=THRESHOLD,
        )
        assert "frozen_stream" in result.decision_reason.lower() or "FROZEN" in result.decision_reason


class TestHybridEngineBasicBanding:
    """
    Below Gate 1: R = wD*D + wT*T + wS*S + wH*H, banded against
    RELIABILITY_R_THRESHOLD. `_condition()`'s default fixture
    (brightness=128, contrast=50, glare=0.01) scores S≈0.933, and T defaults
    to a neutral 1.0 when the caller passes no track context — these tests
    don't pass temporal_score, matching every existing call site that
    hasn't been upgraded to compute it yet.
    """

    def test_below_threshold_returns_uncertain(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.30,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN
        # applied_threshold still echoes what was passed in, for context/display —
        # it no longer drives the DETECTED/UNCERTAIN split (RELIABILITY_R_THRESHOLD does).
        assert result.applied_threshold == THRESHOLD

    def test_exactly_at_old_threshold_still_detects_under_new_formula(self):
        """Coincidence worth locking in with a test: D=0.45 with the default
        S/H/T context happens to land R just above RELIABILITY_R_THRESHOLD
        (0.75) too, so this boundary case keeps its original DETECTED outcome."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=THRESHOLD,  # 0.45
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_above_threshold_ok_camera_returns_detected(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.80,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED
        assert result.camera_health == CameraHealthState.OK

    def test_above_threshold_degraded_camera_returns_detected_flagged(self):
        """DEGRADED camera (H=0.5 instead of 1.0) with strong confidence can
        still reach DETECTED — flagged — because D/T/S together still clear
        RELIABILITY_R_THRESHOLD despite the lower H contribution."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.80,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED
        assert result.camera_health == CameraHealthState.DEGRADED
        assert "DEGRADED" in result.decision_reason

    def test_r_below_threshold_reason_reports_all_four_factors(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.10,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN
        for factor in ("D=", "T=", "S=", "H="):
            assert factor in result.decision_reason


class TestHybridEngineIntentionalNightBehaviorChange:
    """
    INTENTIONAL BEHAVIOR CHANGE from the original 3-gate cascade: a lower
    per-condition confidence threshold used to make night detections easier
    to accept. Under the Hybrid Engine, degraded scene quality instead
    REDUCES R (via S), making night detections require the SAME evidentiary
    bar as day, not an easier one — consistent with the project's own thesis
    that the system should trust itself LESS under degraded conditions, not
    accept weaker evidence as normal. See docs/ARCHITECTURE.md.

    This replaces the old `test_night_condition_uses_lower_threshold`, whose
    premise (a lower threshold makes night detection easier) is exactly what
    this change retires.
    """

    def test_moderate_night_confidence_that_used_to_detect_is_now_uncertain(self):
        """Same inputs as the retired test: confidence=0.35 with a
        night-specific (lower) calibration_threshold=0.30 used to DETECT.
        Under the hybrid formula it correctly requires more evidence."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.35,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.UNCERTAIN
        assert result.scene_condition == SceneCondition.LOW_LIGHT_NIGHT

    def test_low_night_confidence_remains_uncertain(self):
        """This boundary case's outcome is unchanged by the new formula."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.20,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_strong_night_confidence_still_detects(self):
        """The bar isn't impossible at night — sufficiently strong confidence
        (or, in the real pipeline, sustained temporal confirmation raising T)
        still clears RELIABILITY_R_THRESHOLD."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.95,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.DETECTED


class TestWeatherExplainedBlurDoesNotDoublePenalize:
    """
    Real fix for a real, measured failure mode (docs/PERFORMANCE_REPORT.md's
    "Reliability Engine behavior under real night/fog conditions"): a real
    fog/night scene genuinely reduces both S (via its own contrast/
    brightness measurement) AND the camera health monitor's Laplacian blur
    score, which used to also halve H — double-counting one real
    visual-softening signal as two independent penalties. All four cases
    below share D=0.50, T=1.0 (default), and the same S fixture (S≈0.933)
    — chosen so DETECTED vs UNCERTAIN is decided purely by whether H is
    penalized, isolating exactly what this fix changes.
    """

    def test_excessive_blur_during_fog_is_not_health_penalized(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.FOG_RAIN),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_excessive_blur_during_night_is_not_health_penalized(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_excessive_blur_during_clear_day_is_still_fully_penalized(self):
        """The exemption is scoped to weather conditions only — the same
        blur during CLEAR_DAY has no scene-quality explanation for it (more
        likely a genuinely dirty/defocused lens), so H stays fully
        penalized, exactly as before this fix."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_other_degraded_reasons_during_fog_are_still_fully_penalized(self):
        """The exemption is scoped to EXCESSIVE_BLUR specifically — a health
        problem unrelated to weather (e.g. a frozen stream) happening to
        coincide with a foggy scene is still a real, independent problem and
        must still penalize H."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(SceneCondition.FOG_RAIN),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN


class TestWeatherExplainedExposureDoesNotDoublePenalize:
    """
    Real follow-up fix, same pattern and reason/condition-pair mapping as
    TestWeatherExplainedBlurDoesNotDoublePenalize above
    (docs/PERFORMANCE_REPORT.md's "Reliability Engine behavior under real
    night/fog/glare conditions"): a real glare scene genuinely reduces S
    (via glare_fraction) AND genuinely trips the camera health monitor's
    exposure-clipping check (a real, unrelated camera-fault detector) into
    ABNORMAL_EXPOSURE, which used to also halve H for the exact same real
    overexposure signal — measured at 0/55 (0%) DETECTED before this fix.
    """

    def test_abnormal_exposure_during_glare_is_not_health_penalized(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.ABNORMAL_EXPOSURE),
            condition_report=_condition(SceneCondition.GLARE),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_abnormal_exposure_during_clear_day_is_still_fully_penalized(self):
        """The exemption is scoped to GLARE only — the same exposure fault
        during CLEAR_DAY has no scene-quality explanation for it (more
        likely a genuinely malfunctioning auto-exposure/sensor), so H stays
        fully penalized, exactly as before this fix."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.ABNORMAL_EXPOSURE),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_excessive_blur_during_glare_is_still_fully_penalized(self):
        """The mapping is per (reason, condition) PAIR, not per condition
        alone — EXCESSIVE_BLUR is not one of GLARE's explained reasons (only
        ABNORMAL_EXPOSURE is), so it must still penalize H even under GLARE."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.GLARE),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_other_degraded_reasons_during_glare_are_still_fully_penalized(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(SceneCondition.GLARE),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN


class TestWeatherExplainedBlurByRealContrastNotJustLabel:
    """
    Real, at-scale follow-up fix (docs/LIMITATIONS.md, docs/PERFORMANCE_REPORT.md's
    fog+glare compound finding): a real fog+glare compound scene is
    classified GLARE alone (GLARE's classification check runs first), so the
    label-keyed EXCESSIVE_BLUR exemption above (scoped to FOG_RAIN/
    LOW_LIGHT_NIGHT) cannot see the real, co-occurring fog that is the
    actual blur cause. Measured at real scale, not a small sample:
    EXCESSIVE_BLUR fired on 246/260 (95%) real frames of a real fog+glare
    compound test. This checks the REAL measured contrast_std directly
    (against the same real FOG_CONTRAST_THRESHOLD already used elsewhere)
    instead of relying solely on which label won the classification.
    """

    def test_excessive_blur_during_glare_with_fog_like_contrast_is_not_health_penalized(self):
        """The scene is classified GLARE, but its REAL contrast is already
        fog-like (below FOG_CONTRAST_THRESHOLD) — the genuine, physical
        cause of the blur, even though the label can't say so."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition_with(
                SceneCondition.GLARE, contrast_std=FOG_CONTRAST_THRESHOLD - 5.0, brightness_mean=128.0
            ),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_excessive_blur_during_glare_with_normal_contrast_is_still_fully_penalized(self):
        """The exemption is scoped to genuinely fog-like contrast — a real
        dirty/defocused lens during real glare, where contrast is normal to
        high (measured 55-94 across every real glare candidate this
        session, never fog-like), must still fully penalize H. This is the
        exact real scenario the label-only exemption was deliberately NOT
        extended to cover (see TestWeatherExplainedExposureDoesNotDoublePenalize
        above)."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition_with(
                SceneCondition.GLARE, contrast_std=FOG_CONTRAST_THRESHOLD + 25.0, brightness_mean=128.0
            ),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_contrast_based_exemption_does_not_affect_other_degraded_reasons(self):
        """Scoped to EXCESSIVE_BLUR specifically — ABNORMAL_EXPOSURE or any
        other DEGRADED reason must not be exempted just because contrast
        happens to be low; that would be a real, independent problem the
        real fog-like contrast doesn't explain on its own (contrast dropping
        does not itself explain, say, a frozen stream)."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.FROZEN_STREAM),
            condition_report=_condition_with(
                SceneCondition.GLARE, contrast_std=FOG_CONTRAST_THRESHOLD - 5.0, brightness_mean=128.0
            ),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN


class TestWeatherExplainedBlurUsesRegionAwareContrast:
    """
    Real fix for a real, honest gap in the fix above (docs/LIMITATIONS.md,
    docs/PERFORMANCE_REPORT.md's fog+glare compound finding): the WHOLE-
    FRAME contrast_std check above was found NOT to catch the real
    fog_glare scenario it was built for, because a small bright glare
    region inflates the aggregate contrast_std past FOG_CONTRAST_THRESHOLD
    even though the non-glare majority of the frame is genuinely hazy.
    edge/condition/scene_condition.py now computes
    contrast_std_excluding_glare (spread among non-blown-out pixels only),
    and _health_quality_score uses THAT for this exemption when available.
    """

    def test_exemption_fires_on_region_aware_contrast_even_when_whole_frame_contrast_is_high(self):
        """The exact real fog_glare shape: contrast_std is high (a bright
        glare region inflated it — NOT exempted under the old, whole-frame-
        only check), but contrast_std_excluding_glare is genuinely low
        (fog-like) — the region-aware field must be what decides this."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition_with(
                SceneCondition.GLARE,
                contrast_std=FOG_CONTRAST_THRESHOLD + 25.0,  # high — would NOT exempt under the old check
                contrast_std_excluding_glare=FOG_CONTRAST_THRESHOLD - 5.0,  # genuinely fog-like
                brightness_mean=128.0,
            ),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_exemption_does_not_fire_when_region_aware_contrast_is_also_normal(self):
        """The inverse: even if whole-frame contrast_std happens to look
        fog-like, a genuinely normal region-aware contrast (no real haze in
        the non-glare majority) must NOT be exempted — this is the real
        "dirty lens during glare, no fog" case the fix is scoped to exclude."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition_with(
                SceneCondition.GLARE,
                contrast_std=FOG_CONTRAST_THRESHOLD - 5.0,  # low, but...
                contrast_std_excluding_glare=FOG_CONTRAST_THRESHOLD + 25.0,  # ...genuinely normal region-aware
                brightness_mean=128.0,
            ),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_falls_back_to_whole_frame_contrast_when_region_aware_field_is_absent(self):
        """A caller that constructs SceneConditionReport directly without the
        new field (contrast_std_excluding_glare=None, the schema default)
        must still get the original, whole-frame-based behavior — this is
        what every pre-existing test in
        TestWeatherExplainedBlurByRealContrastNotJustLabel above already
        relies on, confirmed explicitly here too."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition_with(
                SceneCondition.GLARE, contrast_std=FOG_CONTRAST_THRESHOLD - 5.0, brightness_mean=128.0
            ),  # contrast_std_excluding_glare left at its None default
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED


class TestSceneQualityFogContrastReference:
    """
    Real follow-up fix (docs/PERFORMANCE_REPORT.md's "Reliability Engine
    behavior under real night/fog conditions"): even after the H
    double-penalty fix above, 29% of genuine fog crossings still missed
    RELIABILITY_R_THRESHOLD, because contrast_score judged FOG_RAIN frames
    against a clear-day contrast ideal (60.0) they were never going to meet
    by definition — FOG_CONTRAST_THRESHOLD=30.0 is the real, already-existing
    rule that classifies a scene FOG_RAIN in the first place. These tests
    call _scene_quality_score directly (not through make_reliability_decision)
    to isolate exactly this behavior.
    """

    def test_fog_at_classification_threshold_scores_full_contrast_component(self):
        """A fog frame whose contrast sits exactly at the real
        FOG_CONTRAST_THRESHOLD (30.0) that got it classified FOG_RAIN in the
        first place should score full marks on the contrast component — it
        is, by this project's own real rule, as clear as "still fog" gets."""
        s = _scene_quality_score(_condition_with(SceneCondition.FOG_RAIN, contrast_std=30.0))
        assert s == pytest.approx(1.0)

    def test_identical_contrast_scores_lower_under_clear_day(self):
        """The SAME raw contrast_std, but classified CLEAR_DAY, still uses
        the clear-day contrast ideal (60.0) and scores lower — proving this
        is a per-condition reference change, not a general softening of the
        contrast component for every condition."""
        fog_s = _scene_quality_score(_condition_with(SceneCondition.FOG_RAIN, contrast_std=30.0))
        day_s = _scene_quality_score(_condition_with(SceneCondition.CLEAR_DAY, contrast_std=30.0))
        assert fog_s > day_s

    def test_fog_contrast_well_below_threshold_still_scores_proportionally_lower(self):
        """Not a blanket free pass — a fog frame meaningfully MORE degraded
        than the classification boundary itself still scores worse than one
        right at the boundary, so real variation within "foggy" still
        matters."""
        at_threshold = _scene_quality_score(_condition_with(SceneCondition.FOG_RAIN, contrast_std=30.0))
        well_below = _scene_quality_score(_condition_with(SceneCondition.FOG_RAIN, contrast_std=10.0))
        assert well_below < at_threshold

    def test_glare_contrast_reference_is_unchanged(self):
        """Regression lock: this fix is scoped to FOG_RAIN only — GLARE
        still uses the clear-day contrast reference exactly as before this
        fix. (LOW_LIGHT_NIGHT gained its OWN, separate contrast reference in
        a later fix — see TestSceneQualityNightContrastReference — so it is
        no longer a same-as-CLEAR_DAY case and is covered there instead.)"""
        glare_s = _scene_quality_score(_condition_with(SceneCondition.GLARE, contrast_std=30.0))
        day_s = _scene_quality_score(_condition_with(SceneCondition.CLEAR_DAY, contrast_std=30.0))
        assert glare_s == pytest.approx(day_s)


class TestSceneQualityNightBrightnessReference:
    """
    Real follow-up fix, same pattern as TestSceneQualityFogContrastReference
    above (docs/PERFORMANCE_REPORT.md's "Reliability Engine behavior under
    real night/fog conditions"): LOW_LIGHT_NIGHT's real measured driver was
    brightness_score judging every night frame against the CLEAR_DAY ideal
    (128.0) it can never meet by definition — BRIGHTNESS_NIGHT_THRESHOLD
    (60.0) is the real, already-existing rule that classifies a scene
    LOW_LIGHT_NIGHT in the first place. These tests call
    _scene_quality_score directly to isolate exactly this behavior.
    """

    def test_night_at_classification_threshold_scores_full_brightness_component(self):
        """A night frame whose brightness sits exactly at the real
        BRIGHTNESS_NIGHT_THRESHOLD (60.0) that got it classified
        LOW_LIGHT_NIGHT in the first place should score full marks on the
        brightness component — as bright as "still night" gets."""
        # contrast_std=1e9 pins contrast_score at its 1.0 cap regardless of
        # which reference LOW_LIGHT_NIGHT's contrast scoring uses, isolating
        # brightness_score cleanly (see TestSceneQualityNightContrastReference
        # below for the contrast-side fix this would otherwise entangle with).
        s = _scene_quality_score(_condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=1e9, brightness_mean=60.0))
        assert s == pytest.approx(1.0)

    def test_identical_brightness_scores_lower_under_clear_day(self):
        """The SAME raw brightness_mean, but classified CLEAR_DAY, still uses
        the clear-day distance-from-128 formula and scores lower — proving
        this is a per-condition reference change, not a general softening of
        the brightness component for every condition."""
        night_s = _scene_quality_score(_condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=1e9, brightness_mean=60.0))
        day_s = _scene_quality_score(_condition_with(SceneCondition.CLEAR_DAY, contrast_std=1e9, brightness_mean=60.0))
        assert night_s > day_s

    def test_night_brightness_well_below_threshold_still_scores_proportionally_lower(self):
        """Not a blanket free pass — a night frame meaningfully darker than
        the classification boundary itself still scores worse than one right
        at the boundary, so real variation within "night" still matters."""
        at_threshold = _scene_quality_score(_condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=1e9, brightness_mean=60.0))
        well_below = _scene_quality_score(_condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=1e9, brightness_mean=20.0))
        assert well_below < at_threshold

    def test_fog_brightness_reference_is_unchanged(self):
        """Regression lock: this fix is scoped to LOW_LIGHT_NIGHT only.
        FOG_RAIN still uses the clear-day distance-from-128 brightness
        formula exactly as before this fix (its own contrast-side fix is
        separate and unaffected)."""
        fog_s_brightness_only = _scene_quality_score(
            _condition_with(SceneCondition.FOG_RAIN, contrast_std=1e9, brightness_mean=60.0)
        )
        day_s_brightness_only = _scene_quality_score(
            _condition_with(SceneCondition.CLEAR_DAY, contrast_std=1e9, brightness_mean=60.0)
        )
        assert fog_s_brightness_only == pytest.approx(day_s_brightness_only)


class TestSceneQualityNightContrastReference:
    """
    Real follow-up fix to night's remaining gap after the brightness fix
    above (docs/PERFORMANCE_REPORT.md's "Reliability Engine behavior under
    real night/fog conditions"): contrast_score was still judging
    LOW_LIGHT_NIGHT frames against the clear-day contrast ideal (60.0).

    UNLIKE the FOG_RAIN contrast fix and the LOW_LIGHT_NIGHT brightness fix
    above (both of which reuse a real constant that's already part of the
    actual SceneConditionClassifier classification rule), LOW_LIGHT_NIGHT's
    classification rule checks brightness only — there is no existing
    "this is the real rule that made it night" constant for contrast to
    reuse. _SCENE_CONTRAST_GOOD_NIGHT is therefore a genuinely NEW,
    disclosed, hand-picked heuristic (half of BRIGHTNESS_NIGHT_THRESHOLD),
    not a reused classification boundary — these tests confirm its actual
    behavior, not that it is "calibrated."
    """

    def test_night_contrast_at_reference_scores_full_contrast_component(self):
        """A night frame whose contrast sits exactly at
        _SCENE_CONTRAST_GOOD_NIGHT should score full marks on the contrast
        component. brightness_mean=128 pins brightness_score at its 1.0 cap
        for BOTH the night ratio formula and the clear-day symmetric formula,
        isolating the contrast comparison cleanly."""
        s = _scene_quality_score(
            _condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=_SCENE_CONTRAST_GOOD_NIGHT, brightness_mean=128.0)
        )
        assert s == pytest.approx(1.0)

    def test_identical_contrast_scores_lower_under_clear_day(self):
        """The SAME raw contrast_std, but classified CLEAR_DAY, still uses
        the clear-day contrast reference (60.0, double
        _SCENE_CONTRAST_GOOD_NIGHT) and scores lower — proving this is a
        per-condition reference change, not a general softening."""
        night_s = _scene_quality_score(
            _condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=_SCENE_CONTRAST_GOOD_NIGHT, brightness_mean=128.0)
        )
        day_s = _scene_quality_score(
            _condition_with(SceneCondition.CLEAR_DAY, contrast_std=_SCENE_CONTRAST_GOOD_NIGHT, brightness_mean=128.0)
        )
        assert night_s > day_s

    def test_night_contrast_well_below_reference_still_scores_proportionally_lower(self):
        """Not a blanket free pass — a night frame meaningfully lower-
        contrast than _SCENE_CONTRAST_GOOD_NIGHT itself still scores worse,
        so real variation within "night" still matters."""
        at_reference = _scene_quality_score(
            _condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=_SCENE_CONTRAST_GOOD_NIGHT, brightness_mean=128.0)
        )
        well_below = _scene_quality_score(
            _condition_with(SceneCondition.LOW_LIGHT_NIGHT, contrast_std=_SCENE_CONTRAST_GOOD_NIGHT / 3.0, brightness_mean=128.0)
        )
        assert well_below < at_reference

    def test_fog_contrast_reference_is_unaffected_by_adding_the_night_entry(self):
        """Regression lock: adding LOW_LIGHT_NIGHT's own dict entry must not
        disturb FOG_RAIN's existing, separate contrast reference
        (FOG_CONTRAST_THRESHOLD=30.0, unrelated in value to
        _SCENE_CONTRAST_GOOD_NIGHT=30.0 despite the coincidental match — see
        TestSceneQualityFogContrastReference for FOG_RAIN's own coverage)."""
        fog_s = _scene_quality_score(_condition_with(SceneCondition.FOG_RAIN, contrast_std=30.0, brightness_mean=128.0))
        assert fog_s == pytest.approx(1.0)


class TestHybridEngineTemporalScore:
    """T (temporal_score) is a real input to R, not decoration — a borderline
    case can flip between UNCERTAIN and DETECTED purely based on it."""

    def test_low_temporal_score_can_tip_borderline_case_to_uncertain(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
            temporal_score=0.0,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_high_temporal_score_can_tip_same_borderline_case_to_detected(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
            temporal_score=1.0,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_default_temporal_score_is_neutral_one(self):
        """Callers that haven't been upgraded to compute T (or have no track
        context, e.g. an abandoned-object event) must see identical behavior
        to explicitly passing temporal_score=1.0."""
        kwargs = dict(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        default_result = make_reliability_decision(**kwargs)
        explicit_result = make_reliability_decision(**kwargs, temporal_score=1.0)
        assert default_result.decision_state == explicit_result.decision_state


class TestHybridEngineWeightsAreConfigured:
    def test_weights_sum_to_one(self):
        """Not enforced at runtime (env-overridable), but the shipped
        defaults must be a real weighted average, not something that silently
        under- or over-counts the four factors."""
        total = RELIABILITY_WEIGHT_D + RELIABILITY_WEIGHT_T + RELIABILITY_WEIGHT_S + RELIABILITY_WEIGHT_H
        assert abs(total - 1.0) < 1e-9

    def test_detector_confidence_carries_the_largest_weight(self):
        """D is the actual object-presence signal — it must not be diluted
        below any single modulating factor."""
        assert RELIABILITY_WEIGHT_D > RELIABILITY_WEIGHT_T
        assert RELIABILITY_WEIGHT_D > RELIABILITY_WEIGHT_S
        assert RELIABILITY_WEIGHT_D > RELIABILITY_WEIGHT_H


class TestDecisionFields:
    """All decisions must populate required fields."""

    def test_abstain_has_required_fields(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED),
            condition_report=_condition(),
            detector_confidence=0.99,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state is not None
        assert result.decision_reason is not None
        assert result.camera_health is not None
        assert result.scene_condition is not None

    def test_detected_has_threshold(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(),
            detector_confidence=0.80,
            calibration_threshold=THRESHOLD,
        )
        assert result.applied_threshold == THRESHOLD
        assert result.detector_confidence == 0.80

    def test_decision_reason_always_non_empty(self):
        for state, conf, threshold, health in [
            (DecisionState.ABSTAIN, 0.99, 0.45, CameraHealthState.FAILED),
            (DecisionState.UNCERTAIN, 0.20, 0.45, CameraHealthState.OK),
            (DecisionState.DETECTED, 0.80, 0.45, CameraHealthState.OK),
        ]:
            result = make_reliability_decision(
                health_report=_health(health),
                condition_report=_condition(),
                detector_confidence=conf,
                calibration_threshold=threshold,
            )
            assert len(result.decision_reason) > 5, f"Empty reason for {state}"


class TestConvenienceConstructors:
    def test_make_abstain(self):
        result = make_abstain("cam-1", "STREAM_DEAD", SceneCondition.CLEAR_DAY)
        assert result.decision_state == DecisionState.ABSTAIN
        assert result.camera_health == CameraHealthState.FAILED

    def test_make_uncertain(self):
        result = make_uncertain(SceneCondition.FOG_RAIN, 0.25, 0.35)
        assert result.decision_state == DecisionState.UNCERTAIN


class TestSchemaLockedFields:
    """Phase 2 acceptance: all locked evidence package fields must be present."""

    def test_evidence_package_has_all_locked_fields(self):
        from shared.schemas import EvidencePackage
        from datetime import datetime
        ep = EvidencePackage(
            event_id="evt-001",
            camera_id="cam-001",
            timestamp=datetime.utcnow(),
            zone_id="zone-001",
            detection_class="person",
            confidence=0.75,
            scene_condition="CLEAR_DAY",
            camera_health_state="OK",
            decision_state="DETECTED",
        )
        locked_fields = [
            "event_id", "camera_id", "timestamp", "zone_id",
            "detection_class", "confidence", "scene_condition",
            "camera_health_state", "decision_state", "evidence_clip_ref",
            "hash", "signature",
        ]
        for field in locked_fields:
            assert hasattr(ep, field), f"Missing locked field: {field}"

    def test_evidence_package_signable_fields_excludes_crypto(self):
        from shared.schemas import EvidencePackage
        ep = EvidencePackage(
            event_id="evt-001",
            camera_id="cam-001",
            timestamp=datetime.utcnow(),
            zone_id="zone-001",
            detection_class="person",
            confidence=0.75,
            scene_condition="CLEAR_DAY",
            camera_health_state="OK",
            decision_state="DETECTED",
            hash="deadbeef",
            signature="cafebabe",
        )
        signable = ep.get_signable_fields()
        assert "hash" not in signable
        assert "signature" not in signable
        assert "event_id" in signable
        assert "camera_id" in signable

    def test_zone_schema_has_adjacent_command_id(self):
        from shared.schemas import ZoneSchema, Polygon, Point
        z = ZoneSchema(
            zone_id="z1",
            camera_id="c1",
            name="Fence",
            zone_type="fence",
            polygon=Polygon(points=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1)]),
            owning_command_id="COMMAND_A",
            adjacent_command_id="COMMAND_B",
        )
        assert z.adjacent_command_id == "COMMAND_B"

    def test_on_chain_transaction_has_locked_fields(self):
        from shared.schemas import AlertIssuedTransaction
        from shared.constants import Severity
        tx = AlertIssuedTransaction(
            alert_id="alert-001",
            evidence_package_hash="abc123",
            severity=Severity.HIGH,
            zone_id="zone-001",
            issuing_command_id="COMMAND_A",
            timestamp=datetime.utcnow(),
        )
        on_chain_fields = [
            "alert_id", "evidence_package_hash", "severity",
            "zone_id", "issuing_command_id", "timestamp"
        ]
        for field in on_chain_fields:
            assert hasattr(tx, field), f"Missing on-chain locked field: {field}"
