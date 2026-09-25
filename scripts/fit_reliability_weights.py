#!/usr/bin/env python
"""
NETRAKSH -- Fit the Hybrid Reliability Engine's weights
(edge/reliability/decision.py's RELIABILITY_WEIGHT_D/T/S/H and
RELIABILITY_R_THRESHOLD) from real, manually-labeled data.

Input: scripts/calibration_data/manifest.json, produced by
scripts/collect_calibration_data.py and then manually reviewed -- each
candidate's "label" field filled in by a human looking at its snapshot
image (1 = genuine crossing, 0 = false positive).

Method: LogisticRegression(D, T, S, H) -> label (scikit-learn), matching
the linear form R = wD*D + wT*T + wS*S + wH*H already used at runtime.
The fitted coefficients are normalized to sum to 1 so they stay directly
comparable to the current hand-picked defaults (0.40/0.20/0.20/0.20).

HONEST LIMITATION -- read before trusting any output this script prints:
This project's real, public benchmark video (demo/videos/vtest.avi, a
daytime pedestrian-crossing clip) does not contain any actual false
detections once a human reviews the snapshots: every one of the 52 real
raw fence-crossing candidates in the labeled manifest is a real, correctly
detected person genuinely at or crossing the marked zone boundary (see
docs/LIMITATIONS.md for the full writeup). A dataset with a single label
value has no decision boundary for logistic regression to find -- sklearn
either raises or returns a degenerate fit (e.g. all weight on the
intercept, none on D/T/S/H). This script detects that case explicitly and
refuses to overwrite the current defaults with a meaningless fit; it says
so plainly rather than printing fake-looking numbers.

Usage:
    python scripts/fit_reliability_weights.py \\
        --manifest scripts/calibration_data/manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit reliability weights from labeled real data")
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    with open(manifest_path) as f:
        manifest = json.load(f)

    candidates = manifest["candidates"]
    unlabeled = [c for c in candidates if c.get("label") is None]
    if unlabeled:
        print(f"{len(unlabeled)} of {len(candidates)} candidates still have label=null.")
        print("Manually review their snapshots and fill in 'label' (1 or 0) before fitting.")
        for c in unlabeled:
            print(f"  {c['candidate_id']}: {c['snapshot']}")
        raise SystemExit(1)

    labels = sorted(set(c["label"] for c in candidates))
    print(f"Loaded {len(candidates)} labeled real candidates from {manifest_path}")
    print(f"Label distribution: {[(v, sum(1 for c in candidates if c['label'] == v)) for v in labels]}")

    if len(labels) < 2:
        print()
        print("=" * 72)
        print("CANNOT FIT: all labeled candidates share the same label "
              f"({labels[0]}).")
        print(
            "This is a real, honest finding about this dataset, not a bug in this\n"
            "script: demo/videos/vtest.avi's real fence-crossing candidates, once a\n"
            "human actually looked at every snapshot, turned out to be 100% genuine\n"
            "detections (label=1) -- no false positives to learn to reject. A binary\n"
            "classifier fitted on a single class has no decision boundary; sklearn's\n"
            "LogisticRegression on this input either raises or returns an intercept-\n"
            "only fit with zero weight on D/T/S/H, which would be worse than the\n"
            "current hand-picked defaults, not better."
        )
        print(
            "\nWhat this does NOT mean: it does not mean the current default weights\n"
            "(RELIABILITY_WEIGHT_D/T/S/H = 0.40/0.20/0.20/0.20, R_THRESHOLD = 0.75 in\n"
            "edge/reliability/decision.py) are proven correct -- only that this\n"
            "specific real video cannot supply the negative examples needed to\n"
            "calibrate against. See docs/LIMITATIONS.md for what a real calibration\n"
            "dataset would need (footage with actual false detections: animals,\n"
            "wind-blown foliage, shadow/glare artifacts, sensor noise at night, etc.)\n"
            "and why none of NETRAKSH's currently available real footage has that."
        )
        print("=" * 72)
        print("\nCurrent defaults left UNCHANGED. No weights were written anywhere.")
        raise SystemExit(0)

    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
    except ImportError as exc:
        raise SystemExit(f"scikit-learn/numpy required to fit: {exc}")

    X = np.array([[c["D"], c["T"], c["S"], c["H"]] for c in candidates])
    y = np.array([c["label"] for c in candidates])

    model = LogisticRegression()
    model.fit(X, y)

    raw = model.coef_[0]
    total = sum(abs(w) for w in raw)
    if total == 0:
        print("Fit converged to zero weight on all four features -- degenerate result.")
        print("Current defaults left UNCHANGED.")
        raise SystemExit(0)

    wD, wT, wS, wH = (abs(w) / total for w in raw)

    print("\nFitted (normalized) weights from real labeled data:")
    print(f"  wD={wD:.4f}  wT={wT:.4f}  wS={wS:.4f}  wH={wH:.4f}")
    print("\nCurrent hand-picked defaults (edge/reliability/decision.py):")
    print("  wD=0.4000  wT=0.2000  wS=0.2000  wH=0.2000")
    print(
        "\nThese are NOT applied automatically -- per this project's practice of never\n"
        "silently changing a significant runtime default, applying them requires an\n"
        "explicit decision and edit to edge/reliability/decision.py (or setting the\n"
        "RELIABILITY_WEIGHT_* environment variables), plus documenting the change and\n"
        "the sample it came from in docs/ARCHITECTURE.md."
    )


if __name__ == "__main__":
    main()
