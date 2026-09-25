# Phase 6: Face Benchmark Preparation

## Status
**NOT MEASURABLE** — Artifact inspected but not yet executed in edge pipeline.

## Evaluation Protocol
Future execution will test:
1. **L2 Normalization & Distance:** Verification of Euclidean distance or cosine similarity on the raw `fc1` output.
2. **ROC/TAR:** Thresholds are entirely UNCALIBRATED. 
   - A threshold tuning pass will calculate True Acceptance Rate (TAR) @ False Acceptance Rate (FAR) using a structured genuine/imposter pairing matrix.

## Alignment Validation
Current pipeline utilizes a generic `FaceAligner`. 
- We must verify that the crop dimensions (112x112) and landmark geometric distribution identically match what the SFace model expects.
- Any discrepancy in rotation/scale will drastically degrade cosine similarity outputs.
