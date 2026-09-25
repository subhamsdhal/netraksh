"""
NETRAKSH Edge — AI Benchmark Harness (Phase 3 Step 0)
Designed to run existing AI pipeline components in isolated READ-ONLY mode to collect
latency, FPS, memory, and detection statistics without modifying the production DB.
"""
import argparse
import json
import logging
import os
import sys
import time
import glob
from pathlib import Path

import cv2
import numpy as np

# Ensure repository root is on the Python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.detector import DetectionTracker, NightMotionFallback
from edge.reliability.decision import make_reliability_decision

from shared.constants import DetectionClass, SceneCondition
from shared.schemas import BoundingBox, Point, TrackData

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | [Benchmark] %(message)s")
logger = logging.getLogger("benchmark")

def get_rss_mb() -> float:
    if HAS_PSUTIL:
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    return 0.0

def run_benchmark(
    video_path: str = None,
    image_dir: str = None,
    annotations_path: str = None,
    quick_mode: bool = False,
    detector_model: str = "yolov8n.pt",
    tracker_config: str = None,
):
    logger.info("Initializing Benchmark Harness (Phase 3 Step 0)...")
    logger.info(f"OS: {sys.platform} | Python: {sys.version.split()[0]}")
    logger.info(f"RSS Before Init: {get_rss_mb():.2f} MB")

    # Metrics storage
    metrics = {
        "timestamp": time.time(),
        "hardware": "NOT MEASURED",  # Can be expanded with platform/cpuinfo
        "os": sys.platform,
        "python": sys.version.split()[0],
        "model": detector_model,
        "tracker": tracker_config or "default",
        "face_engine": os.environ.get("FACE_RECOGNITION_ENGINE", "lbph").lower(),
        "video_fps": 0,
        "resolution": "UNKNOWN",
        "frames_processed": 0,
        "warmup_frames": 10,
        "latency": {
            "detection": [],
            "tracking": [], # Integrated in detect_and_track for YOLO
            "face": [],
            "anpr": [],
            "behavior": [],
            "scene": [],
            "reliability": [],
            "end_to_end": []
        },
        "counts": {
            "objects_detected": 0,
            "active_tracks": 0,
            "faces_processed": 0,
            "faces_matched": 0,
            "ocr_attempts": 0,
            "ocr_successes": 0
        },
        "pixel_area_distribution": {
            "small": 0,
            "medium": 0,
            "large": 0
        },
        "reliability": {
            "D": [], "T": [], "S": [], "H": [], "R": []
        },
        "memory": {
            "rss_before": get_rss_mb(),
            "rss_during_peak": 0.0,
            "rss_after": 0.0
        },
        "tracking": {
            "tracker_used": os.environ.get("TRACKER", "bytetrack").lower(),
            "continuity_guard_enabled": os.environ.get("CONTINUITY_GUARD", "true").lower() == "true",
            "active_tracks_per_frame": [],
            "tracks_created": 0,
            "tracks_terminated": 0,
            "continuity_interventions": 0,
            "track_lifetimes": {},
        },
        "ground_truth_status": "NOT MEASURABLE — NO GROUND TRUTH AVAILABLE"
    }

    if annotations_path and os.path.exists(annotations_path):
        metrics["ground_truth_status"] = f"LOADED: {annotations_path}"
    
    # Init components
    logger.info("Loading SceneConditionClassifier...")
    scene_classifier = SceneConditionClassifier(camera_id="cam-benchmark")

    logger.info(f"Loading DetectionTracker ({detector_model})...")
    detector = DetectionTracker(model_size=detector_model, tracker_config=tracker_config)
    detector.load()

    from edge.rules.modules import VirtualFenceModule, ANPRModule, FaceDetectionModule
    from shared.schemas import ZoneSchema, Polygon
    from shared.constants import ZoneType

    logger.info("Loading Task Modules (Face, ANPR, Fence)...")
    zone = ZoneSchema(
        camera_id="cam-benchmark",
        name="Global Benchmark Zone",
        zone_type=ZoneType.BOUNDARY,
        polygon=Polygon(points=[Point(x=0,y=0), Point(x=10000,y=0), Point(x=10000,y=10000), Point(x=0,y=10000)]),
        owning_command_id="CMD-1"
    )
    zones = [zone]
    
    anpr = ANPRModule(zones=zones)
    face = FaceDetectionModule(zones=zones)
    fence = VirtualFenceModule(zones=zones)
    
    from edge.tracking.continuity_guard import TrackContinuityGuard, compute_histogram
    continuity_guard = TrackContinuityGuard() if metrics["tracking"]["continuity_guard_enabled"] else None
    
    # Tracking bookkeeping
    known_track_ids = set()
    track_last_snapshot = {}
    track_history = {}
    
    behavior_analytics_enabled = str(os.environ.get("BEHAVIOR_ANALYTICS", "false")).lower() == "true"
    if behavior_analytics_enabled:
        from edge.temporal.trajectory import TrajectoryFeatureLayer
        from edge.rules.behavior_analytics import BehaviorCorrelationEngine
        trajectory_layer = TrajectoryFeatureLayer()
        behavior_correlation = BehaviorCorrelationEngine(zones)
    else:
        trajectory_layer = None
        behavior_correlation = None
    
    if metrics["face_engine"] == "embedding" and face._embedding_engine is None:
        metrics["embedding_benchmark"] = "NOT RUN"
        metrics["embedding_benchmark_reason"] = "NO VERIFIED MODEL CONFIGURED"
        logger.warning("Embedding benchmark NOT RUN. Reason: NO VERIFIED MODEL CONFIGURED")
    elif metrics["face_engine"] == "embedding":
        metrics["embedding_benchmark"] = "READY"
        metrics["embedding_benchmark_reason"] = "Verified model loaded"
    
    metrics["memory"]["rss_after_init"] = get_rss_mb()
    logger.info(f"RSS After Init: {metrics['memory']['rss_after_init']:.2f} MB")

    frames_to_process = []
    
    # Input Loading
    if video_path:
        logger.info(f"Opening video: {video_path}")
        cap = cv2.VideoCapture(video_path)
        metrics["video_fps"] = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        metrics["resolution"] = f"{width}x{height}"
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            frames_to_process.append(frame)
            if quick_mode and len(frames_to_process) >= 100:
                break
        cap.release()
    elif image_dir:
        logger.info(f"Loading images from: {image_dir}")
        img_files = sorted(glob.glob(os.path.join(image_dir, "*.*")))
        for f in img_files:
            frame = cv2.imread(f)
            if frame is not None:
                frames_to_process.append(frame)
                if len(frames_to_process) == 1:
                    metrics["resolution"] = f"{frame.shape[1]}x{frame.shape[0]}"
            if quick_mode and len(frames_to_process) >= 100:
                break
    else:
        logger.error("No video or image directory provided.")
        return

    logger.info(f"Loaded {len(frames_to_process)} frames for processing.")

    # Processing Loop
    for i, frame in enumerate(frames_to_process):
        is_warmup = i < metrics["warmup_frames"]
        
        t_e2e_start = time.perf_counter()

        # Scene Classification
        t0 = time.perf_counter()
        condition = scene_classifier.classify(frame)
        t_scene = time.perf_counter() - t0

        # Detection & Tracking
        t0 = time.perf_counter()
        tracks = detector.detect_and_track(frame, condition, confidence_threshold=0.3)
        
        # Apply continuity guard
        if continuity_guard and not is_warmup:
            now = time.time()
            for track in tracks:
                if track.track_id not in known_track_ids:
                    metrics["tracking"]["tracks_created"] += 1
                    histogram = compute_histogram(frame, track.bbox)
                    match = continuity_guard.resolve_new_track(histogram, track.bbox.centroid, now)
                    if match is not None:
                        matched_id, matched_traj = match
                        track.track_id = matched_id
                        track.trajectory = list(matched_traj) + list(track.trajectory)
                        metrics["tracking"]["continuity_interventions"] += 1
                known_track_ids.add(track.track_id)
            
            # Record tracking lifetime
            for track in tracks:
                if track.track_id not in metrics["tracking"]["track_lifetimes"]:
                    metrics["tracking"]["track_lifetimes"][track.track_id] = 0
                metrics["tracking"]["track_lifetimes"][track.track_id] += 1
                track_history[track.track_id] = track.trajectory
                track_last_snapshot[track.track_id] = {
                    "histogram": compute_histogram(frame, track.bbox),
                    "centroid": track.bbox.centroid,
                }
            
            # Clean up stale trajectories and feed continuity guard
            active_ids = {t.track_id for t in tracks}
            stale = [k for k in track_history if k not in active_ids]
            for k in stale:
                metrics["tracking"]["tracks_terminated"] += 1
                snapshot = track_last_snapshot.get(k)
                if snapshot and snapshot["histogram"] is not None:
                    continuity_guard.remember_lost(
                        k, snapshot["histogram"], snapshot["centroid"], track_history.get(k, []), now
                    )
                del track_history[k]
                del track_last_snapshot[k]

        t_detect = time.perf_counter() - t0

        if not is_warmup:
            metrics["counts"]["objects_detected"] += len(tracks)
            metrics["counts"]["active_tracks"] = max(metrics["counts"]["active_tracks"], len(tracks))
            metrics["tracking"]["active_tracks_per_frame"].append(len(tracks))
            
            for t in tracks:
                w = t.bbox.x2 - t.bbox.x1
                h = t.bbox.y2 - t.bbox.y1
                area = w * h
                if area < 1024:
                    metrics["pixel_area_distribution"]["small"] += 1
                elif area < 9216:
                    metrics["pixel_area_distribution"]["medium"] += 1
                else:
                    metrics["pixel_area_distribution"]["large"] += 1

        # Face & ANPR
        t0 = time.perf_counter()
        health_state = "HEALTHY"
        events = []
        for track in tracks:
            # ANPR
            anpr_evt = anpr.process(track, frame)
            if anpr_evt:
                events.append({"track": track, "event_type": "anpr_read"})
                if not is_warmup:
                    metrics["counts"]["ocr_successes"] += 1
            if track.detection_class == DetectionClass.VEHICLE or track.detection_class == "VEHICLE":
                if not is_warmup:
                    metrics["counts"]["ocr_attempts"] += 1
                
            # Face
            face_evt = face.detect(track, frame)
            if face_evt:
                events.append({"track": track, "event_type": "face_recognized"})
                if not is_warmup:
                    metrics["counts"]["faces_matched"] += 1
            if track.detection_class == DetectionClass.PERSON or track.detection_class == "PERSON":
                if not is_warmup:
                    metrics["counts"]["faces_processed"] += 1

        t_orchestrator = time.perf_counter() - t0

        # Behavior Analytics
        t0 = time.perf_counter()
        if behavior_analytics_enabled and not is_warmup:
            now = time.time()
            # Feed track trajectories into behavior system
            features = trajectory_layer.update(tracks, now)
            # We don't have standard events fully simulated here, but we pass what we have
            adv_events = behavior_correlation.update(tracks, features, [], now)
        t_behavior = time.perf_counter() - t0

        # Reliability
        t0 = time.perf_counter()
        from shared.schemas import CameraHealthReport, SceneConditionReport
        from shared.constants import CameraHealthState, HealthReason, SceneCondition
        
        # Mock reports for benchmark purposes
        health_rep = CameraHealthReport(
            camera_id="cam-benchmark", health_state=CameraHealthState.OK, health_reason=HealthReason.OK
        )
        cond_rep = SceneConditionReport(
            camera_id="cam-benchmark", condition=SceneCondition.CLEAR_DAY, brightness_mean=100.0, contrast_std=50.0, glare_fraction=0.0
        )
        for evt in events:
            track = evt.get("track")
            rel = make_reliability_decision(
                health_report=health_rep,
                condition_report=cond_rep,
                detector_confidence=track.confidence if track else 0.5,
                calibration_threshold=0.5,
                temporal_score=min(1.0, len(track.trajectory) / 30.0) if track else 0.1
            )
            if not is_warmup:
                metrics["reliability"]["R"].append(rel.score_r if rel.score_r is not None else 0.0)
                metrics["reliability"]["D"].append(rel.score_d if rel.score_d is not None else 0.0)
                metrics["reliability"]["T"].append(rel.score_t if rel.score_t is not None else 0.0)
                metrics["reliability"]["S"].append(rel.score_s if rel.score_s is not None else 0.0)
                metrics["reliability"]["H"].append(rel.score_h if rel.score_h is not None else 0.0)
        t_reliability = time.perf_counter() - t0

        t_e2e = time.perf_counter() - t_e2e_start

        if not is_warmup:
            metrics["latency"]["scene"].append(t_scene)
            metrics["latency"]["detection"].append(t_detect)
            metrics["latency"]["anpr"].append(t_orchestrator) # Combined for now
            metrics["latency"]["face"].append(t_orchestrator) # Combined for now
            if behavior_analytics_enabled:
                metrics["latency"]["behavior"].append(t_behavior)
            metrics["latency"]["reliability"].append(t_reliability)
            metrics["latency"]["end_to_end"].append(t_e2e)
            metrics["frames_processed"] += 1
            
            cur_rss = get_rss_mb()
            metrics["memory"]["rss_during_peak"] = max(metrics["memory"]["rss_during_peak"], cur_rss)
            
        if (i + 1) % 50 == 0:
            logger.info(f"Processed {i + 1}/{len(frames_to_process)} frames...")

    metrics["memory"]["rss_after"] = get_rss_mb()
    logger.info("Benchmark complete. Generating report...")
    
    _generate_markdown_report(metrics)
    
