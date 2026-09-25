"""
NETRAKSH Edge — Hybrid Reliability Decision Layer (Layer 5).
Implements the architecture v4 §8 HYBRID design (approved to replace the
original 3-gate categorical cascade's Gate 3 — see docs/ARCHITECTURE.md's
"Hybrid Reliability Engine" changelog entry for the full history and the
one existing test this intentionally changed the outcome of).

Gate 1 (Health, hard override — UNCHANGED from the original design):
  health == FAILED -> ABSTAIN, reason CAMERA_FAILED, stop.
  A weighted sum alone cannot guarantee this: a dead camera with an
  otherwise-plausible reading could still cross an Uncertain threshold under
  pure weighting. This stays a categorical, non-negotiable check specifically
  so that can never happen.

Below Gate 1 — weighted-sum Reliability score:
  R = wD*D + wT*T + wS*S + wH*H
  IF R < RELIABILITY_R_THRESHOLD: UNCERTAIN
  ELIF health == DEGRADED:        DETECTED (flagged — degraded-camera context)
  ELSE:                            DETECTED

  D = detector_confidence      (raw YOLO confidence for this frame's detection)
  T = temporal_score           (edge.temporal.track_features.TrackFeatureTracker;
                                defaults to a neutral 1.0 when no track context
                                is available — e.g. an abandoned-object event
                                whose track has already disappeared)
  S = scene quality             derived from SceneConditionReport's raw signals
  H = camera health quality     derived from CameraHealthReport.health_state

ABSTAIN remains reserved for Gate 1 only — this preserves the existing,
testable distinction between "the sensor is broken" (Abstain) and "the
evidence is weak" (Uncertain).

All weights, RELIABILITY_R_THRESHOLD, and the S/H scoring functions are
hand-picked heuristic defaults, NOT calibrated against labeled data — see
docs/LIMITATIONS.md and docs/ADR-TEMPORAL.md. They are environment-
overridable so a future calibration run (in the same spirit as
edge/detection/calibration.py's isotonic/Platt fitting) can update them
without a code change.

INTENTIONAL BEHAVIOR CHANGE from the original cascade: a degraded scene
condition now REDUCES R (via S) rather than lowering the acceptance bar the
way the old per-condition confidence threshold did. This is deliberate — the
project's own thesis is that the system should trust itself LESS under
degraded conditions, not accept weaker evidence as if it were normal. See
docs/ARCHITECTURE.md for the full rationale and the one test this changed.

Reliability and severity remain SEPARATE CONCEPTS.
A high-severity-looking event from a FAILED camera is still ABSTAIN.
"""
from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

from shared.constants import (
    BRIGHTNESS_NIGHT_THRESHOLD,
    CameraHealthState,
    DecisionState,
    FOG_CONTRAST_THRESHOLD,
    HealthReason,
    SceneCondition,
)
from shared.schemas import CameraHealthReport, ReliabilityDecision, SceneConditionReport

logger = logging.getLogger(__name__)

# --- Hybrid Reliability Engine weights and threshold (architecture v4 §8) ---
# HEURISTIC DEFAULTS — hand-picked starting point, ship-day-one values, NOT
# calibrated against labeled data. D carries the most weight because it is
# the actual object-presence signal; T/S/H are equal-weighted modulators.
# RELIABILITY_R_THRESHOLD=0.75 is inherited from the project's original
# reliability-formula convention (R>=0.75 -> DETECTED), now serving as the
# sole DETECTED cutoff since ABSTAIN is Gate 1's exclusive domain.
RELIABILITY_WEIGHT_D = float(os.environ.get("RELIABILITY_WEIGHT_D", "0.40"))
RELIABILITY_WEIGHT_T = float(os.environ.get("RELIABILITY_WEIGHT_T", "0.20"))
RELIABILITY_WEIGHT_S = float(os.environ.get("RELIABILITY_WEIGHT_S", "0.20"))
RELIABILITY_WEIGHT_H = float(os.environ.get("RELIABILITY_WEIGHT_H", "0.20"))
RELIABILITY_R_THRESHOLD = float(os.environ.get("RELIABILITY_R_THRESHOLD", "0.75"))

