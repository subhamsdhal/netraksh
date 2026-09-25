#!/usr/bin/env python3
"""
NETRAKSH Edge — Multi-Stream Admission Control & Resource Benchmark (WP-4.4)
"""
import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import psutil

# Adjust path so edge package is visible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from edge.health.resource import EdgeResourceGovernor, ResourceState
from edge.health.admission import StreamAdmissionController, StreamPriority, AdmissionDecision

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def simulate_camera_stream(stream_id: str, video_path: str, bench_frames: int):
    """Simulates a camera ingestion worker reading frames and recording latency."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"[{stream_id}] Cannot open video {video_path}")
        return {"id": stream_id, "frames": 0, "elapsed": 0.0}

    frames_processed = 0
    t_start = time.perf_counter()
    
    while frames_processed < bench_frames:
        ret, frame = cap.read()
        if not ret:
            # Loop video
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue
        
        # Simulate slight processing latency (e.g. inference time + tracker)
        time.sleep(0.015) 
        frames_processed += 1

    t_end = time.perf_counter()
    cap.release()
    
    elapsed = t_end - t_start
    logger.info(f"[{stream_id}] Completed {frames_processed} frames in {elapsed:.2f}s ({(frames_processed/elapsed):.1f} FPS)")
    
    return {"id": stream_id, "frames": frames_processed, "elapsed": elapsed}


def run_benchmark(num_streams: int, video_path: str, frames_per_stream: int):
    logger.info(f"=== Multi-Stream Benchmark: {num_streams} Streams ===")
    
    # Initialize Resource Governance
    governor = EdgeResourceGovernor()
    admission_controller = StreamAdmissionController(governor)
    
    active_streams = []
    
    logger.info("--- Admission Phase ---")
    for i in range(num_streams):
        stream_id = f"camera_{i}"
        decision = admission_controller.request_admission(stream_id, StreamPriority.NORMAL, len(active_streams))
        
        if decision in (AdmissionDecision.ACCEPT, AdmissionDecision.ACCEPT_DEGRADED):
            active_streams.append(stream_id)
            logger.info(f"Stream {stream_id} ADMITTED ({decision.value}).")
        else:
            logger.warning(f"Stream {stream_id} REJECTED.")
            
        # Simulate resource pressure building up
        if len(active_streams) >= governor.max_cpu_percent * 0.1: # Mocking pressure based on count
            pass # In reality, the governor would read psutil continuously
            
    logger.info(f"Total streams admitted: {len(active_streams)} / {num_streams}")
    
    if len(active_streams) == 0:
        logger.warning("No streams admitted. Exiting benchmark.")
        return

    logger.info("--- Execution Phase ---")
    t0 = time.perf_counter()
    
    results = []
    with ThreadPoolExecutor(max_workers=len(active_streams)) as executor:
        futures = [executor.submit(simulate_camera_stream, sid, video_path, frames_per_stream) for sid in active_streams]
        for f in futures:
            results.append(f.result())
            
    t1 = time.perf_counter()
    total_time = t1 - t0
    
    total_frames = sum(r["frames"] for r in results)
    aggregate_fps = total_frames / total_time if total_time > 0 else 0
    
    # Capture final resource state
    final_state = governor.evaluate(len(active_streams), 10, 15.0)
    telemetry = governor.get_telemetry()
    
    logger.info("--- Results ---")
    logger.info(f"Aggregate FPS: {aggregate_fps:.1f}")
    logger.info(f"Final Resource State: {final_state.value}")
    logger.info(f"CPU Usage: {telemetry['cpu_percent']}%")
    logger.info(f"RSS RAM: {telemetry['memory_mb']:.1f} MB")
    logger.info("=======================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--streams", type=int, default=1, help="Number of concurrent streams to request")
    parser.add_argument("--video", type=str, default="test.mp4", help="Video file to stream")
    parser.add_argument("--frames", type=int, default=100, help="Frames per stream")
    
    args = parser.parse_args()
    run_benchmark(args.streams, args.video, args.frames)
