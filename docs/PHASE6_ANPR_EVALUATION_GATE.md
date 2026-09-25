# PHASE 6: ANPR EVALUATION GATE

## 1. CURRENT ANPR ARCHITECTURE
**Status**: VALIDATED & INTACT

The current default pipeline (`ANPR_PIPELINE=legacy`) is active and remains unmodified:
`VEHICLE DETECTION/TRACK → HeuristicPlateLocalizer (Haar/Contour) → EasyOCR → Temporal OCR Fusion → Watchlist Matching`.
Resource pressure handling (`NOT_EVALUATED_RESOURCE_PRESSURE`) and evidence generation mechanisms are fully preserved.

## 2. MODEL PROVENANCE
**Localization Artifact**: `license_plate_detection_lpd_yunet_2023mar.onnx`
**Status**: VERIFIED
The exact LPD_YuNet artifact is present and documented under the Enhanced ANPR path, bound by its SHA-256 hash. The OCR engine remains EasyOCR.

## 3. EVALUATION DATASET PROCUREMENT AUDIT
**Status**: NO DATASET CURRENTLY APPROVED
Public datasets investigated for commercial border-surveillance evaluation:
- **UFPR-ALPR**: Academic Use Only (Denied). Geographic Relevance: LOW.
- **CCPD**: Commercial restriction unclear, heavily biased towards Chinese plates (Rejected). Geographic Relevance: LOW.
- **AOLP**: Academic Use Only (Denied). Geographic Relevance: LOW.
- **OpenALPR Benchmarks**: Lack controlled condition slices / sequential metadata (Rejected). Geographic Relevance: MEDIUM.

**Conclusion**: No dataset has currently been verified and approved for NETRAKSH ANPR evaluation under the project's provenance, licensing, geographic relevance, and ground-truth requirements.

## 4. METRICS IMPLEMENTED
The following metric evaluators have been successfully built into the evaluation framework (`edge/evaluation/anpr_metrics.py`):
- **Localization Evaluation**: Bounding Box IoU derived from quadrilaterals, Precision, Recall, F1. (Requires Localization GT).
- **OCR Evaluation**: Exact Match (Raw), Exact Match (Normalized), Character Error Rate (CER), Levenshtein Edit Distance. (Requires Text GT).
- **Temporal/System Evaluation**: Exact match improvement, decision latency. (Requires Sequence GT).

## 5. EVALUATION STATUS
Due to the absence of an approved dataset, actual execution of the framework against ground truth yields the following explicit states:
- **Localization Metrics**: NOT MEASURABLE
- **OCR Metrics**: NOT MEASURABLE
- **Temporal Metrics**: NOT MEASURABLE
- **Condition Slices**: NOT MEASURABLE

## 6. PROMOTION CRITERIA
The `ANPRPromotionGate` requires:
- `DATASET_APPROVED` state.
- Localization F1 Score >= `0.90`.
- OCR Exact Match (Normalized) >= `0.85`.

## 7. BENCHMARK AND LATENCY
**Status**: NOT VALIDATED

The current `scripts/benchmark_anpr.py` is classified strictly as a **SIMULATION / HARNESS**. It does not execute the complete production ANPR pipeline on representative real input and therefore cannot establish actual latency.

*Actual NETRAKSH Measurements* require:
1. Real execution of ANPR code against video/image inputs.
2. High-resolution monotonic timing over multiple iterations (excluding warm-up).
3. Explicit environmental metadata (OS, CPU, Python version, runtime, resolution).

Until these are physically established, performance remains NOT VALIDATED.

Enhanced ANPR remains strictly OPT-IN pending the lawful collection of a proprietary internal evaluation dataset.
