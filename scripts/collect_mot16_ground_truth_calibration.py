#!/usr/bin/env python
"""
NETRAKSH — Real false-positive calibration data from MOT16 ground truth.

Every calibration attempt this project has made so far (scripts/collect_
calibration_data.py + scripts/fit_reliability_weights.py +
scripts/fit_detection_thresholds.py) hit the SAME real, honest wall: this
project's only real footage (demo/videos/vtest.avi) contains zero real
false positives once a human reviews the snapshots — every raw candidate
is a genuine detection. A binary classifier (or CalibrationModule.fit())
needs real negative examples to have anything to learn a decision boundary
against, and this project never had any.

MOT16 (Milan et al., "MOT16: A Benchmark for Multi-Object Tracking",
arXiv:1603.00831; https://motchallenge.net — CC BY-NC-SA 3.0, non-commercial
research use, which this SIH hackathon prototype is) is different: it ships
real, human-annotated ground-truth pedestrian boxes (gt/gt.txt) for real
CCTV/street footage. That means, for the first time in this project, "is
this raw YOLO detection a real person" can be checked against an
independent, authoritative real answer instead of a human reviewing a
snapshot — and, critically, a raw YOLO box that does NOT match any real
ground-truth box is a REAL, VERIFIABLE false positive, not a guess.

Method, stated plainly:
1. For each sampled frame in a real MOT16 sequence, run the real detector
   (edge/detection/detector.py's YOLOv8n, same model this whole project
   uses) at a low confidence floor (0.05) so BOTH strong and weak raw
   candidates are captured — the calibration question is precisely "which
   of these should the confidence threshold reject".
2. For each raw candidate box, compute IoU against every real ground-truth
   box in that frame (class 1 = "Pedestrian" in the MOT16 devkit; other GT
   classes — static person, distractor, occluder, reflection, etc. — are
   real too but are NOT what this project's detector is trying to find, so
   they're excluded rather than silently counted as either a match or a
   miss).
3. max_iou >= MATCH_IOU_THRESHOLD -> label=1 (real, GT-confirmed detection).
   max_iou <  FP_IOU_THRESHOLD   -> label=0 (real, GT-confirmed false
   positive: no real pedestrian anywhere near this box).
   Anything in between is genuinely ambiguous (partial/edge overlap) and is
   excluded from the manifest entirely — never forced into either label.
4. The real SceneConditionClassifier (edge/condition/scene_condition.py)
   classifies each frame for real, same as every other calibration script
   this project has — MOT16 sequences are real footage from real cameras,
   not synthetically degraded, so whatever condition they classify as is
   real.

Output feeds scripts/fit_detection_thresholds_mot16.py, which is the first
attempt all session with a real chance at a non-degenerate two-class fit.

Usage:
    python scripts/collect_mot16_ground_truth_calibration.py \\
        --sequence-dir /path/to/MOT16/train/MOT16-04 \\
        --out-dir scripts/calibration_data_mot16_04 \\
        --frame-stride 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np

from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.detector import DetectionTracker

# Real ultralytics/COCO class 0 = person. Low floor so weak raw candidates
# (the ones a real threshold would need to reject) are captured too.
RAW_CONFIDENCE_FLOOR = 0.05

# MOT16 devkit ground-truth class codes (gt.txt column 8) — class 1 is the
# only one meaning "a real, moving pedestrian", which is what this
# project's detector is actually trying to find. Others (2=person on
# vehicle, 3=car, 4=bicycle, 5=motorbike, 6=non-mot vehicle, 7=static
# person, 8=distractor, 9=occluder, 10=occluder on ground, 11=occluder full,
# 12=reflection) are real GT too, just not the target class here — boxes
# near them are excluded (see module docstring point 3), not mislabeled.
GT_PEDESTRIAN_CLASS = 1

MATCH_IOU_THRESHOLD = 0.5   # >= this real IoU with a real GT box -> label=1
FP_IOU_THRESHOLD = 0.1      # <  this real IoU with EVERY real GT box -> label=0


def _iou(box_a, box_b) -> float:
    """Real, standard IoU between two (x1,y1,x2,y2) boxes."""
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _load_ground_truth(gt_path: Path) -> dict:
    """Real MOT16 gt.txt -> {frame_idx: [(x1,y1,x2,y2), ...]} for
    GT_PEDESTRIAN_CLASS boxes only."""
    by_frame: dict = {}
    with open(gt_path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 8:
                continue
            frame_idx = int(parts[0])
            bb_left, bb_top, bb_w, bb_h = (float(parts[2]), float(parts[3]), float(parts[4]), float(parts[5]))
            conf_flag = float(parts[6])
            cls = int(float(parts[7]))
            if conf_flag == 0:
                continue  # devkit convention: 0 means "ignore this box"
            if cls != GT_PEDESTRIAN_CLASS:
                continue
            box = (bb_left, bb_top, bb_left + bb_w, bb_top + bb_h)
            by_frame.setdefault(frame_idx, []).append(box)
    return by_frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Real FP/TP calibration data from MOT16 ground truth")
    parser.add_argument("--sequence-dir", required=True, help="Path to a MOT16-XX sequence directory (contains img1/ and gt/gt.txt)")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--frame-stride", type=int, default=5, help="Process every Nth frame (full sequences are thousands of frames)")
    parser.add_argument("--max-frames", type=int, default=None, help="Optional cap on frames processed")
    parser.add_argument("--save-snapshot-sample", type=int, default=25, help="Save annotated snapshots for only the first N candidates (spot-check, not needed for labeling — labels come from real GT)")
    args = parser.parse_args()

    seq_dir = Path(args.sequence_dir)
    img_dir = seq_dir / "img1"
    gt_path = seq_dir / "gt" / "gt.txt"
    if not img_dir.exists() or not gt_path.exists():
        raise SystemExit(f"Expected {img_dir} and {gt_path} to exist — is --sequence-dir a real MOT16-XX folder?")

    out_dir = Path(args.out_dir)
    snapshots_dir = out_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    gt_by_frame = _load_ground_truth(gt_path)
    print(f"Loaded real ground truth: {sum(len(v) for v in gt_by_frame.values())} pedestrian boxes across {len(gt_by_frame)} frames")

    condition_classifier = SceneConditionClassifier(camera_id="mot16-benchmark")
    detector = DetectionTracker(model_size="yolov8n.pt", device="cpu")
    detector.load()

    frame_files = sorted(img_dir.glob("*.jpg"))
    if args.max_frames:
        frame_files = frame_files[: args.max_frames]

    candidates = []
    condition_counts: dict = {}
    t_start = time.perf_counter()

    for i, frame_path in enumerate(frame_files):
        if i % args.frame_stride != 0:
            continue
        frame_idx = int(frame_path.stem)  # MOT16 img1 filenames are zero-padded frame numbers
        frame = cv2.imread(str(frame_path))
        if frame is None:
            continue

        condition = condition_classifier.classify(frame)
        condition_counts[str(condition.condition)] = condition_counts.get(str(condition.condition), 0) + 1

        # Raw candidates at a low confidence floor — NOT detect_and_track()'s
        # already-thresholded/tracked output, since the whole point here is
        # to see which raw candidates a real threshold should accept/reject.
        try:
            results = detector._model.predict(frame, conf=RAW_CONFIDENCE_FLOOR, verbose=False, classes=[0], device="cpu")
        except Exception as exc:
            print(f"[frame {frame_idx}] detector error: {exc}", file=sys.stderr)
            continue

        gt_boxes = gt_by_frame.get(frame_idx, [])
        if not results or results[0].boxes is None:
            continue

        boxes = results[0].boxes
        for j in range(len(boxes)):
            conf = float(boxes.conf[j].item())
            xyxy = tuple(boxes.xyxy[j].tolist())

            max_iou = max((_iou(xyxy, gt_box) for gt_box in gt_boxes), default=0.0)
            if max_iou >= MATCH_IOU_THRESHOLD:
                label = 1
            elif max_iou < FP_IOU_THRESHOLD:
                label = 0
            else:
                continue  # genuinely ambiguous — excluded, never guessed (see module docstring)

            candidate_id = f"candidate_{len(candidates):04d}"
            entry = {
                "candidate_id": candidate_id,
                "sequence": seq_dir.name,
                "frame_idx": frame_idx,
                "D": round(conf, 4),
                "bbox": [round(v, 1) for v in xyxy],
                "max_iou_with_real_gt": round(max_iou, 4),
                "label": label,
                "scene_condition": str(condition.condition),
                "brightness_mean": round(condition.brightness_mean, 2),
                "contrast_std": round(condition.contrast_std, 2),
            }

            if len(candidates) < args.save_snapshot_sample:
                snapshot = frame.copy()
                x1, y1, x2, y2 = (int(v) for v in xyxy)
                color = (0, 255, 0) if label == 1 else (0, 0, 255)
                cv2.rectangle(snapshot, (x1, y1), (x2, y2), color, 2)
                for gx1, gy1, gx2, gy2 in gt_boxes:
                    cv2.rectangle(snapshot, (int(gx1), int(gy1)), (int(gx2), int(gy2)), (255, 200, 0), 1)
                snapshot_path = snapshots_dir / f"{candidate_id}.jpg"
                cv2.imwrite(str(snapshot_path), snapshot)
                entry["snapshot"] = str(snapshot_path.relative_to(out_dir))

            candidates.append(entry)

        if i % 200 == 0:
            print(f"  ...frame {frame_idx} ({len(candidates)} candidates so far)")

    wall_seconds = time.perf_counter() - t_start
    n_pos = sum(1 for c in candidates if c["label"] == 1)
    n_neg = sum(1 for c in candidates if c["label"] == 0)

    manifest = {
        "source": "MOT16 (Milan et al., arXiv:1603.00831, https://motchallenge.net) — CC BY-NC-SA 3.0, non-commercial research use",
        "sequence": seq_dir.name,
        "frame_stride": args.frame_stride,
        "raw_confidence_floor": RAW_CONFIDENCE_FLOOR,
        "match_iou_threshold": MATCH_IOU_THRESHOLD,
        "fp_iou_threshold": FP_IOU_THRESHOLD,
        "labeling_method": (
            "Real ground truth (gt/gt.txt, MOT16 devkit), NOT manual review — a candidate is "
            "label=1 if its IoU with some real GT pedestrian box is >= match_iou_threshold, "
            "label=0 if its IoU with EVERY real GT box is < fp_iou_threshold. Anything between "
            "the two thresholds is genuinely ambiguous and excluded from this manifest, never "
            "guessed either way."
        ),
        "condition_distribution": condition_counts,
        "wall_seconds": round(wall_seconds, 2),
        "frames_processed": len(frame_files[:: args.frame_stride]) if args.frame_stride else 0,
        "candidates": candidates,
        "label_distribution": {"1_real_detection": n_pos, "0_real_false_positive": n_neg},
    }

    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{len(candidates)} real candidates ({n_pos} real detections, {n_neg} real false positives)")
    print(f"Manifest: {manifest_path}")
    if n_neg == 0:
        print("\nNo real false positives found in this sample — same honest 'nothing to calibrate against'")
        print("outcome as every prior attempt, for this sequence/stride. Try a denser stride or a")
        print("busier sequence before concluding MOT16 can't supply real negatives either.")
    else:
        print(f"\n{n_neg} real, GT-verified false positives found — run scripts/fit_detection_thresholds_mot16.py")
        print("to see whether CalibrationModule can now fit a real, non-degenerate threshold.")


if __name__ == "__main__":
    main()
