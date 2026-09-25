"""
NETRAKSH Edge — Adaptive Compute Gate (architecture v4 §6).
State-gated inference-rate scheduler: skip full YOLO inference on frames
that are genuinely idle, run it every frame otherwise. No new model, no
resolution changes — the cheapest version of this idea that's actually
worth building, per the architecture doc's own framing of it as "cheap to
build... directly saves power/compute on exactly the hardware constraint
that matters here."

Tiers (deliberately simple for MVP — see docs/LIMITATIONS.md for what a
fuller version would add):
  IDLE:   no motion (reusing CameraHealthMonitor's existing frame-difference
          variance signal — no new expensive per-frame computation), AND no
          currently active track, AND no candidate event pending in the
          Event Verifier -> run full inference only once every
          IDLE_INFERENCE_INTERVAL_FRAMES frames.
  ACTIVE: motion detected, OR at least one active track, OR a candidate is
          pending -> run full inference every frame (the pipeline's existing,
          unchanged rate).

Why gating on "no active tracks" is what makes this safe: ByteTrack needs
continuous per-frame detection to maintain a track's identity and
trajectory. This gate only ever skips inference when there is provably
nothing being tracked yet — the moment something enters frame, the very
next motion-triggered inference tick detects it, and "has an active track"
permanently forces full-rate inference again until that track naturally
ends. Skipping is never applied to a frame that already has something to
lose track of.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.constants import IDLE_INFERENCE_INTERVAL_FRAMES, MOTION_GATE_VARIANCE_THRESHOLD

logger = logging.getLogger(__name__)


class AdaptiveComputeGate:
    """Decides, once per processed frame, whether to run full YOLO inference."""

    def __init__(
        self,
        motion_variance_threshold: float = MOTION_GATE_VARIANCE_THRESHOLD,
        idle_interval_frames: int = IDLE_INFERENCE_INTERVAL_FRAMES,
    ):
        self._motion_threshold = motion_variance_threshold
        self._idle_interval = max(1, idle_interval_frames)
        self._idle_tick = 0
        self._frames_run = 0
        self._frames_skipped = 0
        self._last_state = "ACTIVE"

    def should_run_inference(
        self,
        frame_variance: Optional[float],
        has_active_tracks: bool,
        has_pending_candidates: bool,
    ) -> bool:
        """
        Call once per processed frame, in order, before deciding whether to
        invoke the detector. Returns True if full inference should run this
        frame.
        """
        # No variance reading yet (e.g. the very first frame) — run inference
        # rather than guess; there's nothing unsafe about running an extra
        # inference pass, only about skipping one we shouldn't have.
        is_idle = (
            frame_variance is not None
            and frame_variance < self._motion_threshold
            and not has_active_tracks
            and not has_pending_candidates
        )
        self._last_state = "IDLE" if is_idle else "ACTIVE"

        if not is_idle:
            self._idle_tick = 0
            self._frames_run += 1
            return True

        self._idle_tick += 1
        if self._idle_tick >= self._idle_interval:
            self._idle_tick = 0
            self._frames_run += 1
            return True

        self._frames_skipped += 1
        return False

    def get_state(self) -> str:
        """Current tier ("IDLE" or "ACTIVE") as of the last should_run_inference() call."""
        return self._last_state

    def get_stats(self) -> dict:
        total = self._frames_run + self._frames_skipped
        skip_ratio = (self._frames_skipped / total) if total > 0 else 0.0
        return {
            "state": self._last_state,
            "frames_run": self._frames_run,
            "frames_skipped": self._frames_skipped,
            "skip_ratio": round(skip_ratio, 3),
        }
