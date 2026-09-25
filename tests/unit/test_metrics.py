"""
NETRAKSH — Unit tests for edge/instrumentation/metrics.py
(architecture v4 §15 — Performance Instrumentation, MUST HAVE).

Uses an injectable fake clock so FPS/latency math is deterministic instead
of depending on real wall-clock timing in CI.
"""
import json
import os
from collections import deque

from edge.instrumentation.metrics import PipelineMetrics, StageStats, _percentile


class _FakeClock:
    """Deterministic monotonic clock for tests: advance() moves it forward,
    the object itself is callable so it can be passed as `now_fn`."""

    def __init__(self, start: float = 0.0):
        self.t = start

    def advance(self, dt: float) -> float:
        self.t += dt
        return self.t

    def __call__(self) -> float:
        return self.t


class TestPercentile:
    def test_single_value(self):
        assert _percentile([5.0], 95) == 5.0

    def test_empty_list(self):
        assert _percentile([], 95) == 0.0

    def test_p95_of_1_to_100(self):
        values = [float(i) for i in range(1, 101)]
        # nearest-rank: ceil(0.95*100)-1 = 94 (0-indexed) -> sorted[94] == 95.0
        assert _percentile(values, 95) == 95.0

    def test_unsorted_input_is_handled(self):
        values = [30.0, 10.0, 20.0]
        assert _percentile(values, 50) == 20.0


class TestStageStats:
    def test_empty_summary(self):
        s = StageStats()
        summary = s.summary()
        assert summary["count"] == 0
        assert summary["mean_ms"] == 0.0

    def test_mean_and_p95(self):
        s = StageStats()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            s.add(v)
        summary = s.summary()
        assert summary["count"] == 5
        assert summary["mean_ms"] == 30.0
        assert summary["max_ms"] == 50.0
        assert summary["min_ms"] == 10.0

    def test_rolling_window_bounds_memory(self):
        s = StageStats(samples=deque(maxlen=3))
        for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
            s.add(v)
        assert list(s.samples) == [3.0, 4.0, 5.0]


class TestPipelineMetricsFrames:
    def test_record_frame_populates_named_stages(self):
        m = PipelineMetrics()
        m.record_frame(health_condition_ms=1.0, detection_tracking_ms=20.0,
                        event_processing_ms=2.0, total_frame_ms=23.0)
        summary = m.summary()
        assert summary["frames"]["total_frame_ms"]["count"] == 1
        assert summary["frames"]["total_frame_ms"]["mean_ms"] == 23.0
        assert summary["frames"]["detection_tracking_ms"]["mean_ms"] == 20.0

    def test_unknown_stage_kwarg_is_ignored_not_an_error(self):
        m = PipelineMetrics()
        m.record_frame(total_frame_ms=5.0, made_up_stage_ms=999.0)
        assert "made_up_stage_ms" not in m.summary()["frames"]

    def test_fps_computed_from_fake_clock(self):
        clock = _FakeClock()
        m = PipelineMetrics(now_fn=clock)
        # Simulate 10 frames at exactly 25 FPS (40ms apart)
        for _ in range(10):
            clock.advance(0.04)
            m.record_frame(total_frame_ms=5.0)
        assert abs(m.current_fps() - 25.0) < 0.01

    def test_fps_zero_with_fewer_than_two_frames(self):
        m = PipelineMetrics()
        assert m.current_fps() == 0.0
        m.record_frame(total_frame_ms=5.0)
        assert m.current_fps() == 0.0


class TestPipelineMetricsEvents:
    def test_record_event_increments_alert_count(self):
        m = PipelineMetrics()
        m.record_event(snapshot_ms=1.0, hash_sign_ms=2.0, chain_store_ms=3.0,
                        enqueue_ms=1.0, total_event_ms=7.0)
        summary = m.summary()
        assert summary["alerts_generated"] == 1
        assert summary["events"]["total_event_ms"]["mean_ms"] == 7.0

    def test_multiple_events_average_correctly(self):
        m = PipelineMetrics()
        m.record_event(total_event_ms=10.0)
        m.record_event(total_event_ms=20.0)
        assert m.summary()["events"]["total_event_ms"]["mean_ms"] == 15.0
        assert m.summary()["alerts_generated"] == 2


class TestResourceSamplingIsHonest:
    def test_fields_present_and_never_fabricated(self):
        """Whether or not psutil is installed, cpu_percent/rss_mb must never
        be a made-up number — either a real psutil reading or None."""
        m = PipelineMetrics()
        m.sample_resources()
        summary = m.summary()
        assert "cpu_percent" in summary and "rss_mb" in summary
        assert "psutil_available" in summary
        if not summary["psutil_available"]:
            assert summary["cpu_percent"] is None
            assert summary["rss_mb"] is None


class TestDumpJson:
    def test_dump_json_writes_valid_json(self, tmp_path):
        m = PipelineMetrics()
        m.record_frame(total_frame_ms=12.0)
        out_path = os.path.join(str(tmp_path), "nested", "metrics.json")
        m.dump_json(out_path)
        assert os.path.exists(out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert data["frames"]["total_frame_ms"]["count"] == 1

    def test_dump_json_does_not_raise_on_bad_path(self):
        m = PipelineMetrics()
        # A path with an illegal null byte should be swallowed, not crash the pipeline.
        m.dump_json("\x00/impossible/path/metrics.json")

    def test_dump_json_merges_extra_fields(self, tmp_path):
        """edge/main.py uses this to attach the Adaptive Compute Gate's stats
        without PipelineMetrics needing to know anything about that gate."""
        m = PipelineMetrics()
        m.record_frame(total_frame_ms=12.0)
        out_path = os.path.join(str(tmp_path), "metrics.json")
        m.dump_json(out_path, extra={"adaptive_gate": {"state": "IDLE", "skip_ratio": 0.8}})
        with open(out_path) as f:
            data = json.load(f)
        assert data["adaptive_gate"] == {"state": "IDLE", "skip_ratio": 0.8}
        assert data["frames"]["total_frame_ms"]["count"] == 1  # own fields still present

    def test_dump_json_without_extra_is_unchanged(self, tmp_path):
        m = PipelineMetrics()
        out_path = os.path.join(str(tmp_path), "metrics.json")
        m.dump_json(out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert "adaptive_gate" not in data
