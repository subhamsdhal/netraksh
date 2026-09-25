# Phase 4 WP-3.3: Object Storage Architecture

## 1. Overview
The legacy evidence ingestion pipeline tightly coupled the backend API with the local filesystem, requiring synchronous creation of files in `edge/data/clips` or relying on shared filesystem mounts between edge and cloud. WP-3.3 shifts this architecture to a provider-agnostic, two-stage object storage design (e.g., S3-compatible).

## 2. Two-Stage Sync Protocol
To prevent data loss and support bulk object storage natively, edge ingestion now uses a deterministic two-stage pipeline:

1. **Stage 1 (Metadata Ingestion)**
   - Edge sends JSON metadata (including logical evidence hashes) to `POST /events`.
   - Backend persists the Event and logical evidence records.
   - Status remains durability-guaranteed in PostgreSQL.

2. **Stage 2 (Binary Content Upload)**
   - Edge computes the SHA-256 hash of the binary file.
   - Edge uploads the file via `POST /events/{event_id}/evidence` as `multipart/form-data`, passing the `expected_hash`.
   - Backend enforces mTLS edge identity binding, recalculates the hash to verify, and uploads the file to the active `EvidenceStorageBackend` implementation (e.g., `S3Storage`).
   - Backend marks the `storage_status` as `AVAILABLE`.

## 3. Storage Abstraction
A new `EvidenceStorageBackend` abstract base class governs storage. Implementations include:
- `LocalFilesystemStorage`: Legacy and development fallback, preventing path traversal using strict `os.path.commonprefix` checks.
- `S3Storage`: Production `boto3`-backed S3 implementation providing `put_object`, `get_object`, and `generate_signed_url` capabilities.

## 4. Encryption at Rest
Object storage natively leverages provider-supported server-side encryption (SSE-S3 or SSE-KMS). Application-level encryption of binaries during this phase is NOT implemented within the Object Storage abstraction; legacy `.jpg.enc` files continue to be decrypted by the backend upon access, while new pipelines will rely on SSE and TLS.

## 5. Security & Provenance
- Logical hashes in the `EvidencePackage` (Ed25519) remain intact to prove logical chain integrity.
- Binary Content Hashes act as a transport and data-at-rest integrity check, preventing partial uploads, bit rot, and tampering within the object store.