# Scene-quality (S) scoring reference points — same spirit as the thresholds
# in shared/constants.py, hand-picked and clearly labeled as such.
_SCENE_BRIGHTNESS_IDEAL = 128.0
_SCENE_CONTRAST_GOOD = 60.0
_SCENE_GLARE_BAD = 0.30

# Real finding this fixes (docs/PERFORMANCE_REPORT.md's "Reliability Engine
# behavior under real night/fog conditions"): even after the H double-penalty
# fix above, 29% of genuine fog crossings still missed RELIABILITY_R_THRESHOLD
# — because contrast_score judged FOG_RAIN frames against _SCENE_CONTRAST_GOOD
# (60.0), a clear-day ideal. But `contrast_std < FOG_CONTRAST_THRESHOLD` is
# LITERALLY the real rule SceneConditionClassifier already uses to call a
# scene FOG_RAIN in the first place (edge/condition/scene_condition.py) — so
# every frame classified FOG_RAIN is, by definition, already below 60, and
# judging it against 60 anyway scores it as "badly foggy" even when it is
# merely "typically foggy for what got it classified as fog at all." This
# reuses that SAME real, already-existing constant as FOG_RAIN's own
# contrast reference instead — not a new, unjustified number — so a frame at
# the actual boundary of "is this foggy" scores a full contrast_score, and a
# frame foggier than that (which does mean something concretely worse: low
# contrast well beyond the classification threshold itself) still scores
# proportionally lower.
#
# LOW_LIGHT_NIGHT is DIFFERENT IN KIND, not just degree, from the FOG_RAIN
# case above — disclose this plainly rather than implying the same rigor.
# SceneConditionClassifier's LOW_LIGHT_NIGHT rule checks brightness only
# (edge/condition/scene_condition.py); contrast plays no part in classifying
# a scene as night, so unlike FOG_RAIN there is no existing, already-defined
# "this is the real rule that made it night" constant for contrast to reuse.
# _SCENE_CONTRAST_GOOD_NIGHT below is therefore a genuinely NEW, hand-picked
# heuristic — NOT calibrated, NOT a reused classification-boundary constant
# — chosen as half of BRIGHTNESS_NIGHT_THRESHOLD on a real, statable (but
# still heuristic) physical basis: contrast_std measures the spread of a
# non-negative pixel-value distribution, and a distribution whose mean is
# capped below BRIGHTNESS_NIGHT_THRESHOLD cannot have much spread without
# clipping at zero — so a legitimately-dark-but-not-defective night frame's
# achievable contrast is bounded by its own available brightness headroom,
# not by the clear-day sensor's full 0-255 range. This is exactly the same
# category of hand-picked default as _SCENE_CONTRAST_GOOD/_SCENE_BRIGHTNESS_
# IDEAL/_SCENE_GLARE_BAD themselves (see docs/LIMITATIONS.md) — it is
# disclosed as such, not oversold as a "reused real constant" the way the
# FOG_RAIN entry above legitimately is.
_SCENE_CONTRAST_GOOD_NIGHT = BRIGHTNESS_NIGHT_THRESHOLD / 2.0  # = 30.0
_SCENE_CONTRAST_GOOD_BY_CONDITION = {
    SceneCondition.FOG_RAIN: FOG_CONTRAST_THRESHOLD,
    SceneCondition.LOW_LIGHT_NIGHT: _SCENE_CONTRAST_GOOD_NIGHT,
}

