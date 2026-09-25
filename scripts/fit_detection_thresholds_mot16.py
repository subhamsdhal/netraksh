#!/usr/bin/env python
"""
NETRAKSH — Attempt a real CalibrationModule fit using MOT16 ground-truth data.

scripts/fit_detection_thresholds.py already tried this against this
project's own footage and was correctly REFUSED for all three real
conditions, because that footage has zero real false positives once
reviewed. scripts/collect_mot16_ground_truth_calibration.py produces a
different kind of manifest — real, GT-verified positives AND real,
GT-verified negatives — so this is the first attempt all session with an
actual chance at a non-degenerate two-class fit.

This does NOT overwrite this project's own THRESHOLD_* runtime defaults
automatically. A fit here, if one succeeds, is a real result worth
reporting honestly — but MOT16 is a different camera, a different city, a
different crowd density than this project's own footage, and applying a
threshold fitted on one dataset to a different camera's runtime defaults
is a real methodological question, not a mechanical one-liner. That
decision is left explicit and separate, same as
scripts/fit_reliability_weights.py's stance on its own (never-fitted)
weights.

Usage:
    python scripts/fit_detection_thresholds_mot16.py \\
        --manifest scripts/calibration_data_mot16_04/manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

from edge.detection.calibration import CalibrationModule
from shared.constants import SceneCondition


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit CalibrationModule thresholds from real MOT16 ground truth")
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    with open(args.manifest) as f:
        manifest = json.load(f)

    candidates = manifest["candidates"]
    print(f"Loaded {len(candidates)} real candidates from {args.manifest}")
    print(f"Source: {manifest.get('source', 'unknown')}")
    print(f"Label distribution: {manifest.get('label_distribution')}")

    if not candidates:
        raise SystemExit("No candidates in manifest — nothing to fit.")

    # Group by the real scene_condition each frame was actually classified
    # under (edge/condition/scene_condition.py ran for real on every frame
    # in the collection script — this isn't asserted, it's what was measured).
    by_condition: dict = {}
    for c in candidates:
        by_condition.setdefault(c["scene_condition"], []).append(c)

    calibration = CalibrationModule()
    any_success = False

    for condition_str, group in by_condition.items():
        try:
            condition = SceneCondition(condition_str)
        except ValueError:
            print(f"\n{condition_str}: not a real SceneCondition value — skipping")
            continue

        confidences = np.array([c["D"] for c in group])
        labels = np.array([c["label"] for c in group])
        unique = sorted(set(labels.tolist()))
        print(f"\n{condition}: {len(group)} real candidates, label distribution {[(v, int((labels == v).sum())) for v in unique]}")

        try:
            threshold = calibration.fit(confidences, labels, condition, method="isotonic")
        except ValueError as exc:
            print(f"  REFUSED: {exc}")
            print(f"  Prototype threshold for {condition} left in force: {calibration.get_threshold(condition):.3f}")
            continue

        any_success = True
        print(f"  FITTED (real, non-degenerate): threshold={threshold:.3f} (calibration.is_calibrated()={calibration.is_calibrated()})")

    print("\n" + "=" * 72)
    if any_success:
        print(
            "At least one condition produced a real, non-degenerate fit from real MOT16 ground\n"
            "truth — the first time this whole project has had real negative examples to calibrate\n"
            "against. This is NOT automatically applied to edge/detection/calibration.py's runtime\n"
            "THRESHOLD_* defaults: MOT16 is a different camera/city/crowd density than this\n"
            "project's own footage, and deciding whether (and how) to transfer a threshold fitted\n"
            "on one dataset to another camera's defaults is a real, explicit decision — not made\n"
            "here. See docs/LIMITATIONS.md for the full honest account."
        )
    else:
        print(
            "Every condition was REFUSED — even MOT16's real ground truth didn't produce a\n"
            "two-class split for any condition present in this sample (see label_distribution\n"
            "above). Try a denser --frame-stride or a different/busier MOT16 sequence when\n"
            "re-running scripts/collect_mot16_ground_truth_calibration.py before concluding no\n"
            "real dataset can supply this project with real negative examples."
        )
    print("=" * 72)


if __name__ == "__main__":
    main()
