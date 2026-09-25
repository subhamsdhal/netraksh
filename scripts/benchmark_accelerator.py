#!/usr/bin/env python3
"""
NETRAKSH Edge — Hardware Acceleration Benchmark (WP-4.3)
Benchmarks PyTorch vs ONNX (CPU/CUDA) vs TensorRT.
"""
import argparse
import logging
import os
import time
import sys
import psutil

import cv2
import numpy as np

# Adjust path so edge package is visible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge.detection.runtime import (
    create_runtime, 
    PyTorchRuntime,
    ONNXRuntimeCPU,
    ONNXRuntimeCUDA,
    TensorRTRuntime
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def export_onnx(model_path: str, output_path: str):
    logger.info(f"Exporting {model_path} to ONNX at {output_path}...")
    try:
        from ultralytics import YOLO
        model = YOLO(model_path)
        path = model.export(format="onnx", opset=12, simplify=True, dynamic=False, imgsz=640)
        logger.info(f"Export complete. File saved to: {path}")
    except Exception as exc:
        logger.error(f"Export failed: {exc}")
        sys.exit(1)


def discover_hardware():
    import torch
    import onnxruntime as ort
    logger.info("=== Hardware Discovery ===")
    logger.info(f"CPU count: {os.cpu_count()}")
    logger.info(f"Total RAM: {psutil.virtual_memory().total / (1024**3):.1f} GB")
    
    cuda_avail = False
    try:
        cuda_avail = torch.cuda.is_available()
        logger.info(f"PyTorch CUDA available: {cuda_avail}")
        if cuda_avail:
            logger.info(f"GPU Name: {torch.cuda.get_device_name(0)}")
    except ImportError:
        logger.info("PyTorch not installed.")
        
    try:
        providers = ort.get_available_providers()
        logger.info(f"ONNX Runtime Providers: {providers}")
    except ImportError:
        logger.info("ONNX Runtime not installed.")
        
    logger.info("==========================\n")


def compare_equivalence(pytorch_model: str, onnx_model: str, video_path: str):
    logger.info("=== Numerical Equivalence Check ===")
    
    os.environ["DETECTOR_RUNTIME"] = "pytorch"
    os.environ["DETECTOR_MODEL"] = pytorch_model
    pt_rt = PyTorchRuntime(pytorch_model)
    
    os.environ["DETECTOR_RUNTIME"] = "onnx_cpu"
    os.environ["DETECTOR_MODEL_ONNX"] = onnx_model
    onnx_rt = ONNXRuntimeCPU(onnx_model)
    
    try:
        pt_rt.load()
        onnx_rt.load()
    except Exception as exc:
        logger.error(f"Failed to load runtimes for equivalence check: {exc}")
        return

    cap = cv2.VideoCapture(video_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        logger.error("Could not read frame from video.")
        return

    pt_dets = pt_rt.detect(frame, confidence_threshold=0.3)
    onnx_dets = onnx_rt.detect(frame, confidence_threshold=0.3)
    
    logger.info(f"PyTorch detections: {len(pt_dets)}")
    logger.info(f"ONNX CPU detections: {len(onnx_dets)}")
    
    for i, p in enumerate(pt_dets):
        logger.info(f"PT[{i}] cls: {p.class_id}, conf: {p.confidence:.3f}, bbox: {p.bbox}")
    for i, o in enumerate(onnx_dets):
        logger.info(f"ONNX[{i}] cls: {o.class_id}, conf: {o.confidence:.3f}, bbox: {o.bbox}")

    logger.info("Equivalence check complete. Review logs for numeric tolerance (acceptable < 1% diff).")
    logger.info("===================================\n")


def run_benchmark(runtime_name: str, model_path: str, video_path: str, warmup_frames: int = 10, bench_frames: int = 100):
    logger.info(f"=== Benchmarking Runtime: {runtime_name} ===")
    os.environ["DETECTOR_RUNTIME"] = runtime_name
    if runtime_name == "pytorch":
        os.environ["DETECTOR_MODEL"] = model_path
    else:
        os.environ["DETECTOR_MODEL_ONNX"] = model_path

    t0 = time.perf_counter()
    try:
        runtime = create_runtime()
        runtime.load()
    except Exception as exc:
        logger.error(f"Failed to load runtime {runtime_name}: {exc}")
        return
    t1 = time.perf_counter()
    load_time_ms = (t1 - t0) * 1000
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Cannot open video {video_path}")
        return
    
    frames = []
    while len(frames) < warmup_frames + bench_frames:
        ret, frame = cap.read()
        if not ret:
            break
        frames.append(frame)
    cap.release()
    
    if len(frames) == 0:
        logger.error("No frames to process.")
        return

    logger.info(f"Model Load Time: {load_time_ms:.1f} ms")
    logger.info(f"Starting warmup ({warmup_frames} frames)...")
    
    for i in range(min(warmup_frames, len(frames))):
        runtime.detect(frames[i], confidence_threshold=0.3)
        
    logger.info(f"Starting steady state benchmark ({bench_frames} frames)...")
    t_bench_start = time.perf_counter()
    
    start_idx = warmup_frames
    end_idx = min(warmup_frames + bench_frames, len(frames))
    for i in range(start_idx, end_idx):
        runtime.detect(frames[i], confidence_threshold=0.3)
        
    t_bench_end = time.perf_counter()
    total_time_s = t_bench_end - t_bench_start
    frames_processed = end_idx - start_idx
    
    fps = frames_processed / total_time_s if total_time_s > 0 else 0
    avg_e2e_ms = (total_time_s / frames_processed) * 1000 if frames_processed > 0 else 0
    
    process = psutil.Process()
    rss_mb = process.memory_info().rss / (1024 * 1024)
    cpu_percent = process.cpu_percent()
    
    logger.info(f"Results for {runtime_name}:")
    logger.info(f"  Avg E2E:   {avg_e2e_ms:.1f} ms")
    logger.info(f"  FPS:       {fps:.1f}")
    logger.info(f"  CPU Usage: {cpu_percent:.1f} %")
    logger.info(f"  RSS RAM:   {rss_mb:.1f} MB")
    logger.info("=============================================\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hardware", action="store_true", help="Discover hardware")
    parser.add_argument("--export-onnx", action="store_true", help="Export PyTorch model to ONNX")
    parser.add_argument("--model-pt", default="yolov8n.pt", help="Path to PyTorch model")
    parser.add_argument("--model-onnx", default="yolov8n.onnx", help="Path to ONNX model")
    parser.add_argument("--video", default="test.mp4", help="Path to benchmark video")
    parser.add_argument("--equivalence", action="store_true", help="Test PyTorch vs ONNX equivalence")
    parser.add_argument("--runtime", choices=["pytorch", "onnx_cpu", "onnx_cuda", "tensorrt"], help="Run benchmark for specific runtime")
    
    args = parser.parse_args()
    
    if args.hardware:
        discover_hardware()
        
    if args.export_onnx:
        export_onnx(args.model_pt, args.model_onnx)
        
    if args.equivalence:
        compare_equivalence(args.model_pt, args.model_onnx, args.video)
        
    if args.runtime:
        if args.runtime == "pytorch":
            run_benchmark(args.runtime, args.model_pt, args.video)
        else:
            run_benchmark(args.runtime, args.model_onnx, args.video)
