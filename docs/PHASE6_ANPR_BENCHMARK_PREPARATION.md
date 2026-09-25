# Phase 6: ANPR Benchmark Preparation

## 1. Status
**NOT MEASURABLE** (Ground truth dataset and environment execution block remaining latency evaluations).

## 2. Input Isolation
The testing matrix will feed the `LPD_YuNet` ONNX artifact the exact same static camera frames previously used to validate the `HeuristicPlateLocalizer`. 
- This ensures 1:1 parity in image conditions.
- Expected resolutions: Scaled via `cv.resize` to `320x240` prior to inference (as dictated by the model's optimal prior boxes).

## 3. Metrics to be Captured (Post-Integration)
- `load_time_ms`: Time to `ort.InferenceSession()`.
- `preprocess_ms`: Time to `cv.dnn.blobFromImage`.
- `inference_ms`: Time to `session.run()`.
- `postprocess_ms`: Time to evaluate priors, NMS, and coordinate transformation.
- `e2e_latency_ms`: Total execution envelope.

## 4. Accuracy Evaluation Gate
Must use the structured test sets defined in `PHASE6_DATA_REQUIREMENTS.md` with explicit bounding box intersections (IoU > 0.5 for localization success) before character error rate (CER) is evaluated against `EasyOCR`.
