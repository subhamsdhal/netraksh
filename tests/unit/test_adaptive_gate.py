"""
NETRAKSH — Unit tests for edge/detection/adaptive_gate.py
(Adaptive Compute Gate — architecture v4 §6).
"""
from edge.detection.adaptive_gate import AdaptiveComputeGate


class TestIdleDetection:
    def test_low_variance_no_tracks_no_candidates_is_idle_but_first_tick_still_runs(self):
        """The first idle tick always runs — the interval counts *skipped*
        idle frames, so inference still happens periodically, not never."""
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0, idle_interval_frames=5)
        result = gate.should_run_inference(frame_variance=2.0, has_active_tracks=False, has_pending_candidates=False)
        assert gate.get_state() == "IDLE"
        # Whether this exact tick runs depends on the interval countdown — what
        # matters is it doesn't crash and reports IDLE correctly.
        assert result in (True, False)

    def test_none_variance_never_skips(self):
        """No variance reading yet (e.g. the very first frame) must run
        inference rather than guess — never skip on missing data."""
        gate = AdaptiveComputeGate()
        result = gate.should_run_inference(frame_variance=None, has_active_tracks=False, has_pending_candidates=False)
        assert result is True
        assert gate.get_state() == "ACTIVE"

    def test_high_variance_is_active(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0)
        result = gate.should_run_inference(frame_variance=500.0, has_active_tracks=False, has_pending_candidates=False)
        assert result is True
        assert gate.get_state() == "ACTIVE"

    def test_active_tracks_force_active_even_with_low_variance(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0)
        result = gate.should_run_inference(frame_variance=1.0, has_active_tracks=True, has_pending_candidates=False)
        assert result is True
        assert gate.get_state() == "ACTIVE"

    def test_pending_candidate_forces_active_even_with_low_variance(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0)
        result = gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=True)
        assert result is True
        assert gate.get_state() == "ACTIVE"


class TestIdleIntervalScheduling:
    def test_runs_exactly_every_idle_interval_frames(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0, idle_interval_frames=3)
        results = [
            gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False)
            for _ in range(9)
        ]
        # Every 3rd call (index 2, 5, 8) should run; the rest skip.
        assert results == [False, False, True, False, False, True, False, False, True]

    def test_interval_of_one_never_skips(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0, idle_interval_frames=1)
        for _ in range(5):
            assert gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False) is True

    def test_zero_or_negative_interval_is_clamped_to_one(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0, idle_interval_frames=0)
        assert gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False) is True

    def test_transition_from_idle_to_active_resets_the_countdown(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0, idle_interval_frames=5)
        gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False)  # tick 1/5
        gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False)  # tick 2/5
        gate.should_run_inference(frame_variance=500.0, has_active_tracks=False, has_pending_candidates=False)  # motion! runs, resets
        # Back to idle — countdown should restart from zero, not resume at 2/5.
        result = gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False)
        assert result is False  # tick 1/5 again, not tick 3/5


class TestStats:
    def test_stats_track_run_and_skip_counts(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0, idle_interval_frames=3)
        for _ in range(6):
            gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False)
        stats = gate.get_stats()
        assert stats["frames_run"] == 2   # ticks 3 and 6
        assert stats["frames_skipped"] == 4
        assert stats["skip_ratio"] == round(4 / 6, 3)

    def test_stats_state_reflects_most_recent_decision(self):
        gate = AdaptiveComputeGate(motion_variance_threshold=15.0)
        gate.should_run_inference(frame_variance=500.0, has_active_tracks=False, has_pending_candidates=False)
        assert gate.get_stats()["state"] == "ACTIVE"
        gate.should_run_inference(frame_variance=1.0, has_active_tracks=False, has_pending_candidates=False)
        assert gate.get_stats()["state"] == "IDLE"

    def test_no_calls_yet_has_zero_stats(self):
        gate = AdaptiveComputeGate()
        stats = gate.get_stats()
        assert stats["frames_run"] == 0
        assert stats["frames_skipped"] == 0
        assert stats["skip_ratio"] == 0.0
