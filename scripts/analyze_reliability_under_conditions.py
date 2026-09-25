#!/usr/bin/env python
"""
NETRAKSH — Real analysis of the Hybrid Reliability Engine's actual
DETECTED/UNCERTAIN outcomes on labeled calibration manifests, using the
exact runtime weight/threshold constants from edge/reliability/decision.py
(imported, not copied — so this can never silently drift from what the
real pipeline actually does).

This is NOT weight fitting (see scripts/fit_reliability_weights.py's
docstring for why this project's labeled manifests are all single-class
and can't support a fit). This instead answers a different, real question
raised by comparing the daytime vs synthetic-night/fog manifests: given
that every labeled candidate here is a genuine crossing (label=1), how
many of them does the CURRENT hand-picked formula actually mark UNCERTAIN
rather than DETECTED — i.e., how much real evidence is there for
architecture v4 §8's documented "intentional behavior change" (degraded
scene quality should make the system trust itself less, at the cost of
sometimes doubting genuine detections)?

Usage:
    python scripts/analyze_reliability_under_conditions.py \\
        scripts/calibration_data/manifest.json \\
        scripts/calibration_data_night/manifest.json \\
        scripts/calibration_data_fog/manifest.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from edge.reliability.decision import (
    RELIABILITY_R_THRESHOLD,
    RELIABILITY_WEIGHT_D,
    RELIABILITY_WEIGHT_H,
    RELIABILITY_WEIGHT_S,
    RELIABILITY_WEIGHT_T,
)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/analyze_reliability_under_conditions.py <manifest.json> [...]")

    print(
        f"Runtime constants (edge/reliability/decision.py, imported directly): "
        f"wD={RELIABILITY_WEIGHT_D} wT={RELIABILITY_WEIGHT_T} wS={RELIABILITY_WEIGHT_S} "
        f"wH={RELIABILITY_WEIGHT_H} R_THRESHOLD={RELIABILITY_R_THRESHOLD}\n"
    )

    for path in sys.argv[1:]:
        with open(path) as f:
            manifest = json.load(f)

        candidates = manifest["candidates"]
        labeled = [c for c in candidates if c.get("label") is not None]
        genuine = [c for c in labeled if c["label"] == 1]

        detected = 0
        uncertain = 0
        r_values = []
        for c in genuine:
            r = (
                RELIABILITY_WEIGHT_D * c["D"]
                + RELIABILITY_WEIGHT_T * c["T"]
                + RELIABILITY_WEIGHT_S * c["S"]
                + RELIABILITY_WEIGHT_H * c["H"]
            )
            r_values.append(r)
            if r >= RELIABILITY_R_THRESHOLD:
                detected += 1
            else:
                uncertain += 1

        synth = manifest.get("synthetic_condition", "none")
        print(f"{path}  (synthetic_condition={synth})")
        print(f"  {len(genuine)} genuine (label=1) candidates")
        if genuine:
            print(f"  R range: {min(r_values):.3f} - {max(r_values):.3f}  (mean {sum(r_values)/len(r_values):.3f})")
            print(f"  DETECTED (R >= {RELIABILITY_R_THRESHOLD}): {detected}/{len(genuine)}  "
                  f"({100*detected/len(genuine):.0f}%)")
            print(f"  UNCERTAIN (a real crossing NOT flagged, per current weights): {uncertain}/{len(genuine)}  "
                  f"({100*uncertain/len(genuine):.0f}%)")
        print()


if __name__ == "__main__":
    main()
