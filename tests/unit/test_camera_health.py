"""
NETRAKSH — Unit tests for edge/health/camera_health.py's CameraHealthMonitor
(Gate 1, the hard camera-health override).

This module previously had ZERO dedicated unit tests anywhere in this
project's 376-test suite (confirmed by inspection — every other module has
its own test_*.py; this is a real, previously-undiscovered gap). That gap is
exactly why a real regression went uncaught: `update()`'s exposure check
(`hist[255][0]` / `hist[0][0]`) assumed `cv2.calcHist(...)` always returns a
(256, 1)-shaped array. On this project's current OpenCV build
(opencv-contrib-python-headless 5.0.0, installed for real watchlist face
recognition's `cv2.face` — see docs/ARCHITECTURE.md), it returns (256,)
instead, and `hist[255][0]` raised `IndexError: invalid index to scalar
variable` on the FIRST real frame ever processed — confirmed directly
against the real `demo/videos/vtest.avi` before this fix, not just
hypothesized. `tests/unit/test_reliability.py` never caught this because it
constructs `CameraHealthReport` objects directly, bypassing
`CameraHealthMonitor.update()`'s real frame-processing code entirely.

TestExposureCheckRealFrame below is the direct regression test for that one
bug; the rest of this file is baseline coverage for a module that, despite
being called "MUST HAVE" throughout docs/ARCHITECTURE.md, had none.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from edge.health.camera_health import CameraHealthMonitor
from shared.constants import CameraHealthState


def _frame(value=128, size=(240, 320, 3), noise=0):
    if noise:
        rng = np.random.default_rng(0)
        return np.clip(rng.normal(value, noise, size), 0, 255).astype(np.uint8)
    return np.full(size, value, dtype=np.uint8)


class TestExposureCheckRealFrame:
    """Direct regression coverage for the cv2.calcHist shape bug."""

    def test_calchist_shape_assumption_holds_for_this_build(self):
        """Documents the real, environment-specific root cause: whatever
        shape this build's calcHist returns, float(hist[i]) must not raise."""
        import cv2

        gray = cv2.cvtColor(_frame(noise=20), cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        # The real assertion: this must not raise, regardless of whether
        # this build returns (256,) or (256, 1).
        float(hist[255])
        float(hist[0])

    def test_real_frame_with_moderate_exposure_does_not_crash_and_is_ok(self):
        monitor = CameraHealthMonitor(camera_id="cam-exposure", fps_declared=25.0)
        report = monitor.update(_frame(value=128, noise=30), time.time())
        assert report.health_state in (CameraHealthState.OK, CameraHealthState.DEGRADED)
        assert report.exposure_clip_fraction is not None
        assert 0.0 <= report.exposure_clip_fraction <= 1.0

    def test_overexposed_real_frame_flags_abnormal_exposure(self):
        monitor = CameraHealthMonitor(camera_id="cam-overexposed", fps_declared=25.0)
        # Enough real texture/noise to clear the blur check (Check 3 runs
        # before the exposure check and would otherwise return DEGRADED/
        # excessive_blur first on a too-uniform frame), with a mean/spread
        # that pushes a real fraction of pixels past the 0.10 clipping
        # threshold (shared/constants.py::EXPOSURE_CLIPPING_THRESHOLD).
        frame = _frame(value=250, noise=60)
        report = monitor.update(frame, time.time())
        assert report.exposure_clip_fraction > 0.10
        assert report.health_state == CameraHealthState.DEGRADED
        assert report.health_reason == "abnormal_exposure"

    def test_underexposed_real_frame_flags_abnormal_exposure(self):
        monitor = CameraHealthMonitor(camera_id="cam-underexposed", fps_declared=25.0)
        frame = _frame(value=5, noise=60)
        report = monitor.update(frame, time.time())
        assert report.exposure_clip_fraction > 0.10
        assert report.health_state == CameraHealthState.DEGRADED
        assert report.health_reason == "abnormal_exposure"

    def test_real_video_frames_process_without_crashing(self):
        """The concrete regression scenario: the real demo clip, exactly as
        edge/main.py's _process_frame would call this."""
        import cv2
        from pathlib import Path

        video_path = Path("demo/videos/vtest.avi")
        if not video_path.exists():
            pytest.skip("demo/videos/vtest.avi not present")
        cap = cv2.VideoCapture(str(video_path))
        monitor = CameraHealthMonitor(camera_id="cam-real-video", fps_declared=10.0)
        processed = 0
        for _ in range(20):
            ok, frame = cap.read()
            if not ok:
                break
            report = monitor.update(frame, time.time())  # must not raise
            assert report.health_state in (CameraHealthState.OK, CameraHealthState.DEGRADED,
                                            CameraHealthState.FAILED)
            processed += 1
        cap.release()
        assert processed > 0


class TestFrozenFrameDetection:
    def test_one_low_variance_pair_is_not_failed(self):
        monitor = CameraHealthMonitor(camera_id="cam-frozen-1", fps_declared=25.0)
        frame = _frame(noise=15)
        last = None
        # Provide 2 frames (1 pair).
        for _ in range(2):
            last = monitor.update(frame, time.time())
        assert last.health_state != CameraHealthState.FAILED
        assert last.health_reason != "frozen_stream"

    def test_four_consecutive_low_variance_pairs_is_not_failed(self):
        monitor = CameraHealthMonitor(camera_id="cam-frozen-4", fps_declared=25.0)
        frame = _frame(noise=15)
        last = None
        # 1st frame + 4 duplicates = 5 frames = 4 low-variance pairs.
        for _ in range(5):
            last = monitor.update(frame, time.time())
        assert last.health_state != CameraHealthState.FAILED
        assert last.health_reason != "frozen_stream"

    def test_five_consecutive_low_variance_pairs_is_failed(self):
        monitor = CameraHealthMonitor(camera_id="cam-frozen-5", fps_declared=25.0)
        frame = _frame(noise=15)
        last = None
        # 1st frame + 5 duplicates = 6 frames = 5 low-variance pairs.
        for _ in range(6):
            last = monitor.update(frame, time.time())
        assert last.health_state == CameraHealthState.FAILED
        assert last.health_reason == "frozen_stream"

    def test_low_variance_pair_followed_by_normal_frame_resets_counter(self):
        monitor = CameraHealthMonitor(camera_id="cam-frozen-reset", fps_declared=25.0)
        frame_static = _frame(noise=15)
        # 4 identical frames (3 pairs) -> counter should be 3
        for _ in range(4):
            monitor.update(frame_static, time.time())
        
        # 1 different frame -> counter should reset to 0
        frame_diff = _frame(noise=100)
        monitor.update(frame_diff, time.time())
        
        # 4 more identical frames (3 pairs) -> counter should be 3, total pairs 6 but not consecutive
        last = None
        for _ in range(4):
            last = monitor.update(frame_static, time.time())
            
        assert last.health_state != CameraHealthState.FAILED
        assert last.health_reason != "frozen_stream"

    def test_reset_clears_counter(self):
        monitor = CameraHealthMonitor(camera_id="cam-frozen-reset-method", fps_declared=25.0)
        frame = _frame(noise=15)
        for _ in range(5):
            monitor.update(frame, time.time())
        
        # Counter is now at least 4. Reset it.
        monitor.reset()
        
        last = None
        for _ in range(2):
            last = monitor.update(frame, time.time())
        assert last.health_state != CameraHealthState.FAILED

    def test_pause_does_not_increment_counter(self):
        monitor = CameraHealthMonitor(camera_id="cam-frozen-pause", fps_declared=25.0)
        frame = _frame(noise=15)
        for _ in range(4):
            monitor.update(frame, time.time())
            
        # Pause: update with frame=None
        from shared.constants import StreamState
        last = None
        for _ in range(5):
            last = monitor.update(None, time.time(), stream_state=StreamState.CONNECTED)
            
        assert last.health_state != CameraHealthState.FAILED
        assert last.health_reason != "frozen_stream"

    def test_changing_frames_are_not_frozen(self):
        monitor = CameraHealthMonitor(camera_id="cam-moving", fps_declared=25.0)
        rng = np.random.default_rng(1)
        last = None
        for _ in range(6):
            frame = rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)
            last = monitor.update(frame, time.time())
        assert last.health_reason != "frozen_stream"


class TestBlurDetection:
    def test_uniform_flat_frame_is_blurry(self):
        monitor = CameraHealthMonitor(camera_id="cam-blur", fps_declared=25.0)
        # A perfectly flat frame has zero Laplacian variance -- but it would
        # also register as "frozen" against itself on frame 2+, so check the
        # very first frame's blur_score directly instead.
        report = monitor.update(_frame(value=128, noise=0), time.time())
        assert report.blur_score == 0.0

    def test_textured_frame_has_higher_blur_score(self):
        monitor = CameraHealthMonitor(camera_id="cam-sharp", fps_declared=25.0)
        report = monitor.update(_frame(noise=60), time.time())
        assert report.blur_score > 0.0
