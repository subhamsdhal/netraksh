#!/usr/bin/env python
"""
NETRAKSH — Real before/after false-positive measurement (architecture v4
§11, docs/PERFORMANCE_REPORT.md).

Runs the ACTUAL production components (CameraHealthMonitor,
SceneConditionClassifier, CalibrationModule, DetectionTracker/YOLO,
VirtualFenceModule, make_reliability_decision, EventVerifier,
PipelineMetrics) frame-by-frame against a real video file, comparing:

  - "Without verifier" (required_confirmations=1 for every event type):
    every fence-crossing candidate becomes an alert on the frame it's
    first observed -- this is the old, pre-Event-Verifier behavior.
  - "With verifier" (the shipped defaults, e.g. 3 confirmations for fence
    crossing): a candidate must hold for several consecutive frames before
    becoming an alert.

Both runs see the exact same detections on the exact same frames -- only
the verification policy differs -- so the difference between them is the
real, measured effect of architecture v4 §9's temporal verification, not
an estimate.

This script does NOT touch EvidencePackager, SyncClient, or any certs/DB
file the production EdgePipeline writes -- it is a read-only measurement
harness, not a demo run.

Usage:
    python scripts/run_false_positive_benchmark.py \\
        --video demo/videos/vtest.avi \\
        --zone-x1 0.456 --zone-y1 0.260 --zone-x2 1.0 --zone-y2 0.521 \\
        --report-out docs/PERFORMANCE_REPORT_MEASURED.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.calibration import CalibrationModule
from edge.detection.detector import DetectionTracker
from edge.health.camera_health import CameraHealthMonitor
from edge.instrumentation.metrics import PipelineMetrics
from edge.reliability.decision import make_reliability_decision
from edge.rules.modules import VirtualFenceModule
from edge.temporal.event_verifier import EventVerifier
from shared.constants import CameraHealthState, DecisionState
from shared.schemas import Point, Polygon, ZoneSchema


def build_zone(x1: float, y1: float, x2: float, y2: float) -> ZoneSchema:
    """A rectangular fence zone in normalized coordinates, from a box the
    caller supplies (e.g. visually identified in an actual frame of the
    video under test -- see the --zone-* arguments)."""
    return ZoneSchema(
        zone_id="benchmark-zone",
        camera_id="benchmark",
        name="Benchmark fence zone",
        zone_type="fence",
        polygon=Polygon(points=[
            Point(x=x1, y=y1), Point(x=x2, y=y1),
            Point(x=x2, y=y2), Point(x=x1, y=y2),
        ]),
        owning_command_id="COMMAND_A",
    )


def run_pass(video_path: str, zone: ZoneSchema, required_confirmations: int) -> dict:
    """One full pass over the video with a given Event Verifier confirmation
    depth. Returns real counts and latency stats -- nothing here is
    estimated."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")

    health_monitor = CameraHealthMonitor(camera_id="benchmark", fps_declared=cap.get(cv2.CAP_PROP_FPS) or 25.0)
    condition_classifier = SceneConditionClassifier(camera_id="benchmark")
    calibration = CalibrationModule()
    detector = DetectionTracker(model_size="yolov8n.pt", device="cpu")
    detector.load()
    fence_module = VirtualFenceModule(zones=[zone])
    verifier = EventVerifier(required_confirmations={
        "VIRTUAL_FENCE_CROSSING": required_confirmations,
        "LINE_CROSSING": required_confirmations,
    })
    metrics = PipelineMetrics()

    trajectories: dict = {}
    raw_candidates = 0
    alerts_raised = 0
    frame_idx = 0
    t_video_start = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        frame_height, frame_width = frame.shape[:2]
        t0 = time.perf_counter()

        health = health_monitor.update(frame, time.time())
        condition = condition_classifier.classify(frame)
        t1 = time.perf_counter()

        if health.health_state == CameraHealthState.FAILED:
            metrics.record_frame(
                health_condition_ms=(t1 - t0) * 1000.0, detection_tracking_ms=0.0,
                event_processing_ms=0.0, total_frame_ms=(time.perf_counter() - t0) * 1000.0,
            )
            continue

        threshold = calibration.get_threshold(condition.condition)
        try:
            tracks = detector.detect_and_track(frame, condition.condition, threshold, existing_trajectories=trajectories)
        except Exception as exc:
            print(f"[frame {frame_idx}] detector error: {exc}", file=sys.stderr)
            tracks = []
        t2 = time.perf_counter()

        for t in tracks:
            trajectories[t.track_id] = t.trajectory

        observed_keys_this_tick = set()
        active_by_track_id = {t.track_id: t for t in tracks}

        for track in tracks:
            fence_event = fence_module.check(track, frame_width, frame_height)
            if fence_event:
                raw_candidates += 1
                reliability = make_reliability_decision(health, condition, track.confidence, threshold)
                key = EventVerifier.make_key("benchmark", track.track_id, "VIRTUAL_FENCE_CROSSING", zone.zone_id)
                observed_keys_this_tick.add(key)
                _state, verified_payload = verifier.observe(
                    key, "VIRTUAL_FENCE_CROSSING", fence_event, frame_idx,
                    reliability.decision_state == DecisionState.DETECTED,
                )
                if verified_payload is not None:
                    alerts_raised += 1

        # Mirrors edge/main.py's pending re-check loop EXACTLY: a fence
        # crossing candidate fires .check() only once, on the transition
        # frame -- without this, a >1-confirmation policy could NEVER
        # accumulate confirmations on subsequent frames, which would be a
        # bug in this harness, not a real finding about the pipeline.
        for key, payload in verifier.get_pending_by_type("VIRTUAL_FENCE_CROSSING"):
            if key in observed_keys_this_tick:
                continue
            track = active_by_track_id.get(payload.get("track_id"))
            if track is None:
                continue
            expected_inside = str(payload.get("direction", "")).endswith("OUTSIDE_TO_RESTRICTED")
            if fence_module.get_track_zone(track.track_id, payload.get("zone_id", zone.zone_id)) != expected_inside:
                continue
            reliability = make_reliability_decision(health, condition, track.confidence, threshold)
            _state, verified_payload = verifier.observe(
                key, "VIRTUAL_FENCE_CROSSING", payload, frame_idx,
                reliability.decision_state == DecisionState.DETECTED,
            )
            if verified_payload is not None:
                alerts_raised += 1

        verifier.expire_stale(frame_idx)

        t3 = time.perf_counter()
        metrics.record_frame(
            health_condition_ms=(t1 - t0) * 1000.0,
            detection_tracking_ms=(t2 - t1) * 1000.0,
            event_processing_ms=(t3 - t2) * 1000.0,
            total_frame_ms=(t3 - t0) * 1000.0,
        )

    cap.release()
    wall_seconds = time.perf_counter() - t_video_start
    metrics.sample_resources()

    return {
        "required_confirmations": required_confirmations,
        "frames_processed": frame_idx,
        "raw_candidate_events_fired": raw_candidates,
        "alerts_actually_raised": alerts_raised,
        "wall_seconds": round(wall_seconds, 2),
        "metrics": metrics.summary(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Real before/after false-positive measurement")
    parser.add_argument("--video", required=True)
    parser.add_argument("--zone-x1", type=float, required=True)
    parser.add_argument("--zone-y1", type=float, required=True)
    parser.add_argument("--zone-x2", type=float, required=True)
    parser.add_argument("--zone-y2", type=float, required=True)
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args()

    zone = build_zone(args.zone_x1, args.zone_y1, args.zone_x2, args.zone_y2)

    print(f"=== Pass 1: WITHOUT verifier (required_confirmations=1) === video={args.video}")
    without_verifier = run_pass(args.video, zone, required_confirmations=1)
    print(json.dumps(without_verifier, indent=2))

    print(f"\n=== Pass 2: WITH verifier (shipped default = 3 confirmations) === video={args.video}")
    with_verifier = run_pass(args.video, zone, required_confirmations=3)
    print(json.dumps(with_verifier, indent=2))

    result = {
        "video": args.video,
        "zone": {"x1": args.zone_x1, "y1": args.zone_y1, "x2": args.zone_x2, "y2": args.zone_y2},
        "without_verifier": without_verifier,
        "with_verifier": with_verifier,
    }
    if args.report_out:
        with open(args.report_out, "w") as f:
            json.dump(result, f, indent=2)
        print(f"\nSaved to {args.report_out}")


if __name__ == "__main__":
    main()
