# Phase 4 Architecture Review: Corrected & Verified

*Date: 2026-09-14 | State: Phase 3 Completed | Target: SIH PS-26187*

This document serves as the corrected, forensic audit of the NETRAKSH system prior to Phase 4 execution. It reconciles previous architectural assumptions with the actual verified implementation.

---

## 1. CORRECTIONS TO PREVIOUS REVIEW

### 1.1 ANPR Pipeline
- **CLAIM IN PREVIOUS REVIEW**: "Full-frame PaddleOCR" and "Poor quality".
- **ACTUAL VERIFIED STATE**: The system implements an `EnhancedANPRModule` utilizing `EasyOCR` (not PaddleOCR). It does *not* run full-frame OCR; it uses a `HeuristicPlateLocalizer` to crop the lower-middle 55% of the vehicle bounding box, applies CLAHE, and maintains a `TemporalOCRFusion` history over 10 frames to confirm stability.
- **EVIDENCE**: `edge/detection/anpr.py` (`HeuristicPlateLocalizer`, `EasyOCREngine`, `TemporalOCRFusion`) and `edge/rules/modules.py`.
- **CORRECTED ASSESSMENT**: ANPR is well-architected temporally and pre-processing-wise. The only gap is replacing the heuristic bounding box with a dedicated AI model.
- **REMAINING GAP**: Dedicated plate localization model (e.g., YOLOv8-license-plate) to replace `HeuristicPlateLocalizer`.

### 1.2 Face Recognition Pipeline
- **CLAIM IN PREVIOUS REVIEW**: "Face detection missing" / "Scaffolded only".
- **ACTUAL VERIFIED STATE**: Face detection is actively implemented and defaults to a bundled Haar Cascade (`haarcascade_frontalface_default.xml`). It seamlessly upgrades to `RetinaFace` if the package is available. The embedding engine is scaffolded (awaiting ONNX model). Liveness is explicitly absent.
- **EVIDENCE**: `edge/rules/modules.py` (`FaceDetectionModule`), `cv2.CascadeClassifier`.
- **CORRECTED ASSESSMENT**: Detection is fully functional. Alignment and Embedding are scaffolded.
- **REMAINING GAP**: Validated face embedding model (e.g., ArcFace ONNX) and RetinaFace deployment.

### 1.3 Security: RBAC & Secrets
- **CLAIM IN PREVIOUS REVIEW**: "RBAC missing", "Secrets management missing".
- **ACTUAL VERIFIED STATE**: JWT-based RBAC is strictly implemented with `ADMIN`, `OPERATOR`, and `AUDITOR` roles gating all API routes. `config.py` enforces strict startup validation in `production` mode, completely refusing to boot if default/weak passwords or default `SECRET_KEY` are detected.
- **EVIDENCE**: `backend/security/auth.py` (`require_admin`, `require_any_role`) and `backend/config.py` (production startup validation).
- **CORRECTED ASSESSMENT**: Backend access control and secret validation are READY.
- **REMAINING GAP**: Edge PKI / mutual TLS (mTLS) for device identity.

### 1.4 Offline Resilience & Buffering
- **CLAIM IN PREVIOUS REVIEW**: "Offline mode partial", "Local buffering partial".
- **ACTUAL VERIFIED STATE**: The edge node operates a robust, priority-ordered offline sync queue backed by SQLite. If the WebSocket drops, it buffers locally and syncs idempotently upon reconnection.
- **EVIDENCE**: `tests/unit/test_sync_client_priority.py`, `tests/integration/test_backend_e2e.py` (`TestOfflineOutboxToRealBackend`).
- **CORRECTED ASSESSMENT**: Offline edge resilience is READY.
- **REMAINING GAP**: None for the local sync buffer mechanism.

### 1.5 Reliability Calibration
- **CLAIM IN PREVIOUS REVIEW**: "Reliability partial".
- **ACTUAL VERIFIED STATE**: The `LegacyReliabilityEngine` is implemented and functional. The `CalibratedReliabilityEngine` is fully implemented in code but lacks a real trained artifact (model weights) because required edge data (D/T/S/H) is not available in public datasets like MOT16. 
- **EVIDENCE**: `docs/RELIABILITY_CALIBRATION.md`, `scripts/collect_calibration_data.py`.
- **CORRECTED ASSESSMENT**: The *engine* is fully implemented. The *calibrated model* is missing.
- **REMAINING GAP**: Actual data collection on edge devices to fit the logistic regression model.

### 1.6 General Readiness
- **CLAIM IN PREVIOUS REVIEW**: "SIH readiness 60%", "Production readiness 30%".
- **ACTUAL VERIFIED STATE**: Removed arbitrary numerical scoring. The system is structurally robust (GREEN) across core backend, temporal tracking, and offline edge operations. The AI models (Faces/Plates) are the primary AMBER components preventing a full production release.

---

## 2. FINAL MATURITY ASSESSMENT

- **CORE ARCHITECTURE**: GREEN. Offline buffering, DB schema, WebSocket sync, RBAC, and Cryptographic Evidence.
- **TEMPORAL LOGIC**: GREEN. Behavior tracking, cross-camera distance logic, Temporal OCR fusion.
- **AI MODELS**: AMBER. Lacking dedicated plate localizer and face embedding weights.
- **PRODUCTION DEPLOYMENT**: AMBER. Runs as python processes; needs Docker orchestration and GPU optimization.
