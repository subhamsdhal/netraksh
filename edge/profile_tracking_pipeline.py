"""Repeatable local/staging-equivalent detector and visual-tracker profiler."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time

import cv2
import psutil

from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.detector import DetectionTracker
from edge.health.camera_health import CameraHealthMonitor
from edge.tracking.hybrid_tracker import OpticalFlowBoxTracker
from shared.constants import StreamState


def _stats(values):
    if not values:
        return {"mean_ms": 0.0, "p95_ms": 0.0, "count": 0}
    ordered = sorted(values)
    return {
        "mean_ms": round(statistics.mean(values), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
        "count": len(values),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--input-size", type=int, default=640)
    parser.add_argument("--frames", type=int, default=96)
    args = parser.parse_args()
    os.environ["DETECTOR_RUNTIME"] = "onnx_cpu"
    os.environ["DETECTOR_MODEL_ONNX"] = os.environ.get("DETECTOR_MODEL_ONNX", "yolov8n.onnx")
    os.environ["DETECTOR_INPUT_SIZE"] = str(args.input_size)
    os.environ.setdefault("ORT_INTRA_OP_THREADS", "1")
    os.environ.setdefault("ORT_INTER_OP_THREADS", "1")
    cv2.setNumThreads(1)

    capture = cv2.VideoCapture(args.video)
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    detector = DetectionTracker()
    detector.load()
    health = CameraHealthMonitor("profile", fps_declared=source_fps)
    scene = SceneConditionClassifier("profile")
    flow = OpticalFlowBoxTracker(max_width=480)
    health_ms, scene_ms, serialize_ms, jpeg_ms, flow_ms = [], [], [], [], []
    detector_stage = {"preprocess": [], "inference": [], "postprocess_nms": [], "total": []}
    bytetrack_ms = []
    detector_tracks = []
    process = psutil.Process()
    process.cpu_percent(None)
    started_all = time.perf_counter()
    detector_stride = max(1, int(round(source_fps)))
    decode_ms = []
    frames_processed = 0
    condition = None
    for index in range(args.frames):
        started = time.perf_counter()
        ok, frame = capture.read()
        decode_ms.append((time.perf_counter() - started) * 1000.0)
        if not ok:
            break
        frames_processed += 1
        started = time.perf_counter()
        health.update(frame, time.time(), StreamState.CONNECTED)
        health_ms.append((time.perf_counter() - started) * 1000.0)
        # Production refreshes scene context only for detector keyframes.
        if condition is None or index % detector_stride == 0:
            started = time.perf_counter()
            condition = scene.classify(frame)
            scene_ms.append((time.perf_counter() - started) * 1000.0)
        started = time.perf_counter()
        flow.observe(frame, index)
        flow_ms.append((time.perf_counter() - started) * 1000.0)
        if index % detector_stride == 0:
            detector_tracks = detector.detect_and_track(frame, condition.condition, 0.25)
            for key, value in detector._runtime.last_stage_ms.items():
                detector_stage[key].append(value)
            bytetrack_ms.append(detector.last_tracker_ms)
            flow.reanchor(detector_tracks, index, frame)
        payload = {
            "frame_index": index,
            "video_time": index / source_fps,
            "tracks": [track.model_dump(mode="json") for track in flow.current_tracks()],
        }
        started = time.perf_counter()
        json.dumps(payload)
        serialize_ms.append((time.perf_counter() - started) * 1000.0)
        if index % detector_stride == 0:
            started = time.perf_counter()
            cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 68])
            jpeg_ms.append((time.perf_counter() - started) * 1000.0)
    capture.release()
    if frames_processed == 0:
        raise RuntimeError("No frames decoded")
    wall = time.perf_counter() - started_all
    report = {
        "input_size": args.input_size,
        "source_fps": source_fps,
        "frames": frames_processed,
        "decode": _stats(decode_ms),
        "health": _stats(health_ms),
        "scene": _stats(scene_ms),
        "preprocess": _stats(detector_stage["preprocess"]),
        "yolo_inference": _stats(detector_stage["inference"]),
        "postprocess_nms": _stats(detector_stage["postprocess_nms"]),
        "detector_total": _stats(detector_stage["total"]),
        "bytetrack": _stats(bytetrack_ms),
        "optical_flow": _stats(flow_ms),
        "telemetry_serialization": _stats(serialize_ms),
        "diagnostic_jpeg": _stats(jpeg_ms),
        "measured_loop_fps": round(frames_processed / wall, 3),
        "cpu_percent": process.cpu_percent(None),
        "rss_mb": round(process.memory_info().rss / (1024 * 1024), 2),
        "onnx_session_reused": True,
        "onnx_graph_optimization": "ORT_ENABLE_ALL",
        "onnx_intra_op_threads": int(os.environ["ORT_INTRA_OP_THREADS"]),
        "onnx_inter_op_threads": int(os.environ["ORT_INTER_OP_THREADS"]),
        "opencv_threads": cv2.getNumThreads(),
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
