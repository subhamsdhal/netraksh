"""
NETRAKSH Edge — Camera Health Monitor (Gate 1).
Determines camera health state BEFORE any detector runs.

Checks:
  1. Frozen / repeated frames: frame-difference variance
  2. Blur / defocus: Laplacian variance
  3. Abnormal exposure: histogram clipping fraction
  4. FPS consistency: measured FPS vs declared
  5. Timestamp drift: system clock vs frame timestamp

Output: CameraHealthReport with state OK / DEGRADED / FAILED and specific reason.

A FAILED camera IMMEDIATELY causes the reliability layer to emit ABSTAIN.
The system never silently interprets a dead camera as "no activity".
"""
from __future__ import annotations

import time
import logging
import os
from collections import deque
from datetime import datetime
from typing import Deque, Tuple, Optional

import cv2
import numpy as np

from shared.constants import (
    BLUR_LAPLACIAN_THRESHOLD,
    CLOCK_DRIFT_DEGRADED_SECONDS,
    CLOCK_DRIFT_FAILED_SECONDS,
    EXPOSURE_CLIPPING_THRESHOLD,
    FPS_DEGRADED_RATIO,
    FROZEN_FRAME_VARIANCE_THRESHOLD,
    CameraHealthState,
    HealthReason,
    StreamState,
)
from shared.schemas import CameraHealthReport

logger = logging.getLogger(__name__)


