"""
NETRAKSH Edge — Temporal Evidence Intelligence, Mode A (architecture v4 §7).
Computes the `T` (temporal consistency) factor feeding the Hybrid Reliability
Engine (edge/reliability/decision.py) — see docs/ADR-TEMPORAL.md for why this
is hand-crafted features, not a Mamba/SSM/GRU sequence model.

Mode A (implemented here): a hand-weighted, explicitly-labeled combination of
per-track features that need ZERO labeled training data:

  - track_age_score:    how long this track has persisted (a track we've
                         only just started following carries less temporal
                         evidence than one we've watched for a few seconds).
  - path_smoothness:     1 / (1 + variance of frame-to-frame heading-angle
                         change). Purposeful movement is smooth; a jittery,
                         erratic path suggests tracking/detection noise
                         rather than a genuine, trackable object.
  - speed_consistency:   1 / (1 + coefficient of variation of frame-to-frame
                         speed). A track moving at a roughly constant pace —
                         or standing still — is temporally consistent; wild
                         speed swings suggest track fragmentation or noise.
                         NOTE: this deliberately does not penalize raw speed
                         magnitude — a fast-moving vehicle is not inherently
                         less reliable than a slow-moving one, only an
                         erratic one is.

Mode B (NOT implemented — see docs/ADR-TEMPORAL.md): if 200-500 labeled
clips become available, these same features could feed a small
scikit-learn LogisticRegression instead of the hand-picked average below.

All of this is a heuristic, hand-picked default, not calibrated against
labeled data — see docs/LIMITATIONS.md.
"""
from __future__ import annotations

import logging
import math
import statistics
from typing import Dict, List, Optional

from shared.schemas import Point

logger = logging.getLogger(__name__)

MIN_POINTS_FOR_SMOOTHNESS = 3
MIN_POINTS_FOR_SPEED = 2
TRACK_AGE_SATURATION_SECONDS = 5.0  # age at which track_age_score reaches 1.0
STATIONARY_SPEED_EPSILON = 1e-6     # below this, treat as "stationary" (perfectly consistent)


def _angle(dx: float, dy: float) -> float:
    return math.atan2(dy, dx)


def _angle_diff(a1: float, a2: float) -> float:
    """Smallest signed difference between two angles, wrapped to [-pi, pi]."""
    d = a2 - a1
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def _path_smoothness(trajectory: List[Point]) -> float:
    """
    Penalizes the average MAGNITUDE of direction change per step, not its
    variance — a path that turns sharply but *consistently* (e.g. a perfectly
    regular zigzag) must still score low. Variance alone would score that
    case as "smooth" simply because the large turn angle repeats predictably,
    which is not what this feature is meant to capture.
    """
    if len(trajectory) < MIN_POINTS_FOR_SMOOTHNESS:
        return 1.0  # not enough data to judge yet — do not penalize
    angle_deltas = []
    for i in range(2, len(trajectory)):
        p0, p1, p2 = trajectory[i - 2], trajectory[i - 1], trajectory[i]
        a1 = _angle(p1.x - p0.x, p1.y - p0.y)
        a2 = _angle(p2.x - p1.x, p2.y - p1.y)
        angle_deltas.append(abs(_angle_diff(a1, a2)))
    if not angle_deltas:
        return 1.0
    mean_turn = sum(angle_deltas) / len(angle_deltas)
    return 1.0 / (1.0 + mean_turn)


def _speed_consistency(trajectory: List[Point]) -> float:
    if len(trajectory) < MIN_POINTS_FOR_SPEED:
        return 1.0  # not enough data to judge yet — do not penalize
    speeds = [
        math.hypot(trajectory[i].x - trajectory[i - 1].x, trajectory[i].y - trajectory[i - 1].y)
        for i in range(1, len(trajectory))
    ]
    mean_speed = sum(speeds) / len(speeds)
    if mean_speed < STATIONARY_SPEED_EPSILON:
        return 1.0  # stationary — perfectly consistent, not a penalty
    if len(speeds) < 2:
        return 1.0
    variance = statistics.pvariance(speeds)
    coefficient_of_variation = (variance ** 0.5) / mean_speed
    return 1.0 / (1.0 + coefficient_of_variation)


class TrackFeatureTracker:
    """
    Maintains per-track first-seen timestamps (the only state this class
    needs — trajectory data itself already lives on each frame's TrackData
    and in EdgePipeline._trajectories) and computes T on request.

    Real bug this class's callers must avoid (see docs/LIMITATIONS.md and
    docs/PERFORMANCE_REPORT.md's "Reliability Engine behavior" section for
    the full, measured writeup): track_age_score is only meaningful if
    `observe()` (or `compute()`, which also registers first-seen as a side
    effect) is called for a track as soon as it is FIRST SEEN — every frame,
    for every active track — not only when some rule module happens to fire
    an event for it. A caller that only calls `compute()` inside an
    event-triggered branch (e.g. only when a fence-crossing event fires)
    will register `_first_seen` at the moment of that FIRST event, not the
    track's real first-observed frame — so a fence-crossing event, which by
    its nature usually fires exactly once per track at the crossing
    transition, would then ALWAYS see age_seconds=0.0 on that one and only
    call, regardless of how long the track had genuinely been tracked
    beforehand. This was a real, measured bug in both edge/main.py and
    scripts/collect_calibration_data.py until both were fixed to call
    `observe()` unconditionally for every active track every frame.
    """

    def __init__(self, age_saturation_seconds: float = TRACK_AGE_SATURATION_SECONDS):
        self._first_seen: Dict[int, float] = {}
        self._age_saturation_seconds = age_saturation_seconds

    def observe(self, track_id: int, now: float) -> None:
        """Register that this track was seen at `now`, if not already known.
        Call this UNCONDITIONALLY for every active track, every frame — see
        the class docstring for why this must not be left to `compute()`
        alone in a caller that only invokes `compute()` conditionally."""
        if track_id not in self._first_seen:
            self._first_seen[track_id] = now

    def compute(self, track_id: int, trajectory: List[Point], now: float) -> float:
        """Returns T in [0,1] for this track at this point in time.

        Also calls `observe()` as a convenience/safety net, so a caller that
        only ever invokes `compute()` (e.g. these unit tests, or a one-off
        script) still gets correct, self-consistent "first observation has
        zero age" behavior — but a caller whose observations are gated
        behind a conditional event (see class docstring) MUST call
        `observe()` unconditionally itself; this fallback cannot fix that
        case, since by the time `compute()` is reached the damage (the
        wrong, event-triggered timestamp) is already what gets recorded.
        """
        self.observe(track_id, now)
        age_seconds = now - self._first_seen[track_id]
        age_score = min(age_seconds / self._age_saturation_seconds, 1.0)

        smoothness = _path_smoothness(trajectory)
        speed_consistency = _speed_consistency(trajectory)

        t = (age_score + smoothness + speed_consistency) / 3.0
        return max(0.0, min(1.0, t))

    def get_track_age_seconds(self, track_id: int, now: float) -> Optional[float]:
        if track_id not in self._first_seen:
            return None
        return now - self._first_seen[track_id]

    def forget(self, track_id: int) -> None:
        """Call when a track is no longer active, to bound memory growth."""
        self._first_seen.pop(track_id, None)

    def get_tracked_count(self) -> int:
        return len(self._first_seen)
