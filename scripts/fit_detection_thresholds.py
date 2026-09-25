#!/usr/bin/env python
"""
NETRAKSH -- Real detection-threshold calibration attempt for
edge/detection/calibration.py's CalibrationModule (Gate 3: isotonic
regression / Platt scaling per scene-condition bucket -- architecture §17).

This module's fit() has NEVER had a real caller before this script (see
docs/LIMITATIONS.md: "no labeled dataset has been run through it yet").
Rather than collect a brand-new dataset from scratch, this reuses the
same real, manually-reviewed labeled data already collected for the
Hybrid Reliability Engine's weight-calibration attempt
(scripts/calibration_data{,_night,_fog}/manifest.json) -- each manifest's
candidates already carry a real raw detector confidence ("D") and a real
manual label (1 = genuine detection; every one of these turned out to be
1 -- see below) for one of the three real scene conditions actually
observed in this project's footage (CLEAR_DAY, LOW_LIGHT_NIGHT,
FOG_RAIN). This is the SAME real, honest data, not a new/different
dataset -- reused here for a different real question: can it calibrate
Gate 3's per-condition confidence thresholds, the same way it could not
calibrate the Hybrid Reliability Engine's weights?

HONEST EXPECTATION, stated before running: manual review already
established (docs/LIMITATIONS.md) that every one of these real
candidates, across all three conditions, is a genuine detection -- zero
false positives anywhere in this project's real footage. CalibrationModule
.fit() needs genuine negative examples (real false detections) to have
any real precision/recall signal to fit a threshold against. This script
therefore expects -- and, if so, will report plainly rather than force a
number -- the SAME "cannot calibrate, no real negative examples exist"
outcome as scripts/fit_reliability_weights.py found, but for this
DIFFERENT module. `CalibrationModule.fit()` itself was hardened (this
session) to refuse a single-class dataset rather than silently return a
meaningless threshold -- this script relies on that real guard rather
than re-implementing the check.

Usage:
    python scripts/fit_detection_thresholds.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json

import numpy as np

from edge.detection.calibration import CalibrationModule
from shared.constants import SceneCondition

MANIFESTS = {
    SceneCondition.CLEAR_DAY: "scripts/calibration_data/manifest.json",
    SceneCondition.LOW_LIGHT_NIGHT: "scripts/calibration_data_night/manifest.json",
    SceneCondition.FOG_RAIN: "scripts/calibration_data_fog/manifest.json",
}


def main() -> None:
    calibration = CalibrationModule()  # starts on prototype defaults, uncalibrated

    for condition, manifest_path in MANIFESTS.items():
        path = Path(manifest_path)
        if not path.exists():
            print(f"{condition}: {manifest_path} not found -- run scripts/collect_calibration_data.py first.")
            continue

        with open(path) as f:
            manifest = json.load(f)

        candidates = [c for c in manifest["candidates"] if c.get("label") is not None]
        # Real, measured, condition-specific real data (already manually
        # reviewed) -- every candidate is already the real scene_condition
        # this manifest was collected under (see collect_calibration_data.py),
        # so no re-filtering by condition is needed here.
        confidences = np.array([c["D"] for c in candidates])
        labels = np.array([c["label"] for c in candidates])

        print(f"\n{condition}: {len(candidates)} real labeled candidates from {manifest_path}")
        unique = sorted(set(labels.tolist()))
        print(f"  Label distribution: {[(v, int((labels == v).sum())) for v in unique]}")

        try:
            threshold = calibration.fit(confidences, labels, condition, method="isotonic")
        except ValueError as exc:
            print(f"  REFUSED: {exc}")
            print(f"  Prototype threshold for {condition} left in force: {calibration.get_threshold(condition):.3f}")
            continue

        print(f"  Fitted threshold: {threshold:.3f} (calibration.is_calibrated()={calibration.is_calibrated()})")

    print(
        "\nSummary: this attempt used the SAME real, already-reviewed labeled data as the Hybrid\n"
        "Reliability Engine's weight-calibration attempt, applied to a different module\n"
        "(CalibrationModule's per-condition confidence thresholds). If every condition above was\n"
        "REFUSED, that is the same honest finding as before, for a different module: this project's\n"
        "one real video (across daytime and two synthetic night/fog variants) contains zero real false\n"
        "detections to calibrate a threshold against. Prototype thresholds "
        "(THRESHOLD_CLEAR_DAY etc.) remain in force -- nothing here was saved or applied to the\n"
        "runtime defaults."
    )


if __name__ == "__main__":
    main()