class CameraHealthMonitor:
    """
    Runs on every frame batch. Maintains a rolling window of recent frames
    and metrics to detect health degradation.
    """

    def __init__(
        self,
        camera_id: str,
        fps_declared: float = 25.0,
        window_size: int = 10,
    ):
        self.camera_id = camera_id
        self.fps_declared = fps_declared
        self._recent_frames: Deque[np.ndarray] = deque(maxlen=window_size)
        self._frame_times: Deque[float] = deque(maxlen=window_size)
        self._last_report_time: float = 0.0
        self._report_interval: float = 2.0  # seconds between health reports
        self._consecutive_frozen_frames: int = 0

    def reset(self) -> None:
        """Reset the monitor's state, e.g., on loop boundaries."""
        self._recent_frames.clear()
        self._frame_times.clear()
        self._consecutive_frozen_frames = 0

    def update(self, frame: Optional[np.ndarray], frame_timestamp: float, stream_state: Optional[StreamState] = None) -> CameraHealthReport:
        """
        Process one frame (if available) and return a health report.
        If frame is None, the stream_state is used to determine health.
        """
        new_frame_added = False
        if frame is not None:
            self._recent_frames.append(frame.copy())
            self._frame_times.append(frame_timestamp)
            new_frame_added = True

        state, reason, metrics = self._evaluate(stream_state, new_frame_added)

        return CameraHealthReport(
            camera_id=self.camera_id,
            health_state=state,
            health_reason=reason,
            health_timestamp=datetime.utcnow(),
            fps_actual=metrics.get("fps_actual"),
            fps_declared=self.fps_declared,
            drift_seconds=metrics.get("drift_seconds"),
            blur_score=metrics.get("blur_score"),
            exposure_clip_fraction=metrics.get("exposure_clip_fraction"),
            frame_variance=metrics.get("frame_variance"),
        )

    def _evaluate(self, stream_state: Optional[StreamState] = None, new_frame_added: bool = True) -> Tuple[CameraHealthState, HealthReason, dict]:
        metrics: dict = {}

        # --- Check 1: Stream state (WP-4.1 integration) ---
        if stream_state == StreamState.FAILED:
            return CameraHealthState.FAILED, HealthReason.STREAM_UNAVAILABLE, metrics
        elif stream_state in (StreamState.STALLING, StreamState.RECONNECTING):
            return CameraHealthState.DEGRADED, HealthReason.STREAM_RECONNECTING, metrics
        elif stream_state in (StreamState.INITIALIZING, StreamState.STOPPED):
            return CameraHealthState.DEGRADED, HealthReason.STREAM_UNAVAILABLE, metrics

        if not self._recent_frames:
            # We don't have a stream state that indicates failure, but no frames yet
            return CameraHealthState.DEGRADED, HealthReason.STREAM_UNAVAILABLE, metrics

        frame = self._recent_frames[-1]

        # --- Check 2: Frozen frame detection ---
        if len(self._recent_frames) >= 2:
            diff = cv2.absdiff(
                cv2.cvtColor(self._recent_frames[-1], cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(self._recent_frames[-2], cv2.COLOR_BGR2GRAY),
            )
            variance = float(np.var(diff))
            metrics["frame_variance"] = variance
            
            if new_frame_added:
                # Very dark sensors can have low absolute variance even while
                # a large object is moving.  Use changed-pixel area as a
                # second signal so healthy-but-dark motion is not mislabelled
                # as a stalled camera; a genuinely static black frame still
                # accumulates toward FAILED.
                low_light_limit = float(os.environ.get("LOW_LIGHT_LUMA_THRESHOLD", "60.0"))
                mean_luma = float(np.mean(cv2.cvtColor(self._recent_frames[-1], cv2.COLOR_BGR2GRAY)))
                changed_fraction = float(np.mean(diff > 3))
                meaningful_dark_motion = mean_luma < low_light_limit and changed_fraction >= float(os.environ.get("NIGHT_HEALTH_MOTION_FRACTION", "0.005"))
                if variance < FROZEN_FRAME_VARIANCE_THRESHOLD and not meaningful_dark_motion:
                    self._consecutive_frozen_frames += 1
                else:
                    self._consecutive_frozen_frames = 0
            
            if self._consecutive_frozen_frames >= 5:
                logger.warning(f"[Health] Camera {self.camera_id}: FROZEN (variance={variance:.2f}, count={self._consecutive_frozen_frames})")
                return CameraHealthState.FAILED, HealthReason.FROZEN_STREAM, metrics

        # --- Check 3: Blur / defocus (Laplacian variance) ---
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        metrics["blur_score"] = blur_score
        if blur_score < BLUR_LAPLACIAN_THRESHOLD:
            logger.debug(f"[Health] Camera {self.camera_id}: blur score={blur_score:.1f} < {BLUR_LAPLACIAN_THRESHOLD}")
            # Excessive blur = DEGRADED (not FAILED — could be fog/night, not necessarily broken)
            return CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR, metrics

        # --- Check 4: Exposure (histogram clipping) ---
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        total_pixels = gray.size
        # cv2.calcHist's returned array shape is (256, 1) on some OpenCV
        # builds and (256,) on others (confirmed different between the
        # opencv-python and opencv-contrib-python-headless builds this
        # project has used at different points — see docs/LIMITATIONS.md).
        # float(hist[i]) works for both: a size-1 (256,1) row or a bare
        # scalar from a (256,) array. The previous hist[i][0] form crashed
        # with "IndexError: invalid index to scalar variable" on any build
        # returning the 1-D shape, on the very first real frame processed.
        # Over-exposed: too many pixels at 255
        overexposed_fraction = float(hist[255]) / total_pixels
        # Under-exposed: too many pixels at 0
        underexposed_fraction = float(hist[0]) / total_pixels
        clip_fraction = max(overexposed_fraction, underexposed_fraction)
        metrics["exposure_clip_fraction"] = clip_fraction
        if clip_fraction > EXPOSURE_CLIPPING_THRESHOLD:
            logger.debug(f"[Health] Camera {self.camera_id}: abnormal exposure clip={clip_fraction:.3f}")
            return CameraHealthState.DEGRADED, HealthReason.ABNORMAL_EXPOSURE, metrics

        # --- Check 5: FPS consistency ---
        if len(self._frame_times) >= 5:
            intervals = [
                self._frame_times[i] - self._frame_times[i - 1]
                for i in range(1, len(self._frame_times))
            ]
            avg_interval = sum(intervals) / len(intervals)
            fps_actual = 1.0 / avg_interval if avg_interval > 0 else 0.0
            metrics["fps_actual"] = fps_actual
            fps_ratio = fps_actual / self.fps_declared if self.fps_declared > 0 else 1.0
            if fps_ratio < FPS_DEGRADED_RATIO:
                logger.debug(f"[Health] Camera {self.camera_id}: FPS degraded (actual={fps_actual:.1f}, declared={self.fps_declared})")
                return CameraHealthState.DEGRADED, HealthReason.FPS_DEGRADED, metrics
        else:
            metrics["fps_actual"] = self.fps_declared  # not enough data yet

        # --- Check 6: Timestamp drift ---
        # Compare system time to frame timestamp (opportunistic NTP check)
        now = time.time()
        drift = abs(now - self._frame_times[-1])
        metrics["drift_seconds"] = drift
        if drift > CLOCK_DRIFT_FAILED_SECONDS:
            logger.warning(f"[Health] Camera {self.camera_id}: CLOCK DRIFT CRITICAL drift={drift:.1f}s")
            return CameraHealthState.FAILED, HealthReason.CLOCK_DRIFT, metrics
        if drift > CLOCK_DRIFT_DEGRADED_SECONDS:
            logger.warning(f"[Health] Camera {self.camera_id}: clock drift={drift:.1f}s (DEGRADED)")
            return CameraHealthState.DEGRADED, HealthReason.CLOCK_DRIFT, metrics

        # --- All checks passed ---
        return CameraHealthState.OK, HealthReason.OK, metrics