def _generate_markdown_report(metrics: dict):
    os.makedirs("docs", exist_ok=True)
    report_path = "docs/PHASE3_AI_BENCHMARK.md"
    
    def _agg(lst):
        if not lst:
            return {"mean": 0, "p95": 0, "min": 0, "max": 0}
        return {
            "mean": float(np.mean(lst)),
            "p95": float(np.percentile(lst, 95)),
            "min": float(np.min(lst)),
            "max": float(np.max(lst))
        }

    scene_agg = _agg(metrics["latency"]["scene"])
    det_agg = _agg(metrics["latency"]["detection"])
    rel_agg = _agg(metrics["latency"]["reliability"])
    e2e_agg = _agg(metrics["latency"]["end_to_end"])

    md = f"""# NETRAKSH Phase 3 AI Benchmark

*Generated on: {time.ctime(metrics["timestamp"])}*

## 1. Environment
- **OS**: {metrics["os"]}
- **Python**: {metrics["python"]}
- **Hardware**: {metrics["hardware"]}

## 2. Input Data
- **Resolution**: {metrics["resolution"]}
- **Source FPS**: {metrics["video_fps"]}
- **Frames Processed**: {metrics["frames_processed"]} (excl. {metrics["warmup_frames"]} warmup)

## 3. Current Baseline Configuration
- **Detector**: {metrics["model"]}
- **Tracker**: {metrics["tracker"]}

## 4. Detection Metrics
- **Mean Detector+Tracker Latency**: {det_agg['mean']*1000:.2f} ms (p95: {det_agg['p95']*1000:.2f} ms)
- **Effective FPS**: {1.0/det_agg['mean'] if det_agg['mean'] > 0 else 0:.1f}
- **Total Objects Detected**: {metrics["counts"]["objects_detected"]}
- **Pixel-Area Categories**: Small (<32x32): {metrics["pixel_area_distribution"]["small"]} | Medium: {metrics["pixel_area_distribution"]["medium"]} | Large (>96x96): {metrics["pixel_area_distribution"]["large"]}
- **Precision/Recall**: {metrics["ground_truth_status"]}

## 5. Tracking Metrics
- **Tracker Used**: {metrics["tracking"]["tracker_used"]}
- **Continuity Guard Enabled**: {metrics["tracking"]["continuity_guard_enabled"]}
- **Tracks Created**: {metrics["tracking"]["tracks_created"]}
- **Tracks Terminated**: {metrics["tracking"]["tracks_terminated"]}
- **Continuity Guard Interventions (Fragmentation Proxy)**: {metrics["tracking"]["continuity_interventions"]}
- **Average Track Lifetime**: {float(np.mean(list(metrics["tracking"]["track_lifetimes"].values()))) if metrics["tracking"]["track_lifetimes"] else 0:.1f} frames
- **Median Track Lifetime**: {float(np.median(list(metrics["tracking"]["track_lifetimes"].values()))) if metrics["tracking"]["track_lifetimes"] else 0:.1f} frames
- **Peak Active Tracks**: {metrics["counts"]["active_tracks"]}
- **IDF1/MOTA/ID Switches**: {metrics["ground_truth_status"]}

## 6. Face Metrics
- **Face Processing Latency**: Included in Orchestrator
- **Matches/Unknowns**: {metrics["counts"]["faces_matched"]}
- **ROC/Accuracy**: {metrics["ground_truth_status"]}

## 7. ANPR Metrics
- **OCR Latency**: Included in Orchestrator
- **OCR Attempts**: {metrics["counts"]["ocr_attempts"]}
- **Exact-Match Rate**: {metrics["ground_truth_status"]}

## 7.5 Behavioral Intelligence
- **Behavior Correlation Latency**: {_agg(metrics["latency"].get("behavior", []))['mean']*1000:.2f} ms
- **Events Generated**: NOT TRACKED IN BENCHMARK HARNESS YET

## 8. Reliability Metrics
- **Mean Processing Latency**: {rel_agg['mean']*1000:.2f} ms
- **R (Final Score) Mean**: {np.mean(metrics['reliability']['R']) if metrics['reliability']['R'] else 0:.2f}

## 9. Scene-Condition Metrics
- **Mean Latency**: {scene_agg['mean']*1000:.2f} ms

## 10. End-to-End Metrics
- **Mean Latency**: {e2e_agg['mean']*1000:.2f} ms (p95: {e2e_agg['p95']*1000:.2f} ms)
- **Mean Effective Throughput**: {1.0/e2e_agg['mean'] if e2e_agg['mean'] > 0 else 0:.1f} FPS

## 11. Memory Metrics
- **RSS Before**: {metrics['memory']['rss_before']:.2f} MB
- **RSS Peak During**: {metrics['memory']['rss_during_peak']:.2f} MB
- **RSS After**: {metrics['memory']['rss_after']:.2f} MB

## 12. Ground-Truth Availability
{metrics["ground_truth_status"]}

## 13. Metrics that are NOT MEASURABLE
- Precision, Recall, mAP, IDF1, MOTA, ID Switches, True OCR Accuracy, Face Recognition ROC are all **NOT MEASURABLE** at this time due to lack of ground truth labels for the evaluated videos.

## 14. Known Benchmark Limitations
- Face and ANPR latencies are grouped under Orchestrator latency due to current architecture coupling.
- No ground truth datasets currently exist in the repository to measure True Positives vs False Positives.

## 15. Reproduction Command
```bash
python -m edge.benchmark_runner --video <path_to_video>
```
"""
    with open(report_path, "w") as f:
        f.write(md)
    logger.info(f"Report written to {report_path}")
    
    with open("docs/benchmark_raw.json", "w") as f:
        json.dump(metrics, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser("NETRAKSH Phase 3 AI Benchmark Harness")
    parser.add_argument("--video", type=str, help="Path to test video")
    parser.add_argument("--images", type=str, help="Path to image directory")
    parser.add_argument("--annotations", type=str, help="Path to ground truth annotations")
    parser.add_argument("--quick", action="store_true", help="Run in quick mode (100 frames max)")
    parser.add_argument("--detector", type=str, default="yolov8n.pt", help="Detector model size")
    args = parser.parse_args()
    
    # Override environment manually for the benchmark harness if passed
    if args.detector:
        os.environ["DETECTOR_MODEL"] = args.detector
        
    run_benchmark(
        video_path=args.video,
        image_dir=args.images,
        annotations_path=args.annotations,
        quick_mode=args.quick,
        detector_model=args.detector
    )