# Real finding this fixes (same section of docs/PERFORMANCE_REPORT.md):
# LOW_LIGHT_NIGHT's real measured driver was brightness_score, not contrast —
# every night frame is, by definition, below BRIGHTNESS_NIGHT_THRESHOLD (60.0,
# the real rule that classifies a scene as LOW_LIGHT_NIGHT in the first place,
# edge/condition/scene_condition.py), yet brightness_score judged it against
# the CLEAR_DAY midpoint ideal (128.0) meant for a symmetric too-dark/too-
# bright measurement — scoring every night frame as "badly dark" even at the
# very boundary of "still counts as night." Reusing BRIGHTNESS_NIGHT_THRESHOLD
# here, exactly like FOG_CONTRAST_THRESHOLD above: within the night band, MORE
# light is unambiguously better for detection (not "distance from an ideal"
# the way CLEAR_DAY/GLARE/FOG_RAIN's symmetric formula assumes), so this uses
# a ratio score capped at the real classification boundary — a frame right at
# that boundary scores full brightness marks; a darker one than that still
# scores proportionally lower.
_NIGHT_BRIGHTNESS_SCORED_CONDITIONS = frozenset({SceneCondition.LOW_LIGHT_NIGHT})

# Health-quality (H) scoring. FAILED is never looked up here — Gate 1
# handles it exclusively, before this table would ever be consulted.
_HEALTH_QUALITY_SCORE = {
    CameraHealthState.OK: 1.0,
    CameraHealthState.DEGRADED: 0.5,
}

# Real finding this fixes (docs/PERFORMANCE_REPORT.md's "Reliability Engine
# behavior under real night/fog conditions", docs/LIMITATIONS.md): under a
# real, honest fog measurement, 0/52 genuine crossings cleared
# RELIABILITY_R_THRESHOLD. Root cause — a double penalty, not two
# independent ones: fog/low-light genuinely reduces image contrast/
# brightness, which S already measures and penalizes directly, AND
# genuinely reduces the Laplacian blur score edge/health/camera_health.py
# uses for its OWN, unrelated purpose (detecting a broken/dirty/defocused
# camera) — so the SAME real visual-softening signal was silently counted
# twice, once as S and again as H, for conditions where it isn't actually
# two independent problems.
#
# The SAME real pattern was later found for GLARE too, at 0/55 (0%) DETECTED
# under a real, honest glare measurement: glare genuinely blows out
# highlights, which S already measures and penalizes via glare_fraction,
# AND the same real overexposure genuinely trips
# edge/health/camera_health.py's OWN, unrelated exposure-clipping check
# (a real camera fault detector, not a weather detector) into
# ABNORMAL_EXPOSURE — the same double-count, different reason/condition
# pair. Both pairs are listed below; this dict is deliberately a mapping
# (not two separate special-cased conditionals) so a third such pairing, if
# ever found, is a one-line addition, not a new code path.
#
# FROZEN_STREAM, FPS_DEGRADED, and CLOCK_DRIFT are genuinely independent of
# scene condition and are NOT touched by this — only the specific
# reason/condition pairs below, where the DEGRADED reason and the scene
# classification are reacting to the exact same real pixel signal.
_WEATHER_EXPLAINED_DEGRADED_REASONS: dict = {
    HealthReason.EXCESSIVE_BLUR: frozenset({SceneCondition.FOG_RAIN, SceneCondition.LOW_LIGHT_NIGHT}),
    HealthReason.ABNORMAL_EXPOSURE: frozenset({SceneCondition.GLARE}),
}


