# Phase 6: Face Privacy Model

## Biometric Data Rule
Face embeddings derived from the inference pipeline represent sensitive biometric markers. The future implementation architecture MUST rigorously prevent their exposure.

### Log Management
- Embeddings MUST NOT be logged to stdout, files, or telemetry.
- Embeddings MUST NOT be exported to Prometheus labels.
- Structural logs may only emit a pseudonymous identity string (e.g., `subj_uuid`) and a `similarity_score`.

### API & Frontend
- Embeddings MUST NOT be transmitted over API endpoints.
- External systems may only receive the decision (`CONFIRMED`, `UNKNOWN`) and the associated internal pseudonymous ID.

### Storage
- Persistent biometric storage is restricted unless explicitly approved.
- When evaluation models run, temporary in-memory vectors are immediately garbage collected after similarity scoring.
