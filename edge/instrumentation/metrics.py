"""
NETRAKSH Edge — Pipeline Performance Instrumentation (architecture v4 §15, MUST HAVE).

Measures real, locally-clocked latency at each edge-pipeline stage instead of
asserting "real-time" without evidence. Two measurement domains:

  1. Per-frame timing (every frame, whether or not an event fires):
       health/condition -> detection+tracking -> task-module/event-decision -> total
  2. Per-event timing (only frames where a candidate is VERIFIED and evidence
     is actually generated -- see edge/temporal/event_verifier.py):
       snapshot -> hash+sign -> chain-store -> enqueue -> total decision-to-enqueue

All numbers are wall-clock milliseconds from `time.perf_counter()` (monotonic,
sub-millisecond resolution) — never estimated, never invented. Percentiles use
nearest-rank on a bounded rolling window so memory stays flat during a
long-running demo.

CPU/RAM sampling uses `psutil` if it is installed; if not, those fields report
`None` rather than a fabricated number — consistent with the project's rule
that an unmeasured quantity is reported as absent, not guessed.

This module has no dependency on anything else in edge/ or shared/, so it is
importable and unit-testable in isolation (a fake `now_fn` clock can be
injected for deterministic FPS tests).
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when psutil isn't installed
    _PSUTIL_AVAILABLE = False


def _percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile. `values` need not be pre-sorted."""
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = math.ceil(pct / 100.0 * len(s)) - 1
    rank = min(max(rank, 0), len(s) - 1)
    return s[rank]


@dataclass
class StageStats:
    """Rolling sample window + summary stats for one named pipeline stage."""
    samples: Deque[float] = field(default_factory=lambda: deque(maxlen=500))

    def add(self, value_ms: float) -> None:
        self.samples.append(value_ms)

    def summary(self) -> Dict[str, float]:
        vals = list(self.samples)
        if not vals:
            return {"count": 0, "mean_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0, "min_ms": 0.0}
        return {
            "count": len(vals),
            "mean_ms": round(sum(vals) / len(vals), 3),
            "p95_ms": round(_percentile(vals, 95), 3),
            "max_ms": round(max(vals), 3),
            "min_ms": round(min(vals), 3),
        }


class PipelineMetrics:
    """
    Owns one StageStats per named stage plus frame-rate and resource
    bookkeeping. Instantiate once per EdgePipeline; the record_* calls are a
    perf_counter() read and a deque append each — near-zero overhead, safe to
    call on every frame/event.
    """

    FRAME_STAGES = ("health_condition_ms", "detection_tracking_ms", "event_processing_ms", "total_frame_ms")
    EVENT_STAGES = ("snapshot_ms", "hash_sign_ms", "chain_store_ms", "enqueue_ms", "total_event_ms")

    def __init__(self, window_size: int = 500, now_fn: Callable[[], float] = time.perf_counter):
        self._now = now_fn
        self._window_size = window_size
        self._frame_stats: Dict[str, StageStats] = {
            s: StageStats(deque(maxlen=window_size)) for s in self.FRAME_STAGES
        }
        self._event_stats: Dict[str, StageStats] = {
            s: StageStats(deque(maxlen=window_size)) for s in self.EVENT_STAGES
        }
        self._frame_timestamps: Deque[float] = deque(maxlen=window_size)
        self._alert_count = 0
        self._start_time = self._now()
        self._last_cpu_percent: Optional[float] = None
        self._last_rss_mb: Optional[float] = None
        if _PSUTIL_AVAILABLE:
            try:
                # First call always returns 0.0 per psutil's own docs — this
                # primes the internal baseline so later reads are meaningful.
                psutil.Process().cpu_percent(interval=None)
            except Exception:
                pass

    def record_frame(self, **stage_ms: float) -> None:
        self._frame_timestamps.append(self._now())
        for stage, value in stage_ms.items():
            if stage in self._frame_stats:
                self._frame_stats[stage].add(value)

    def record_event(self, **stage_ms: float) -> None:
        self._alert_count += 1
        for stage, value in stage_ms.items():
            if stage in self._event_stats:
                self._event_stats[stage].add(value)

    def current_fps(self) -> float:
        """FPS actually measured over the rolling window — not the declared/configured rate."""
        ts = list(self._frame_timestamps)
        if len(ts) < 2:
            return 0.0
        span = ts[-1] - ts[0]
        return (len(ts) - 1) / span if span > 0 else 0.0

    def sample_resources(self) -> None:
        """Best-effort CPU%/RSS sample. No-op (fields stay None) if psutil isn't installed."""
        if not _PSUTIL_AVAILABLE:
            return
        try:
            proc = psutil.Process()
            self._last_cpu_percent = proc.cpu_percent(interval=None)
            self._last_rss_mb = proc.memory_info().rss / (1024 * 1024)
        except Exception as exc:
            logger.debug(f"[Metrics] Resource sampling failed: {exc}")

    def summary(self) -> dict:
        return {
            "uptime_seconds": round(self._now() - self._start_time, 1),
            "fps": round(self.current_fps(), 2),
            "frames": {k: v.summary() for k, v in self._frame_stats.items()},
            "events": {k: v.summary() for k, v in self._event_stats.items()},
            "alerts_generated": self._alert_count,
            "cpu_percent": self._last_cpu_percent,
            "rss_mb": round(self._last_rss_mb, 1) if self._last_rss_mb is not None else None,
            "psutil_available": _PSUTIL_AVAILABLE,
        }

    def dump_json(self, path: str, extra: Optional[dict] = None) -> None:
        """Persist the current summary to disk so it survives the process and
        can be picked up by scripts/print_performance_report.py or attached
        directly to the PPT as real, timestamped evidence of measurement.
        `extra` merges in additional real, already-computed fields (e.g. the
        Adaptive Compute Gate's stats) without this class needing to know
        anything about where they came from."""
        try:
            data = self.summary()
            if extra:
                data.update(extra)
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.debug(f"[Metrics] Failed to write metrics JSON to {path}: {exc}")