def _scene_quality_score(condition_report: SceneConditionReport) -> float:
    """Mode-A heuristic scene-quality score S in [0,1], derived from the same
    raw brightness/contrast/glare signals SceneConditionClassifier already
    computes. NOT calibrated — see docs/LIMITATIONS.md.

    Both contrast_score and brightness_score use per-condition reference
    points rather than a single global one for FOG_RAIN and LOW_LIGHT_NIGHT
    (see the comments above each lookup table) — to avoid judging an
    inherently-degraded-by-definition condition against a clear-day ideal it
    was never going to meet. FOG_RAIN's contrast reference and
    LOW_LIGHT_NIGHT's brightness reference reuse a real, already-existing
    classification-boundary constant; LOW_LIGHT_NIGHT's contrast reference
    does not have one of those to reuse and is a disclosed, hand-picked
    heuristic instead — see the comment above _SCENE_CONTRAST_GOOD_NIGHT.
    """
    if condition_report.condition in _NIGHT_BRIGHTNESS_SCORED_CONDITIONS:
        brightness_score = min(condition_report.brightness_mean / BRIGHTNESS_NIGHT_THRESHOLD, 1.0)
    else:
        brightness_score = 1.0 - min(
            abs(condition_report.brightness_mean - _SCENE_BRIGHTNESS_IDEAL) / _SCENE_BRIGHTNESS_IDEAL, 1.0
        )
    contrast_good = _SCENE_CONTRAST_GOOD_BY_CONDITION.get(condition_report.condition, _SCENE_CONTRAST_GOOD)
    contrast_score = min(condition_report.contrast_std / contrast_good, 1.0)
    glare_score = 1.0 - min(condition_report.glare_fraction / _SCENE_GLARE_BAD, 1.0)
    return max(0.0, min(1.0, (brightness_score + contrast_score + glare_score) / 3.0))


def _health_quality_score(
    health_report: CameraHealthReport, condition_report: SceneConditionReport
) -> float:
    """Mode-A heuristic health-quality score H in [0,1]. Only OK/DEGRADED are
    scored here — FAILED is handled exclusively by Gate 1 before this is
    ever reached.

    One deliberate exception (see _WEATHER_EXPLAINED_DEGRADED_REASONS above
    for the real, measured failure modes this fixes): when health is
    DEGRADED for a reason whose real cause overlaps with the scene's own
    independent classification (EXCESSIVE_BLUR under FOG_RAIN/
    LOW_LIGHT_NIGHT; ABNORMAL_EXPOSURE under GLARE), H is scored as healthy
    (1.0) instead of the usual 0.5 — S already penalizes this exact real
    signal, so this avoids double-counting one real degradation as two. Any
    OTHER DEGRADED reason (or the SAME reason under an unrelated scene
    condition, e.g. EXCESSIVE_BLUR during CLEAR_DAY) still fully penalizes H
    exactly as before — those are genuinely independent hardware/pipeline
    problems S has no signal for.

    A SECOND exemption, added after a real, at-scale finding (a real
    fog+glare compound scene, docs/LIMITATIONS.md: EXCESSIVE_BLUR fired on
    246/260 real frames — 95%, not a small-sample anecdote): SceneCondition
    is a single categorical label, so a scene that is genuinely BOTH FOG_RAIN
    and GLARE (glare_fraction wins the classification priority) is reported
    as GLARE alone — and the EXCESSIVE_BLUR exemption above, keyed only to
    the WINNING label, cannot see the real, co-occurring fog that is the
    actual cause. Rather than add GLARE to the label-keyed exemption (which
    would incorrectly also exempt a genuinely dirty/defocused lens during
    real glare with no fog involved — glare's own transform, with no blur
    applied, never once triggered EXCESSIVE_BLUR across ~160 real candidates
    collected this session), this checks the REAL underlying signal directly:
    if REGION-AWARE contrast (SceneConditionReport.contrast_std_excluding_glare
    — spread among non-blown-out pixels only, edge/condition/scene_condition.py)
    is below FOG_CONTRAST_THRESHOLD — the same real constant that defines "is
    this fog" — the blur is plausibly explained by genuine fog-like
    conditions in the non-glare majority of the frame, regardless of which
    label won the classification or how much a small bright region inflates
    the WHOLE-FRAME contrast_std. This is a real, necessary refinement over
    an earlier version of this same check that used whole-frame contrast_std
    directly: that version was found, honestly, to NOT catch the real
    fog_glare case it was built for (whole-frame contrast_std≈41, above the
    threshold, because the glow inflated it) — this region-aware measurement
    is what actually catches it (falls back to contrast_std for any caller
    not supplying the new field, e.g. direct SceneConditionReport construction
    in older tests). A real dirty lens during pure glare has normal-to-high
    contrast even region-aware (measured 55-94 across every real
    glare/glare_mild/night_glare candidate this session, all well above 30)
    and is therefore still NOT exempted by this check — only a scene whose
    non-glare majority is ACTUALLY fog-like is.
    """
    if health_report.health_state == CameraHealthState.DEGRADED:
        explained_conditions = _WEATHER_EXPLAINED_DEGRADED_REASONS.get(health_report.health_reason)
        if explained_conditions and condition_report.condition in explained_conditions:
            return 1.0
        region_aware_contrast = condition_report.contrast_std_excluding_glare
        if region_aware_contrast is None:
            region_aware_contrast = condition_report.contrast_std
        if (
            health_report.health_reason == HealthReason.EXCESSIVE_BLUR
            and region_aware_contrast < FOG_CONTRAST_THRESHOLD
        ):
            return 1.0
    return _HEALTH_QUALITY_SCORE.get(health_report.health_state, 0.5)


