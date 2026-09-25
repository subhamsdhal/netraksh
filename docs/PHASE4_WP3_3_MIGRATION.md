# Phase 4 WP-3.3: Data Migration

## 1. Objective
Migrate legacy evidence binaries stored natively on the backend's local filesystem into the new provider-agnostic Object Storage architecture (e.g., S3). 

## 2. Idempotent Migration Script
The script `scripts/migrate_evidence_to_object_storage.py` is an idempotent utility designed for zero-downtime execution.

### Methodology
1. **Query Unmigrated Data**: Selects all `Event` records where `storage_status` is NULL.
2. **Path Resolution**: Resolves legacy `evidence_clip_ref` strings to physical disk locations.
3. **Binary Content Hash**: Loads the legacy binary into memory and computes the SHA-256 hash, generating the `content_hash`.
4. **Object Storage Upload**: Uploads the binary to the configured `EvidenceStorageBackend` using a deterministic key:
   `evidence/{camera_id}/{date_str}/{event_id}.jpg[.enc]`
5. **Database Update**: Updates `Event` with `storage_provider`, `storage_status` ('AVAILABLE'), `content_hash`, `content_size`, and `uploaded_at`.

### Safety & Resilience
- **Dry-run by default**: The script runs in dry-run mode unless executed with `--commit`, allowing safe auditing of missing files.
- **Idempotency**: Safe to interrupt and rerun. Events already marked `AVAILABLE` (or processed during subsequent runs) are skipped or updated non-destructively.
- **Missing File Handling**: If a physical file is missing from disk, the event's `storage_status` is explicitly set to `MISSING`, ensuring the reconciliation process acknowledges the discrepancy without failing the entire migration loop.

## 3. Zero-Downtime Accessibility
- Legacy requests for evidence via `GET /events/{event_id}/evidence-image` gracefully handle both pre-migration (`evidence_clip_ref`) and post-migration (`object_key`) data.
- If the configured provider supports signed URLs (e.g., S3), legacy application-level encrypted objects will be delivered to the client via 307 Redirect, ensuring backward compatibility with frontend decryption or necessitating architectural transitions to pure server-side encryption.
