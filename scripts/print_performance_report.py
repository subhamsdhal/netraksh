#!/usr/bin/env python
"""
NETRAKSH — Prints a human-readable performance report from one or more
edge/data/metrics_<camera_id>.json files (written periodically by
EdgePipeline._report_metrics(); see edge/instrumentation/metrics.py).

Usage:
    python scripts/print_performance_report.py [path/to/metrics_*.json ...]

With no arguments, scans edge/data/ for metrics_*.json.

This script only prints numbers that were actually measured during a real
run — it never estimates or fills in a missing figure. See
docs/PERFORMANCE_REPORT.md for how to turn this into the report used in the
PPT.
"""
import glob
import json
import sys


def load(paths):
    reports = []
    for p in paths:
        try:
            with open(p) as f:
                reports.append((p, json.load(f)))
        except Exception as exc:
            print(f"  (skipped {p}: {exc})")
    return reports


def _print_stage_table(stages: dict) -> None:
    for stage, stats in stages.items():
        if stats.get("count", 0) == 0:
            continue
        print(
            f"    {stage:<24} n={stats['count']:<5} "
            f"mean={stats['mean_ms']:<9} p95={stats['p95_ms']:<9} max={stats['max_ms']}"
        )


def print_report(path: str, data: dict) -> None:
    print(f"\n=== {path} ===")
    print(f"  Uptime: {data.get('uptime_seconds')}s   Measured FPS: {data.get('fps')}")
    print(f"  Alerts generated: {data.get('alerts_generated')}")

    if data.get("psutil_available"):
        print(f"  CPU: {data.get('cpu_percent')}%   RSS: {data.get('rss_mb')} MB")
    else:
        print("  CPU/RSS: not available (psutil not installed in this environment — "
              "pip install psutil for real resource numbers)")

    print("  -- Per-frame stage latency (ms) --")
    _print_stage_table(data.get("frames", {}))

    print("  -- Per-event stage latency (ms) — VERIFIED/ALERTED events only --")
    _print_stage_table(data.get("events", {}))


def main() -> None:
    paths = sys.argv[1:] or glob.glob("edge/data/metrics_*.json")
    if not paths:
        print(
            "No metrics JSON files found. Run the edge pipeline first (python -m edge.main) — "
            "it writes edge/data/metrics_<camera_id>.json every metrics_report_interval_seconds "
            "(default 10s)."
        )
        return
    for path, data in load(paths):
        print_report(path, data)


if __name__ == "__main__":
    main()