class ReliabilityEngine(ABC):
    """Abstract base class for the Reliability Engine."""

    @abstractmethod
    def evaluate(
        self,
        health_report: CameraHealthReport,
        condition_report: SceneConditionReport,
        detector_confidence: float,
        calibration_threshold: float,
        temporal_score: float = 1.0,
    ) -> ReliabilityDecision:
        pass


class LegacyReliabilityEngine(ReliabilityEngine):
    """
    Preserves the exact behavior of the v4 Hybrid Reliability Engine.
    """
    def evaluate(
        self,
        health_report: CameraHealthReport,
        condition_report: SceneConditionReport,
        detector_confidence: float,
        calibration_threshold: float,
        temporal_score: float = 1.0,
    ) -> ReliabilityDecision:
        condition = condition_report.condition
        d = max(0.0, min(1.0, detector_confidence))
        t = max(0.0, min(1.0, temporal_score))
        s = _scene_quality_score(condition_report)
        h = _health_quality_score(health_report, condition_report)

        r = (
            RELIABILITY_WEIGHT_D * d
            + RELIABILITY_WEIGHT_T * t
            + RELIABILITY_WEIGHT_S * s
            + RELIABILITY_WEIGHT_H * h
        )
        factor_detail = f"D={d:.2f},T={t:.2f},S={s:.2f},H={h:.2f}"

        if r < RELIABILITY_R_THRESHOLD:
            reason = f"R_BELOW_THRESHOLD:R={r:.3f}<{RELIABILITY_R_THRESHOLD:.3f} ({factor_detail})"
            logger.debug(f"[Reliability] UNCERTAIN — {reason}")
            return ReliabilityDecision(
                decision_state=DecisionState.UNCERTAIN,
                decision_reason=reason,
                camera_health=health_report.health_state,
                scene_condition=condition,
                detector_confidence=detector_confidence,
                applied_threshold=calibration_threshold,
                score_d=d,
                score_t=t,
                score_s=s,
                score_h=h,
                score_r=r,
            )

        # R above threshold — DETECTED, flag health context
        if health_report.health_state == CameraHealthState.DEGRADED:
            reason = (
                f"R_ABOVE_THRESHOLD_DEGRADED_CAMERA:R={r:.3f}>={RELIABILITY_R_THRESHOLD:.3f} "
                f"({factor_detail}),health={health_report.health_reason}"
            )
            logger.info(f"[Reliability] DETECTED (DEGRADED CAMERA) — R={r:.3f}, health={health_report.health_reason}")
            return ReliabilityDecision(
                decision_state=DecisionState.DETECTED,
                decision_reason=reason,
                camera_health=CameraHealthState.DEGRADED,
                scene_condition=condition,
                detector_confidence=detector_confidence,
                applied_threshold=calibration_threshold,
                score_d=d,
                score_t=t,
                score_s=s,
                score_h=h,
                score_r=r,
            )

        # Full DETECTED
        reason = f"R_ABOVE_THRESHOLD:R={r:.3f}>={RELIABILITY_R_THRESHOLD:.3f} ({factor_detail})"
        logger.info(f"[Reliability] DETECTED — R={r:.3f}")
        return ReliabilityDecision(
            decision_state=DecisionState.DETECTED,
            decision_reason=reason,
            camera_health=CameraHealthState.OK,
            scene_condition=condition,
            detector_confidence=detector_confidence,
            applied_threshold=calibration_threshold,
            score_d=d,
            score_t=t,
            score_s=s,
            score_h=h,
            score_r=r,
        )


