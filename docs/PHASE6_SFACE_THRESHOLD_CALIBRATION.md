# PHASE 6: SFACE THRESHOLD CALIBRATION

## Status
NOT MEASURABLE — NO VALID GROUND TRUTH

## Objective
Select a candidate operating threshold (Cosine Similarity) for the SFace model from a dedicated validation subset of border CCTV face imagery.

## Data Provenance
Currently, there is no verified border-specific evaluation dataset integrated into the repository. We do NOT use generic web-crawled datasets (e.g. LFW) to calibrate production thresholds for edge surveillance.

## Methodology (Pending Data)
When a valid dataset is supplied, the calibration script will:
1. Embed all subjects across the validation split.
2. Generate all Genuine (same identity) and Impostor (different identity) pairs disjointly.
3. Perform a threshold sweep from `-1.0` to `1.0`.
4. Calculate TP, TN, FP, FN, FAR, FRR at each threshold.
5. Select the threshold yielding an acceptable FAR (e.g., FAR = `1e-3` or `1e-4` depending on operational risk tolerance) while maximizing TAR.

## Current Configuration
The threshold configuration variable is:
`FACE_MATCH_THRESHOLD`

**Fallback Value**: `0.363` (The default provided by OpenCV SFace documentation for generic verification, but NOT calibrated for NETRAKSH).
