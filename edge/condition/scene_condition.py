"""
NETRAKSH Edge — Scene Condition Classifier (Gate 2).
Classifies the current visual scene into one of four buckets:
  CLEAR_DAY | LOW_LIGHT_NIGHT | FOG_RAIN | GLARE

Uses pure OpenCV heuristics — no model required for MVP.
Each bucket corresponds to a different calibrated confidence threshold in Gate 3.

A single global threshold is provably wrong across day/night/fog — this is why
condition classification exists as its own gate.
"""
from __future__ import annotations

import logging
import os

import cv2
import numpy as np

from shared.constants import (
    BRIGHTNESS_GLARE_THRESHOLD,
    BRIGHTNESS_NIGHT_THRESHOLD,
    FOG_CONTRAST_THRESHOLD,
    SceneCondition,
)
from shared.schemas import SceneConditionReport

logger = logging.getLogger(__name__)

# Real fix (docs/LIMITATIONS.md's fog+glare compound finding): the same
# near-white pixel-value band glare_fraction already uses to flag "how much
# of the frame is blown out" — reused here (not a new, separate cutoff) to
# exclude those same pixels from a REGION-AWARE contrast measurement, so a
# small bright region (real glare, a light source, a reflection) doesn't
# mask genuine haze in the rest of the frame the way the whole-frame
# contrast_std can. See _compute_masked_contrast()'s docstring.
_GLARE_PIXEL_VALUE = 230


class SceneConditionClassifier:
    """
    Stateless classifier. Returns a SceneConditionReport per frame.
    """

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.low_light_threshold = float(os.environ.get("LOW_LIGHT_LUMA_THRESHOLD", str(BRIGHTNESS_NIGHT_THRESHOLD)))
        self.very_low_light_threshold = float(os.environ.get("VERY_LOW_LIGHT_LUMA_THRESHOLD", "20.0"))

    def classify(self, frame: np.ndarray) -> SceneConditionReport:
        """
        Classify scene condition from a single frame.
        Priority order (matches what reduces detector reliability most severely):
          1. GLARE (destroys object boundaries)
          2. FOG_RAIN (reduces contrast globally)
          3. LOW_LIGHT_NIGHT (reduces brightness)
          4. CLEAR_DAY (default)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        brightness_mean = float(np.mean(gray))
        contrast_std = float(np.std(gray))

        # Glare: high mean AND very high peak histogram fraction
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        glare_fraction = float(np.sum(hist[230:]) / gray.size)
        dark_pixel_ratio = float(np.mean(gray < 30))

        contrast_std_excluding_glare = self._compute_masked_contrast(gray)

        # Real classification decision is UNCHANGED by the region-aware
        # measurement above — this is deliberately scoped: _decide() still
        # uses the same whole-frame contrast_std it always has, since
        # changing what actually gates FOG_RAIN/GLARE classification is a
        # bigger, separately-justified change this fix does not make. See
        # docs/LIMITATIONS.md for why this is intentionally narrow.
        condition = self._decide(brightness_mean, contrast_std, glare_fraction)

        report = SceneConditionReport(
            camera_id=self.camera_id,
            condition=condition,
            brightness_mean=brightness_mean,
            contrast_std=contrast_std,
            contrast_std_excluding_glare=contrast_std_excluding_glare,
            glare_fraction=glare_fraction,
            lighting_state=(
                "VERY_LOW_LIGHT" if brightness_mean < self.very_low_light_threshold else
                "LOW_LIGHT" if brightness_mean < self.low_light_threshold else
                "DAYLIGHT" if condition in (SceneCondition.CLEAR_DAY, SceneCondition.FOG_RAIN) else
                "UNKNOWN"
            ),
            mean_luminance=brightness_mean,
            dark_pixel_ratio=dark_pixel_ratio,
        )

        logger.debug(
            f"[Condition] {self.camera_id}: {condition} "
            f"(brightness={brightness_mean:.1f}, contrast={contrast_std:.1f}, "
            f"glare={glare_fraction:.3f})"
        )
        return report

    @staticmethod
    def _compute_masked_contrast(gray: np.ndarray) -> float:
        """Contrast (pixel-value std) among NON-blown-out pixels only.

        Real motivation (docs/LIMITATIONS.md's fog+glare compound finding):
        a real fog+glare scene measured whole-frame contrast_std≈41 — ABOVE
        FOG_CONTRAST_THRESHOLD (30) — purely because a small, genuinely
        bright glare region pulled the aggregate up, even though the
        non-glare majority of the frame was genuinely hazy (low real
        contrast). Excluding the same near-white band glare_fraction already
        flags (>= _GLARE_PIXEL_VALUE) removes that region's disproportionate
        influence, so this reflects what a viewer looking at just the
        non-blown-out part of the frame would actually see.

        Falls back to the whole-frame std if every pixel is blown out (glare
        fills the entire frame) — there is no "non-glare region" left to
        measure separately in that case, and 0.0 would incorrectly read as
        "perfectly uniform," not "fully saturated."
        """
        non_glare = gray[gray < _GLARE_PIXEL_VALUE]
        if non_glare.size == 0:
            return float(np.std(gray))
        return float(np.std(non_glare))

    def _decide(
        self,
        brightness: float,
        contrast: float,
        glare_fraction: float,
    ) -> SceneCondition:
        # 1. Glare (washed-out, over-bright)
        if brightness > BRIGHTNESS_GLARE_THRESHOLD or glare_fraction > 0.15:
            return SceneCondition.GLARE

        # 2. Fog/rain: low contrast even though not dark
        if contrast < FOG_CONTRAST_THRESHOLD and brightness > self.low_light_threshold:
            return SceneCondition.FOG_RAIN

        # 3. Night / low-light: dark frame
        if brightness < self.low_light_threshold:
            return SceneCondition.LOW_LIGHT_NIGHT

        # 4. Default
        return SceneCondition.CLEAR_DAY
