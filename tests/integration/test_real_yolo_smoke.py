"""Opt-in smoke test for the packaged YOLO model and demo video.

This is intentionally excluded from ordinary fast unit runs. Set
``RUN_REAL_CV_SMOKE=1`` to execute CPU model loading, warm-up, video decode,
and inference against repository artifacts.
"""
from __future__ import annotations

import os
from pathlib import Path

import cv2
import pytest

from edge.detection.runtime import PyTorchRuntime


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_CV_SMOKE") != "1",
    reason="set RUN_REAL_CV_SMOKE=1 to execute packaged model inference",
)
def test_packaged_yolo_detects_supported_objects_in_demo_video() -> None:
    root = Path(__file__).resolve().parents[2]
    model_path = root / "yolov8n.pt"
    video_path = root / "demo" / "videos" / "vtest.avi"
    assert model_path.is_file(), f"missing model artifact: {model_path}"
    assert video_path.is_file(), f"missing demo video: {video_path}"

    runtime = PyTorchRuntime(str(model_path))
    runtime.load()

    capture = cv2.VideoCapture(str(video_path))
    assert capture.isOpened(), f"could not decode demo video: {video_path}"
    detections = []
    sampled_frames = 0
    try:
        frame_index = 0
        while sampled_frames < 8:
            ok, frame = capture.read()
            assert ok, "demo video ended before the smoke sample completed"
            if frame_index % 12 == 0:
                sampled_frames += 1
                detections.extend(runtime.detect(frame, confidence_threshold=0.25))
                if detections:
                    break
            frame_index += 1
    finally:
        capture.release()

    assert detections, "real YOLO inference produced no supported object detections"
    assert all(d.class_id in {0, 2, 3, 5, 7} for d in detections)
    assert all(d.class_id != 1 for d in detections), "COCO bicycle must never map to PERSON"
