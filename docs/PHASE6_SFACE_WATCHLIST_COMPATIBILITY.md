# PHASE 6: SFACE WATCHLIST COMPATIBILITY

## Status
VERIFIED

## Architecture Details
The integration cleanly bridges SFace embeddings with the in-memory `EmbeddingWatchlistIndex`.

- **Training (Sync from Backend)**: When `sync_from_backend()` downloads base64 JPEGs from the API, it now extracts standard RGB versions (via `decode_base64_face_image_rgb`) alongside the legacy LBPH grayscale versions.
- **Embedding Ingestion**: Instead of providing `cv2.face` with raw pixel images, the `UnifiedFaceRecognizer` passes each RGB image into `SFaceEmbeddingModel` to generate a normalized 128-d embedding, assigning it to the subject's identity profile.
- **Privacy Enforcement**: SFace embeddings reside entirely within volatile RAM inside `EmbeddingWatchlistIndex`. They are not transmitted over the network, written to logs, or emitted as Prometheus labels. Only pseudonymous identifiers (`person_id`) and classical thresholds are exposed.

## Legacy Compatibility
The LBPH subsystem is left intact. If `FACE_RECOGNITION_ENGINE` is set back to `lbph` (the production default), the codebase naturally bypasses all embedding extraction logic and reverts to standard `LBPHFaceRecognizer.train()` usage.
