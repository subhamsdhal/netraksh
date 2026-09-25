#!/usr/bin/env python3
"""Run bounded, concurrent, *real* EdgePipeline measurements.

This deliberately calls ``EdgePipeline.start`` rather than a detector-only
shortcut: decode, YOLO, ByteTrack, rules, telemetry, event packaging, and sync
all remain on the normal production path.  It is intended for the native SIH
host, not for extrapolating capacity to other hardware.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import threading
import time
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

from edge.main import EdgePipeline
from edge.evidence.packager import EdgeKeyManager


def host_summary() -> dict:
    data = {"platform": platform.platform(), "cpu": platform.processor(), "logical_cores": os.cpu_count()}
    if psutil:
        data["ram_gib"] = round(psutil.virtual_memory().total / 1024 ** 3, 2)
    return data


def make_pipeline(camera_id: str, args: argparse.Namespace, root: Path) -> EdgePipeline:
    camera_root = root / camera_id
    camera_root.mkdir(parents=True, exist_ok=True)
    # Benchmark identities are isolated under the requested output directory.
    # Production workers still require pre-provisioned identities.
    key_dir = camera_root / "keys"
    EdgeKeyManager(str(key_dir / f"{camera_id}.key"), str(key_dir / f"{camera_id}.pub")).load_or_generate(allow_generate=True)
    return EdgePipeline({
        "camera_id": camera_id,
        "camera_name": camera_id,
        "stream_id": f"perf-{camera_id}-{int(time.time())}",
        "video_source": args.video,
        "loop_video": True,
        "zones_config_path": args.zones,
        "backend_url": args.backend_url,
        "key_dir": str(key_dir),
        "chain_db_path": str(camera_root / "chain.db"),
        "sync_db_path": str(camera_root / "sync.db"),
        "clip_dir": str(camera_root / "clips"),
        "metrics_json_path": str(camera_root / "metrics.json"),
        "metrics_report_interval_seconds": 5.0,
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--streams", type=int, choices=(1, 2, 4), required=True)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--profile", choices=("core", "enhanced"), default="enhanced")
    parser.add_argument("--video", default="demo/videos/vtest.avi")
    parser.add_argument("--zones", default="demo/scripts/zones_config.json")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8443")
    parser.add_argument("--output-dir", default="artifacts/full-inference")
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be positive")
    if not Path(args.video).is_file():
        parser.error(f"video not found: {args.video}")

    root = Path(args.output_dir) / f"{args.streams}stream-{args.profile}-{int(time.time())}"
    ids = (["cam-border-01", "cam-checkpoint-01"] if args.streams == 2
           else [f"perf-cam-{n:02d}" for n in range(1, args.streams + 1)])
    pipelines = [make_pipeline(camera_id, args, root) for camera_id in ids]
    threads = [threading.Thread(target=p.start, name=f"benchmark-{p.camera_id}") for p in pipelines]
    process = psutil.Process() if psutil else None
    before_rss = process.memory_info().rss / 1024 ** 2 if process else None
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    time.sleep(args.duration)
    for pipeline in pipelines:
        pipeline.stop()
    for thread in threads:
        thread.join(timeout=20)

    result = {
        "host": host_summary(), "profile": args.profile, "streams_requested": args.streams,
        "duration_seconds": round(time.perf_counter() - started, 2), "rss_start_mb": before_rss,
        "rss_end_mb": round(process.memory_info().rss / 1024 ** 2, 2) if process else None,
        "streams": [],
    }
    for pipeline, thread in zip(pipelines, threads):
        metrics = pipeline.metrics.summary()
        result["streams"].append({
            "camera_id": pipeline.camera_id, "thread_stopped": not thread.is_alive(),
            "adapter_frames_received": pipeline.adapter.frames_received,
            "adapter_frames_dropped": pipeline.adapter.frames_dropped,
            "adapter_queue_depth": pipeline.adapter._queue.qsize(),
            "event_outbox_depth": pipeline.sync_client.get_queue_depth(),
            "telemetry": pipeline._telemetry_metrics, "metrics": metrics,
        })
    root.mkdir(parents=True, exist_ok=True)
    output = root / "summary.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"RESULT={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
