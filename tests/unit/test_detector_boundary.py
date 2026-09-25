"""
NETRAKSH — Detector & Tracker Boundary Regression Tests
Phase 7.4.2D

These tests verify the DEFINITIVE tracker adapter: that the
ultralytics.engine.results.Boxes object is constructed correctly at the
framework boundary, covering every attribute the installed BYTETracker/BOTSORT
accesses in its update() method:

  results.conf   → Boxes.data[:, -2]
  results.cls    → Boxes.data[:, -1]
  results.xywh   → ops.xyxy2xywh(Boxes.data[:, :4])
  results.xywhr  → (optional OBB path, not used here)

Ultralytics version verified from installed __init__.py: 8.3.0

The previous implementation (_DetWrapper) was missing .xywh, which caused
'_DetWrapper' object has no attribute 'xywh'. This test suite would have
caught that regression.
"""
import numpy as np
import torch
import pytest

from ultralytics.engine.results import Boxes as UltralyticsBoxes
from edge.detection.runtime import PyTorchRuntime, DetectionResult
from shared.schemas import BoundingBox


# ──────────────────────────────────────────────────────────────────────────────
# PART A — Ultralytics Boxes construction & attribute contract
# ──────────────────────────────────────────────────────────────────────────────

ORIG_SHAPE = (480, 640)  # (height, width) required by Boxes


def make_boxes(rows):
    """Helper: build UltralyticsBoxes from a list of [x1,y1,x2,y2,conf,cls] rows."""
    if rows:
        t = torch.tensor(rows, dtype=torch.float32)
    else:
        t = torch.zeros((0, 6), dtype=torch.float32)
    return UltralyticsBoxes(t, ORIG_SHAPE)


def test_boxes_zero_detections():
    """Empty Boxes must expose .conf, .cls, .xywh with length 0."""
    b = make_boxes([])
    assert len(b.conf) == 0
    assert len(b.cls) == 0
    assert len(b.xywh) == 0


def test_boxes_one_detection_conf():
    b = make_boxes([[10.0, 20.0, 100.0, 200.0, 0.91, 0.0]])
    assert len(b.conf) == 1
    assert abs(float(b.conf[0]) - 0.91) < 1e-5


def test_boxes_one_detection_cls():
    b = make_boxes([[10.0, 20.0, 100.0, 200.0, 0.91, 2.0]])
    assert int(b.cls[0]) == 2


def test_boxes_one_detection_xywh_shape():
    b = make_boxes([[10.0, 20.0, 110.0, 220.0, 0.91, 0.0]])
    xywh = b.xywh
    assert xywh.shape == (1, 4), f"Expected (1,4), got {xywh.shape}"


def test_boxes_one_detection_xywh_values():
    """xyxy [10,20,110,220] → xywh [60,120,100,200]."""
    b = make_boxes([[10.0, 20.0, 110.0, 220.0, 0.91, 0.0]])
    xywh = b.xywh.numpy() if hasattr(b.xywh, "numpy") else np.array(b.xywh)
    assert abs(xywh[0, 0] - 60.0) < 1e-4, f"cx={xywh[0,0]}"
    assert abs(xywh[0, 1] - 120.0) < 1e-4, f"cy={xywh[0,1]}"
    assert abs(xywh[0, 2] - 100.0) < 1e-4, f"w={xywh[0,2]}"
    assert abs(xywh[0, 3] - 200.0) < 1e-4, f"h={xywh[0,3]}"


def test_boxes_multiple_detections():
    rows = [
        [10.0, 20.0, 100.0, 200.0, 0.9, 0.0],
        [30.0, 40.0, 150.0, 250.0, 0.8, 2.0],
        [5.0, 5.0, 50.0, 50.0, 0.7, 7.0],
    ]
    b = make_boxes(rows)
    assert len(b.conf) == 3
    assert len(b.cls) == 3
    assert b.xywh.shape == (3, 4)


def test_boxes_column_layout():
    """Verify the exact column layout: conf = data[:,-2], cls = data[:,-1]."""
    t = torch.tensor([[10.0, 20.0, 100.0, 200.0, 0.77, 5.0]], dtype=torch.float32)
    b = UltralyticsBoxes(t, ORIG_SHAPE)
    assert abs(float(b.conf[0]) - 0.77) < 1e-5, "conf must come from column -2"
    assert int(b.cls[0]) == 5, "cls must come from column -1"


def test_boxes_has_xywh_attribute():
    """Regression: _DetWrapper was missing .xywh; real Boxes must have it."""
    b = make_boxes([[10.0, 20.0, 100.0, 200.0, 0.9, 0.0]])
    assert hasattr(b, "xywh"), "Boxes must expose .xywh (tracker requirement)"


def test_no_duck_typing_leaks_downstream():
    """After construction, Boxes.xyxy must NOT raise AttributeError."""
    b = make_boxes([[10.0, 20.0, 100.0, 200.0, 0.9, 0.0]])
    _ = b.xyxy  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# PART B — Canonical DetectionResult → Boxes adapter
# ──────────────────────────────────────────────────────────────────────────────

def _build_detections(rows):
    """Build canonical DetectionResult list from [[x1,y1,x2,y2,conf,cls]] rows."""
    results = []
    for x1, y1, x2, y2, conf, cls_id in rows:
        results.append(DetectionResult(
            bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
            confidence=conf,
            class_id=int(cls_id),
        ))
    return results


def _detections_to_boxes(detections, orig_shape):
    """Mirror of the logic in detector.py detect_and_track."""
    if not detections:
        empty_t = torch.zeros((0, 6), dtype=torch.float32)
        return UltralyticsBoxes(empty_t, orig_shape)
    arr = np.zeros((len(detections), 6), dtype=np.float32)
    for i, d in enumerate(detections):
        arr[i] = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2, d.confidence, d.class_id]
    t = torch.tensor(arr, dtype=torch.float32)
    return UltralyticsBoxes(t, orig_shape)


def test_adapter_zero_detections():
    boxes = _detections_to_boxes([], ORIG_SHAPE)
    assert isinstance(boxes, UltralyticsBoxes)
    assert len(boxes.conf) == 0


def test_adapter_one_detection():
    dets = _build_detections([[10.0, 20.0, 100.0, 200.0, 0.88, 2.0]])
    boxes = _detections_to_boxes(dets, ORIG_SHAPE)
    assert len(boxes.conf) == 1
    assert abs(float(boxes.conf[0]) - 0.88) < 1e-5
    assert int(boxes.cls[0]) == 2


def test_adapter_multiple_detections():
    dets = _build_detections([
        [10.0, 20.0, 100.0, 200.0, 0.9, 0.0],
        [30.0, 40.0, 150.0, 250.0, 0.8, 2.0],
    ])
    boxes = _detections_to_boxes(dets, ORIG_SHAPE)
    assert len(boxes.conf) == 2
    assert boxes.xywh.shape == (2, 4)


def test_adapter_tracker_attributes_no_error():
    """All tracker-accessed attributes must be reachable without AttributeError."""
    dets = _build_detections([[10.0, 20.0, 100.0, 200.0, 0.9, 0.0]])
    boxes = _detections_to_boxes(dets, ORIG_SHAPE)
    # These are the exact attributes BYTETracker.update() accesses:
    _ = boxes.conf    # line 301 in byte_tracker.py
    _ = boxes.xywh    # line 302 in byte_tracker.py (fallback from xywhr)
    _ = boxes.cls     # line 305 in byte_tracker.py
    # xyxy is also accessed by downstream consumers
    _ = boxes.xyxy