class CalibratedReliabilityEngine(ReliabilityEngine):
    """
    Interface for a future data-driven Reliability Engine (e.g., LogisticRegression).
    Currently implemented as a safe fallback because a verified model does not exist.
    """
    def __init__(self, model_path: str = "models/reliability_calibration.json"):
        self.model_path = model_path
        self.model = self._load_and_validate_model()
        self.threshold = float(os.environ.get("RELIABILITY_CALIBRATED_THRESHOLD", "0.75"))

    def _load_and_validate_model(self):
        """Safely validate the JSON model artifact if it exists."""
        import json
        if not os.path.exists(self.model_path):
            logger.warning(f"[Reliability] Calibrated model artifact not found at {self.model_path}. Engine UNAVAILABLE.")
            return None
        
        try:
            with open(self.model_path, "r") as f:
                model = json.load(f)
            
            # Validation: JSON schema checks
            if model.get("version") != 1:
                logger.error("[Reliability] Invalid model type: unexpected version.")
                return None
                
            weights = model.get("weights", {})
            if not isinstance(weights, dict):
                logger.error("[Reliability] Invalid model type: weights is not a dictionary.")
                return None
                
            for k in ["d", "t", "s", "h"]:
                if k not in weights or not isinstance(weights[k], (int, float)):
                    logger.error(f"[Reliability] Feature schema mismatch: missing or invalid weight for {k}")
                    return None
                    
            if not isinstance(model.get("intercept", 0.0), (int, float)):
                logger.error("[Reliability] Invalid model type: intercept is not numeric.")
                return None
                
            logger.info(f"[Reliability] Successfully loaded JSON CalibratedReliabilityEngine model from {self.model_path}")
            return model
            
        except Exception as e:
            logger.error(f"[Reliability] Failed to load/validate calibrated JSON model: {e}")
            return None

    def evaluate(
        self,
        health_report: CameraHealthReport,
        condition_report: SceneConditionReport,
        detector_confidence: float,
        calibration_threshold: float,
        temporal_score: float = 1.0,
    ) -> ReliabilityDecision:
        condition = condition_report.condition
        d = max(0.0, min(1.0, detector_confidence))
        t = max(0.0, min(1.0, temporal_score))
        s = _scene_quality_score(condition_report)
        h = _health_quality_score(health_report, condition_report)

        if self.model is None:
            # Safe Fallback: DO NOT SILENTLY GENERATE A SCORE OR USE LEGACY
            reason = "UNCERTAIN_CALIBRATED_ENGINE_UNAVAILABLE"
            return ReliabilityDecision(
                decision_state=DecisionState.UNCERTAIN,
                decision_reason=reason,
                camera_health=health_report.health_state,
                scene_condition=condition,
                detector_confidence=detector_confidence,
                applied_threshold=calibration_threshold,
                score_d=d,
                score_t=t,
                score_s=s,
                score_h=h,
                score_r=None,
            )

        import math
        try:
            w = self.model["weights"]
            intercept = float(self.model.get("intercept", 0.0))
            z = intercept + (d * float(w["d"])) + (t * float(w["t"])) + (s * float(w["s"])) + (h * float(w["h"]))
            # Clamp z to avoid overflow in exp
            z = max(-500.0, min(500.0, z))
            prob = 1.0 / (1.0 + math.exp(-z))
        except Exception as e:
            logger.error(f"[Reliability] Prediction failed: {e}")
            return ReliabilityDecision(
                decision_state=DecisionState.UNCERTAIN,
                decision_reason=f"CALIBRATED_ENGINE_ERROR:{e}",
                camera_health=health_report.health_state,
                scene_condition=condition,
                detector_confidence=detector_confidence,
                applied_threshold=calibration_threshold,
                score_d=d,
                score_t=t,
                score_s=s,
                score_h=h,
                score_r=None,
            )

        if prob < self.threshold:
            state = DecisionState.UNCERTAIN
            reason = f"CALIBRATED_PROBABILITY_BELOW_THRESHOLD:P={prob:.3f}<{self.threshold:.3f}"
        else:
            state = DecisionState.DETECTED
            reason = f"CALIBRATED_PROBABILITY_ABOVE_THRESHOLD:P={prob:.3f}>={self.threshold:.3f}"
            
        return ReliabilityDecision(
            decision_state=state,
            decision_reason=reason,
            camera_health=health_report.health_state,
            scene_condition=condition,
            detector_confidence=detector_confidence,
            applied_threshold=calibration_threshold,
            score_d=d,
            score_t=t,
            score_s=s,
            score_h=h,
            score_r=prob,
        )


