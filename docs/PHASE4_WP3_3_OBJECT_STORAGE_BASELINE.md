# NETRAKSH — Phase 4 WP-3.3 Object Storage Baseline

## Forensic Audit of Current Evidence Flow

Before implementing a robust object-storage architecture, the following is the exact state of evidence storage and retrieval in the current deployment.

### 1. Evidence Creation & Edge Storage
- **Creation**: `edge/evidence/packager.py` captures frames, optionally encrypts them via AES-256-GCM, and saves the binary file to the local edge filesystem (e.g., `edge/data/clips/`).
- **Metadata**: It records the local path as `evidence_clip_ref` within the `EvidencePackage`.
- **Cryptographic Binding**: The JSON payload (including `evidence_clip_ref`) is hashed (SHA-256) and signed (Ed25519) using the edge's private key. The `kid` is attached.

### 2. Edge-to-Central Sync
- **Mechanism**: `edge/sync/sync_client.py` reads the signed JSON payloads from `sync_queue.db` and sends them via `POST /events`.
- **CRITICAL GAP**: The sync client **does not transmit the actual evidence bytes**. It only sends the JSON metadata (including the `evidence_clip_ref` string).

### 3. Backend Ingestion & Database
- **Storage**: The backend inserts the event metadata into the `events` table (PostgreSQL), retaining the raw JSON and the `evidence_clip_ref` string.
- **Hash-Chain**: The `evidence_chain` table tracks sequence numbers and hashes to preserve continuity.
- **No Upload Validation**: Because the edge doesn't upload the file, the backend API cannot validate the evidence binary content hash upon ingestion.

### 4. Evidence Retrieval (API & Frontend)
- **Endpoint**: `GET /api/events/{event_id}/evidence-image`.
- **Abstraction**: Uses `backend/services/evidence_storage.py` -> `get_evidence_storage()`.
- **Current Behavior**: The `LocalFilesystemStorage` class reads the file directly from the backend's local filesystem by extracting the basename from `evidence_clip_ref` and joining it with `settings.EVIDENCE_CLIPS_DIR`. 
- **Limitation**: This *only* works because the edge and backend currently run on the same physical machine and share a filesystem (documented in `LIMITATIONS.md`).
- **Object Storage**: An `ObjectStorageBackend` class exists but is a stub raising `NotImplementedError`.

### 5. Deletion & Cleanup
- **State**: There is currently no active lifecycle policy, cleanup job, or deletion workflow for evidence clips. The filesystem will grow indefinitely.
- **Offline References**: Historical DB records hold static `evidence_clip_ref` paths that are tightly coupled to a local disk path rather than a portable object identifier.

## Conclusion
The current architecture tightly couples the backend to the edge's local disk, completely bypassing network-based evidence ingestion. To decouple this, the edge must explicitly upload evidence binaries alongside the metadata, and the backend must store them in a secure, provider-agnostic object store, updating the retrieval APIs to issue signed URLs rather than reading local disk files.
