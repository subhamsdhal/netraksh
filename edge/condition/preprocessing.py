"""
NETRAKSH Edge — CLAHE Preprocessing (architecture v4 §3).
Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) to the
luminance channel of a frame before detection, ONLY when the Scene Condition
Engine has already classified the scene as LOW_LIGHT_NIGHT or FOG_RAIN.

This produces a SEPARATE, enhanced copy used only as the detector's input —
camera health monitoring, scene condition classification, evidence
snapshots, and ANPR/face crops all continue to use the original,
unmodified frame. Enhancing before classification would make a genuinely
dark/foggy scene measure as better than it is, corrupting the very signal
(S in the Hybrid Reliability Engine, edge/reliability/decision.py) that
depends on being honest about scene quality.

Explicitly a MITIGATION, not a fix: the detector is still COCO-pretrained,
not night/fog-trained. CLAHE improves local contrast for the detector's
existing weights; it does not add information the sensor didn't capture,
and it does not close the underlying training-data gap. See
docs/LIMITATIONS.md.
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Tuple

import numpy as np

from shared.constants import SceneCondition

logger = logging.getLogger(__name__)


class ConditionProcessingPolicy(str, Enum):
    STANDARD = "standard"
    LOW_LIGHT = "low_light"
    ADVERSE_WEATHER = "adverse_weather"
    GLARE_AWARE = "glare_aware"


class ConditionRouter:
    """
    Decouples 'what is the scene' from 'how should we process it'.
    Provides safe fallback to STANDARD if the feature flag ADVERSE_PROCESSING is disabled.
    """

    def __init__(self):
        # Adaptive low-light enhancement is the safe demo default: it is
        # applied only after measured scene classification, never to daylight
        # frames. Set ADVERSE_PROCESSING=disabled to opt out explicitly.
        self.mode = os.environ.get("ADVERSE_PROCESSING", "adaptive").lower()
        if self.mode not in ("disabled", "adaptive"):
            logger.warning(f"[ConditionRouter] Invalid ADVERSE_PROCESSING='{self.mode}', falling back to 'disabled'.")
            self.mode = "disabled"

    def route(self, condition: SceneCondition) -> ConditionProcessingPolicy:
        if self.mode == "disabled":
            return ConditionProcessingPolicy.STANDARD

        if condition == SceneCondition.LOW_LIGHT_NIGHT:
            return ConditionProcessingPolicy.LOW_LIGHT
        elif condition == SceneCondition.FOG_RAIN:
            return ConditionProcessingPolicy.ADVERSE_WEATHER
        elif condition == SceneCondition.GLARE:
            return ConditionProcessingPolicy.GLARE_AWARE
        else:
            return ConditionProcessingPolicy.STANDARD


# Hand-picked defaults matching the commonly-cited starting point for CLAHE
# on natural images — not calibrated against this project's own footage.
DEFAULT_CLIP_LIMIT = 2.0
DEFAULT_TILE_GRID_SIZE: Tuple[int, int] = (8, 8)


def enhance_for_detection(
    frame: np.ndarray,
    policy: ConditionProcessingPolicy,
    clip_limit: float = DEFAULT_CLIP_LIMIT,
    tile_grid_size: Tuple[int, int] = DEFAULT_TILE_GRID_SIZE,
) -> np.ndarray:
    """
    Applies condition-specific preprocessing (e.g. CLAHE for LOW_LIGHT) based on the policy.
    Never mutates the input in place.
    """
    if policy == ConditionProcessingPolicy.STANDARD:
        return frame

    if policy in (ConditionProcessingPolicy.LOW_LIGHT, ConditionProcessingPolicy.ADVERSE_WEATHER):
        import cv2

        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)

        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
        l_enhanced = clahe.apply(l_channel)

        enhanced_lab = cv2.merge((l_enhanced, a_channel, b_channel))
        return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
    
    # GLARE_AWARE or unknown -> pass through for now
    return frame
