"""
NETRAKSH Edge — Track Continuity Guard (architecture v4 §4).
Mitigates ByteTrack ID fragmentation under brief occlusion — v3/v4 Risk #2 —
using classical computer vision only (color histograms + spatial proximity),
deliberately NOT a learned Re-ID network. See docs/ADR-TEMPORAL.md for the
same "hand-crafted over learned, for this problem size" philosophy applied
to temporal features; this module applies it to tracking.

How it works:
  1. Every frame, the pipeline snapshots each active track's HSV color
     histogram and centroid (edge/main.py — cheap, cv2.calcHist on a small crop).
  2. When a track disappears (ByteTrack drops it — its own track_buffer,
     see edge/config/bytetrack_border.yaml, already gives it some grace),
     that last snapshot is moved into this guard's short-lived "lost pool"
     via remember_lost().
  3. When a genuinely NEW track ID appears, resolve_new_track() checks the
     lost pool for a spatially-close, histogram-similar entry. Above both
     thresholds, the new detection is treated as the SAME physical object —
     the caller reassigns the new track's ID back to the old one — instead
     of silently starting a fresh track with no history.
  4. Unmatched entries expire from the pool after lost_pool_ttl_seconds.

This directly reduces two demo-damaging failure modes: a genuine loiterer
appearing to "leave and re-enter" and double-firing loitering events, and a
briefly-occluded object being wrongly flagged as abandoned because its
original track vanished mid-dwell.

Every re-association is logged (architecture requirement: "log the merge...
as an auditable decision, not a silent correction") — never applied quietly.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from shared.schemas import Point

logger = logging.getLogger(__name__)

DEFAULT_LOST_POOL_TTL_SECONDS = 5.0
DEFAULT_HISTOGRAM_SIMILARITY_THRESHOLD = 0.7
DEFAULT_MAX_CENTROID_DISTANCE = 150.0  # pixels — hand-picked, not calibrated


def compute_histogram(frame: np.ndarray, bbox) -> Optional[np.ndarray]:
    """
    HSV color histogram of a bounding-box crop, normalized so
    cv2.compareHist's correlation method is scale-invariant to crop size.
    Returns None if the crop is degenerate (out of frame bounds, zero area).
    """
    import cv2

    fh, fw = frame.shape[:2]
    x1 = max(0, int(bbox.x1))
    y1 = max(0, int(bbox.y1))
    x2 = min(fw, int(bbox.x2))
    y2 = min(fh, int(bbox.y2))
    if x2 <= x1 or y2 <= y1:
        return None

    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


class TrackContinuityGuard:
    """Classical-CV re-association for tracks lost to brief occlusion."""

    def __init__(
        self,
        lost_pool_ttl_seconds: float = DEFAULT_LOST_POOL_TTL_SECONDS,
        histogram_similarity_threshold: float = DEFAULT_HISTOGRAM_SIMILARITY_THRESHOLD,
        max_centroid_distance: float = DEFAULT_MAX_CENTROID_DISTANCE,
    ):
        self._ttl = lost_pool_ttl_seconds
        self._similarity_threshold = histogram_similarity_threshold
        self._max_distance = max_centroid_distance
        self._lost_pool: Dict[int, dict] = {}

    def remember_lost(
        self,
        track_id: int,
        histogram: Optional[np.ndarray],
        centroid: Point,
        trajectory: List[Point],
        now: float,
    ) -> None:
        """Called when a track disappears — snapshot it for possible re-match."""
        if histogram is None:
            return  # nothing usable to match against later
        self._lost_pool[track_id] = {
            "histogram": histogram,
            "centroid": centroid,
            "trajectory": list(trajectory),
            "lost_at": now,
        }

    def resolve_new_track(
        self, histogram: Optional[np.ndarray], centroid: Point, now: float
    ) -> Optional[Tuple[int, List[Point]]]:
        """
        Checks whether a newly-appeared track is likely the same physical
        object as something recently lost. On a match, removes it from the
        pool and returns (old_track_id, its_prior_trajectory) for the caller
        to splice onto the new detection. Returns None if no match is found
        (or histogram is None — nothing to compare).
        """
        self._expire_internal(now)
        if histogram is None:
            return None

        best_id: Optional[int] = None
        best_score = 0.0
        best_trajectory: List[Point] = []

        for track_id, entry in self._lost_pool.items():
            distance = math.hypot(centroid.x - entry["centroid"].x, centroid.y - entry["centroid"].y)
            if distance > self._max_distance:
                continue
            score = self._similarity(histogram, entry["histogram"])
            if score > best_score:
                best_score = score
                best_id = track_id
                best_trajectory = entry["trajectory"]

        if best_id is not None and best_score >= self._similarity_threshold:
            del self._lost_pool[best_id]
            logger.info(
                f"[ContinuityGuard] Re-associated as lost track {best_id} "
                f"(histogram similarity={best_score:.3f})"
            )
            return best_id, best_trajectory
        return None

    @staticmethod
    def _similarity(hist_a: np.ndarray, hist_b: np.ndarray) -> float:
        import cv2

        return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))

    def expire_stale(self, now: float) -> List[int]:
        """Call once per frame regardless of whether a new track appeared, so
        callers can release any OTHER per-track state (e.g. temporal-feature
        age tracking) for entries that genuinely never got re-matched."""
        return self._expire_internal(now)

    def _expire_internal(self, now: float) -> List[int]:
        stale = [tid for tid, entry in self._lost_pool.items() if (now - entry["lost_at"]) > self._ttl]
        for tid in stale:
            del self._lost_pool[tid]
            logger.debug(f"[ContinuityGuard] Lost track {tid} expired unmatched (TTL={self._ttl}s)")
        return stale

    def get_pool_size(self) -> int:
        return len(self._lost_pool)
