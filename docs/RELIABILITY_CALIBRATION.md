# Reliability Calibration Data Contract

This document defines the strict requirements for collecting, labeling, and training a future `CalibratedReliabilityEngine` for NETRAKSH.

Because the currently available `MOT16` tracking datasets lack verified Temporal tracking consistency (`T`) and Camera Health (`H`) scores mapped to real-world edge scenarios, **CALIBRATION IS NOT YET POSSIBLE**.

## 1. Feature Schema

A valid calibration training dataset MUST export candidates with the following required features, in exact order, to match the engine's expected schema:

1. `D` (Detector Confidence): Raw YOLO score `[0,1]`
2. `T` (Temporal Score): Track consistency `[0,1]`
3. `S` (Scene Quality Score): Computed via `SceneConditionReport` heuristic `[0,1]`
4. `H` (Health Quality Score): Computed via `CameraHealthReport` heuristic `[0,1]`

Optional future features (DO NOT append to `LogisticRegression` without versioning the schema):
- `brightness`, `contrast`, `glare`, `blur`, `object_size`, `track_age`

## 2. Event Labeling Semantics

Every exported candidate must contain an explicit, verified `label`:
- `1`: Verified genuine security event (e.g., true human fence crossing, true vehicle loitering).
- `0`: Verified false alarm (e.g., shadow, spider web, sensor noise, reflection).

> [!CAUTION]
> Do NOT guess these values. Do NOT assume any generic tracking bounding box implies a true security event. 

## 3. Collection Process

To build a valid dataset, the edge node must capture the full `T` and `H` state during a candidate's lifetime.
The data must consist of:
- **True Positives**: Genuine human/vehicle events across varying scene conditions.
- **True Negatives / Hard False Positives**: Actual spurious detections (animals, foliage, rain, sun glare) that YOLO incorrectly scores highly.

*MOT16 provides bounding boxes but cannot simulate camera health failures (`H`) or edge tracker degradation (`T`) natively. It is insufficient.*

## 4. Methodology and Risks

- **Leakage Risk**: Do not train and validate on the same physical camera viewpoint unless testing generalization is not required.
- **Class Imbalance**: False alarms may vastly outnumber genuine events. Stratified sampling or class weighting may be necessary.
- **Safety Gate**: The model is ONLY invoked if the camera is NOT `FAILED`. Camera failures are handled by a hard Gate 1 absolute rule and should not be passed to the model training loop.

## 5. Promotion Criteria

A calibrated engine will ONLY be promoted to the default `RELIABILITY_ENGINE` if empirical evidence proves it outperforms the `LegacyReliabilityEngine` on:
- Brier Score (better calibrated probabilities).
- False Positive Rate (FPR) vs False Negative Rate (FNR) tradeoff.
- Reliability during known degraded conditions (`LOW_LIGHT_NIGHT`, `GLARE`, `FOG_RAIN`).

Accuracy alone is not sufficient. 
Until proven: `RELIABILITY_ENGINE=legacy`.
