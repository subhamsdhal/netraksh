# Phase 6: Evaluation Protocol

## 1. Ground Truth Enforcement
Evaluation scripts (`scripts/phase6_evaluate_anpr.py` and `scripts/phase6_evaluate_face.py`) MUST NOT generate synthetic accuracy metrics.
If a dataset is not physically present, the script outputs `DATASET NOT AVAILABLE`.
If ground truth annotations are absent, accuracy is logged as `NOT MEASURABLE`.

## 2. Separation of Metrics
- **ANPR:** Bounding box accuracy (localization) and OCR accuracy (transcription) must be reported separately before defining an end-to-end success rate.
- **Face:** Verification metrics (matching known pairs) must not be conflated with closed-set identification accuracy (Rank-1).

## 3. Temporal Validation
Evaluation must capture the existing temporal tracking behavior.
Metrics should include:
- Single-frame accuracy (how accurate is one frame's OCR/Embedding)
- Temporal accuracy (how accurate is the aggregated result over a track)
- Confirmation latency (time/frames required to reach `CONFIRMED` state).

## 4. Promotion Criteria
To be promoted to the production default, a model must achieve:
1. Provenance & License Verification
2. Validated Runtime
3. Positive Accuracy Delta (over Baseline)
4. Evaluated Condition Slices
5. Acceptable Resource Cost
6. Passed Regression
7. Maintained Fallback Mechanism