def get_reliability_engine() -> ReliabilityEngine:
    engine_type = os.environ.get("RELIABILITY_ENGINE", "legacy").lower()
    if engine_type == "calibrated":
        return CalibratedReliabilityEngine()
    else:
        return LegacyReliabilityEngine()


def make_reliability_decision(
    health_report: CameraHealthReport,
    condition_report: SceneConditionReport,
    detector_confidence: float,
    calibration_threshold: float,
    temporal_score: float = 1.0,
) -> ReliabilityDecision:
    """
    The one function that implements the Hybrid Reliability Engine.
    Gate 1 is processed strictly here before the engine sees it.

    Args:
        health_report: output of Gate 1 (Camera Health Monitor)
        condition_report: output of Gate 2 (Scene Condition Classifier)
        detector_confidence: raw confidence from YOLO for the highest-confidence
                             detection in this frame (0.0 if no detection)
        calibration_threshold: per-condition confidence threshold
        temporal_score: T in [0,1] from track_features.

    Returns:
        ReliabilityDecision with decision_state, decision_reason, and context
    """
    # === GATE 1: Camera Health (hard override, unchanged, absolute safety gate) ===
    if health_report.health_state == CameraHealthState.FAILED:
        reason = f"CAMERA_FAILED:{health_report.health_reason}"
        logger.warning(
            f"[Reliability] ABSTAIN — Gate 1 FAILED "
            f"(camera={health_report.camera_id}, reason={health_report.health_reason})"
        )
        return ReliabilityDecision(
            decision_state=DecisionState.ABSTAIN,
            decision_reason=reason,
            camera_health=CameraHealthState.FAILED,
            scene_condition=condition_report.condition,
            detector_confidence=detector_confidence,
            applied_threshold=calibration_threshold,
        )

    engine = get_reliability_engine()
    return engine.evaluate(
        health_report, condition_report, detector_confidence, calibration_threshold, temporal_score
    )


def make_abstain(camera_id: str, reason: str, condition: SceneCondition = SceneCondition.CLEAR_DAY) -> ReliabilityDecision:
    """Convenience constructor for ABSTAIN without running full gate logic."""
    return ReliabilityDecision(
        decision_state=DecisionState.ABSTAIN,
        decision_reason=reason,
        camera_health=CameraHealthState.FAILED,
        scene_condition=condition,
        detector_confidence=0.0,
        applied_threshold=0.0,
        score_d=None,
        score_t=None,
        score_s=None,
        score_h=None,
        score_r=None,
    )


def make_uncertain(condition: SceneCondition, confidence: float, threshold: float) -> ReliabilityDecision:
    """Convenience constructor for UNCERTAIN (e.g. night motion fallback)."""
    return ReliabilityDecision(
        decision_state=DecisionState.UNCERTAIN,
        decision_reason=f"MOVEMENT_DETECTED_CLASS_UNCERTAIN:{condition}",
        camera_health=CameraHealthState.OK,
        scene_condition=condition,
        detector_confidence=confidence,
        applied_threshold=threshold,
        score_d=None,
        score_t=None,
        score_s=None,
        score_h=None,
        score_r=None,
    )
