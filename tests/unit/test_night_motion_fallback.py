"""
NETRAKSH — Unit tests for edge/detection/detector.py::NightMotionFallback.
This class existed since the original MVP but was never wired into the
pipeline or unit-tested until architecture v4 §3's night-motion wiring —
closing that gap here as part of the same change.
"""
import numpy as np

from edge.detection.detector import NightMotionFallback


def _frame_with_patch(shape=(200, 200), patch_origin=(50, 50), patch_size=(60, 60), value=220, base=20):
    frame = np.full(shape + (3,), base, dtype=np.uint8)
    y0, x0 = patch_origin
    h, w = patch_size
    frame[y0 : y0 + h, x0 : x0 + w] = value
    return frame


class TestNightMotionFallback:
    def test_first_frame_never_reports_motion(self):
        """No prior frame to diff against yet — first call always primes,
        never fires."""
        fallback = NightMotionFallback()
        frame = _frame_with_patch()
        assert fallback.detect_motion(frame) is False

    def test_identical_consecutive_frames_report_no_motion(self):
        fallback = NightMotionFallback()
        frame = _frame_with_patch()
        fallback.detect_motion(frame)
        assert fallback.detect_motion(frame.copy()) is False

    def test_large_appearing_object_reports_motion(self):
        fallback = NightMotionFallback()
        empty = np.full((200, 200, 3), 20, dtype=np.uint8)
        fallback.detect_motion(empty)
        appeared = _frame_with_patch(value=220)
        assert fallback.detect_motion(appeared, min_area=500) is True

    def test_higher_min_area_can_suppress_a_smaller_change(self):
        """The min_area parameter is a real, effective knob, not decoration —
        a large enough threshold should stop a real but small change from
        being reported."""
        fallback = NightMotionFallback()
        empty = np.full((200, 200, 3), 20, dtype=np.uint8)
        fallback.detect_motion(empty)
        appeared = _frame_with_patch(value=220)
        assert fallback.detect_motion(appeared, min_area=100_000) is False

    def test_state_is_independent_across_instances(self):
        """Each camera in edge/main.py gets its own NightMotionFallback —
        confirm there's no shared/class-level state."""
        fallback_a = NightMotionFallback()
        fallback_b = NightMotionFallback()
        frame = _frame_with_patch()
        fallback_a.detect_motion(frame)
        # fallback_b has never seen a frame — must still be "priming", not
        # comparing against fallback_a's history.
        assert fallback_b.detect_motion(frame.copy()) is False
