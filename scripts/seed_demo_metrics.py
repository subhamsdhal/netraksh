"""
NETRAKSH — Seed a realistic performance snapshot against a running
deployment (local or live), via the real public POST /system/metrics
endpoint (no auth, same MVP posture as POST /events).

Frame-level stage latency and FPS below are NOT invented — they are the
exact numbers already measured and written down in
docs/PERFORMANCE_REPORT.md (health_condition_ms/detection_tracking_ms/
event_processing_ms/total_frame_ms mean/p95/max, FPS=21.76, RSS~413-427MB),
from `scripts/run_false_positive_benchmark.py`'s real run against
`demo/videos/vtest.avi`. Only `min_ms` per stage (not in that report's
table) and the per-event stage timings (that report explicitly states
were NOT measured in that run — its own event-level table says
"Not measured in this run") are plausible illustrative values, not
measurements — disclosed here, not hidden.

CPU% is deliberately omitted (psutil_available=False, cpu_percent=None):
docs/PERFORMANCE_REPORT.md's own real reading (0.0%) is explicitly
flagged there as "not credible... do not put 0% CPU in the PPT" — this
script does not substitute a different invented number in its place.

Usage:
    NETRAKSH_BASE_URL=https://your-deployment.onrender.com \
    python scripts/seed_demo_metrics.py
"""
import os

import httpx

BASE = os.environ.get("NETRAKSH_BASE_URL", "http://localhost:8443")

payload = {
    "edge_device_id": "edge-001",
    "uptime_seconds": 795 / 10.0,  # this report's real clip: 795 frames @ 10 fps source rate
    "fps": 21.76,  # docs/PERFORMANCE_REPORT.md, measured FPS (real)
    "frames": {
        # mean/p95/max are the real measured values from docs/PERFORMANCE_REPORT.md;
        # min_ms isn't in that report's table — a plausible value below the
        # mean is used here, not a measurement.
        "health_condition_ms": {"count": 500, "mean_ms": 9.54, "p95_ms": 10.58, "max_ms": 13.43, "min_ms": 6.80},
        "detection_tracking_ms": {"count": 500, "mean_ms": 34.93, "p95_ms": 39.16, "max_ms": 59.08, "min_ms": 24.10},
        "event_processing_ms": {"count": 500, "mean_ms": 0.09, "p95_ms": 0.13, "max_ms": 0.18, "min_ms": 0.04},
        "total_frame_ms": {"count": 500, "mean_ms": 44.55, "p95_ms": 49.17, "max_ms": 69.38, "min_ms": 33.20},
    },
    # docs/PERFORMANCE_REPORT.md's event-level table explicitly says "Not
    # measured in this run" (the benchmark harness skips EvidencePackager
    # to avoid writing real keys/files) — these are plausible illustrative
    # values for lightweight crypto/file-IO operations, not a measurement.
    "events": {
        "snapshot_ms": {"count": 23, "mean_ms": 12.1, "p95_ms": 18.4, "max_ms": 22.0, "min_ms": 8.2},
        "hash_sign_ms": {"count": 23, "mean_ms": 1.8, "p95_ms": 2.9, "max_ms": 3.5, "min_ms": 0.9},
        "chain_store_ms": {"count": 23, "mean_ms": 0.6, "p95_ms": 1.1, "max_ms": 1.4, "min_ms": 0.3},
        "enqueue_ms": {"count": 23, "mean_ms": 0.4, "p95_ms": 0.8, "max_ms": 1.0, "min_ms": 0.2},
        "total_event_ms": {"count": 23, "mean_ms": 14.9, "p95_ms": 22.1, "max_ms": 26.8, "min_ms": 9.8},
    },
    "alerts_generated": 23,  # docs/PERFORMANCE_REPORT.md, real: 52 raw candidates -> 23 alerts
    # psutil WAS available for this real run — only the single end-of-run
    # CPU% sample it produced (0.0) is what docs/PERFORMANCE_REPORT.md
    # flags as not credible ("do not put 0% CPU in the PPT"). cpu_percent
    # is left None rather than substituting a different invented number;
    # rss_mb is real and that same report explicitly says IS credible to
    # quote, so it's included.
    "cpu_percent": None,
    "rss_mb": 419.7,  # midpoint of the report's real 412.9/426.5 MB readings
    "psutil_available": True,
    # No real adaptive-gate skip-ratio numbers exist anywhere in this repo's
    # docs either (the false-positive benchmark run didn't record them) —
    # illustrative only, not a measurement.
    "adaptive_gate": {"state": "ACTIVE", "skip_ratio": 0.18, "frames_run": 410, "frames_skipped": 90},
}

if __name__ == "__main__":
    r = httpx.post(f"{BASE}/system/metrics", json=payload, timeout=30)
    print(r.status_code, r.text)
