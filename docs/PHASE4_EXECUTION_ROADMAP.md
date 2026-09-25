# Phase 4 Execution Roadmap

*Date: 2026-09-14 | State: Phase 3 Completed | Target: SIH PS-26187*

Based on the forensic audit of the actual codebase, Phase 4 will address the *true* remaining gaps preventing production deployment. 

**STRICT RULE**: No model integration may proceed without acquiring explicit, legally-cleared model weights. The system architecture is fully prepared to receive them; the limitation is purely asset acquisition and verification.

---

## WORK PACKAGE 1: AI Model Procurement & Integration

### WP-1.1: ANPR Plate Localization
- **Context**: `edge/detection/anpr.py` uses `HeuristicPlateLocalizer` (bottom 55% crop of a vehicle track). `EasyOCREngine` and `TemporalOCRFusion` are already fully implemented and robust.
- **Action**: 
  1. Procure a permissive-licensed ONNX YOLOv8-based license plate localizer.
  2. Implement `AIPlateLocalizer` adhering to the existing `PlateLocalizer` interface.
  3. Swap `HeuristicPlateLocalizer` out for `AIPlateLocalizer` in `EnhancedANPRModule`.

### WP-1.2: Face Embedding
- **Context**: `FaceDetectionModule` implements face detection (Haar/RetinaFace). `ONNXFaceEmbeddingEngine` is scaffolded but lacks a model.
- **Action**:
  1. Procure a permissive-licensed ONNX Face Embedding model (e.g., ArcFace variant).
  2. Map the model's I/O in `ONNXFaceEmbeddingEngine`.
  3. Validate against the existing `EmbeddingWatchlistIndex` cosine similarity logic.

---

## WORK PACKAGE 2: Edge-to-Cloud Security

### WP-2.1: Mutual TLS (mTLS) 
- **Context**: JWT, RBAC, and crypto-signatures are fully implemented. Transport layer is currently standard TLS (or plaintext locally) via WebSocket/HTTP. Edge devices do not yet authenticate via client certificates.
- **Action**:
  1. Enforce `TLS_ENABLED=True` and configure Uvicorn/NGINX to require client certificates.
  2. Provision client certificates for edge nodes.
  3. Update `sync_client_priority.py` to present the client certificate during WebSocket and HTTP connections.

---

## WORK PACKAGE 3: Reliability Calibration

### WP-3.1: Edge Data Collection
- **Context**: `CalibratedReliabilityEngine` requires `[D, T, S, H]` features, which don't exist in public datasets.
- **Action**:
  1. Deploy the edge node with `LegacyReliabilityEngine` in a staging environment.
  2. Enable the existing `scripts/collect_calibration_data.py` pipeline.
  3. Manually label the collected true-positive and false-positive events.

### WP-3.2: Engine Training & Promotion
- **Context**: The `CalibratedReliabilityEngine` needs weights.
- **Action**:
  1. Train a Logistic Regression model on the collected data.
  2. Validate that the Brier score outperforms the `LegacyReliabilityEngine`.
  3. Promote the weights and enable `CalibratedReliabilityEngine` by default.

---

## WORK PACKAGE 4: Production Deployment

### WP-4.1: Containerization
- **Context**: System runs as naked Python processes.
- **Action**: 
  1. Create `Dockerfile.edge` with ONNXRuntime-GPU, OpenCV, and GStreamer dependencies.
  2. Create `Dockerfile.backend` with PostgreSQL client dependencies.
  3. Provide a `docker-compose.yml` for unified deployment.

### WP-4.2: Hardware Acceleration
- **Context**: Processing currently defaults to CPU.
- **Action**:
  1. Ensure YOLOv8, RetinaFace, and Face Embeddings run on TensorRT or CUDA execution providers in ONNXRuntime.
  2. Validate FPS metrics on the target edge hardware.
