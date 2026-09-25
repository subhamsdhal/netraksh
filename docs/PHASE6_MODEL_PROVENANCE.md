# Phase 6: Model Provenance Gate

## 1. Rules of Engagement
- Candidate models (e.g., LPRNet, RetinaFace, ArcFace variants) are listed for investigation only.
- Being listed here does not constitute authorization to integrate.
- No dummy/mock models.

## 2. Provenance Record Schema
For each model considered, the following must be documented before download:
- `model_name`
- `model_version`
- `exact_repository_url`
- `exact_artifact_url`
- `weights_hash` (SHA-256)
- `runtime` (ONNX/PyTorch/TensorRT)
- `input_contract` (e.g., 112x112 RGB image)
- `output_contract` (e.g., 512-d float32 vector)
- `code_license` / `weights_license`
- `training_data_notes`
- `commercial_status` / `redistribution_status`
- `known_limitations`

## 3. Candidate Investigation Table
*(This table is a structural template; no models are approved yet)*

| Candidate | Target | License | Hash | Status |
|---|---|---|---|---|
| *TBD* | ANPR OCR | *TBD* | *TBD* | `UNVERIFIED — DO NOT USE` |
| *TBD* | Face Embed | *TBD* | *TBD* | `UNVERIFIED — DO NOT USE` |
