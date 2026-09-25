# WP-3.3 Object Storage — Test Matrix

Status: **NOT EXECUTED — ENVIRONMENT BLOCKED**

## Legend
- ✅ = Implementation verified in source code
- ❌ = Not implemented or defect
- 🔧 = Was defective; now fixed in reconciliation pass
- ⛔ = NOT EXECUTED — environment blocked

| ID | Test Case | Implementation Status | Execution Status |
| :--- | :--- | :--- | :--- |
| **DEP-01** | `boto3==1.34.0` declared in `requirements.txt` | ✅ Line 42 | ⛔ |
| **DEP-02** | `python-multipart` declared (required for `UploadFile`) | ✅ Line 34 | ⛔ |
| **CFG-01** | `OBJECT_STORAGE_PROVIDER` setting present in `config.py` | ✅ | ⛔ |
| **CFG-02** | `OBJECT_STORAGE_BUCKET/ACCESS_KEY/SECRET_KEY/ENDPOINT/REGION` present | ✅ | ⛔ |
| **CFG-03** | Production startup FAILS if `OBJECT_STORAGE_PROVIDER=s3` but credentials absent | ✅ Fixed in reconciliation | ⛔ |
| **CFG-04** | `MAX_UPLOAD_SIZE_BYTES` configurable (default 5 MiB) | ✅ | ⛔ |
| **LF-01** | `LocalFilesystemStorage._get_safe_path` preserves subdirectory structure for WP-3.3 keys | ✅ Fixed in reconciliation | ⛔ |
| **LF-02** | `LocalFilesystemStorage._get_safe_path` path traversal (`../../etc/passwd`) rejected | ✅ | ⛔ |
| **LF-03** | `LocalFilesystemStorage.put_object` creates intermediate directories | ✅ Fixed in reconciliation | ⛔ |
| **S3-01** | `S3Storage.put_object` uploads via boto3 | ✅ | ⛔ |
| **S3-02** | `S3Storage.get_object` retrieves by object key | ✅ | ⛔ |
| **S3-03** | `S3Storage.generate_signed_url` returns presigned URL | ✅ | ⛔ |
| **S3-04** | boto3 import is lazy (module imports cleanly without boto3 installed) | ✅ Fixed in reconciliation | ⛔ |
| **S3-05** | `NoSuchKey` AND `404` both map to `EvidenceNotFoundError` | ✅ Fixed in reconciliation | ⛔ |
| **API-01** | `POST /events/{event_id}/evidence` accepts valid multipart, verifies hash, sets `AVAILABLE` | ✅ | ⛔ |
| **API-02** | `POST /events/{event_id}/evidence` oversized → HTTP 413 (not 500) | ✅ Fixed in reconciliation | ⛔ |
| **API-03** | `POST /events/{event_id}/evidence` hash mismatch → HTTP 400 | ✅ | ⛔ |
| **API-04** | `POST /events/{event_id}/evidence` event not found → HTTP 404 | ✅ | ⛔ |
| **API-05** | `POST /events/{event_id}/evidence` mTLS identity mismatch → HTTP 403 | ✅ | ⛔ |
| **API-06** | `POST /events/{event_id}/evidence` already AVAILABLE → idempotent 200 | ✅ | ⛔ |
| **API-07** | `GET /evidence-image` non-local provider → 307 signed URL redirect | ✅ | ⛔ |
| **API-08** | `GET /evidence-image` AVAILABLE but object missing → 404, status → MISSING | ✅ | ⛔ |
| **API-09** | `GET /evidence-image` not AVAILABLE → 404 with status in message | ✅ | ⛔ |
| **HASH-01** | Edge computes `SHA-256(binary)` before upload | ✅ `sync_client._upload` | ⛔ |
| **HASH-02** | Backend independently computes `SHA-256(received_bytes)` | ✅ `ingest_evidence` | ⛔ |
| **HASH-03** | `expected_hash == calculated_hash` enforced server-side | ✅ | ⛔ |
| **HASH-04** | `EvidencePackage` logical hash (Ed25519 chain) unchanged / separate from `content_hash` | ✅ `EvidencePackage.sha256` untouched | ⛔ |
| **SYNC-01** | Stage 1 (metadata POST) succeeds → event durable in DB | ✅ | ⛔ |
| **SYNC-02** | Stage 2 (binary POST) fails → event remains `QUEUED` on edge | ✅ `_mark` keeps status QUEUED | ⛔ |
| **SYNC-03** | Stage 1 idempotent on retry (duplicate event → "already exists") | ✅ `ingest_event` duplicate guard | ⛔ |
| **SYNC-04** | Stage 2 idempotent on retry (already AVAILABLE → early return) | ✅ | ⛔ |
| **SYNC-05** | Edge missing local file → queue cleared, backend storage_status reflects absence | ✅ warning logged, Stage 2 skipped | ⛔ |
| **MIG-01** | `--commit` flag required to write; default is dry-run | ✅ | ⛔ |
| **MIG-02** | Queries events with `storage_status IS NULL OR = 'CREATED'` | ✅ Fixed in reconciliation | ⛔ |
| **MIG-03** | Missing local file → `storage_status=MISSING`, loop continues | ✅ | ⛔ |
| **MIG-04** | Source files NOT deleted | ✅ No `os.remove` call | ⛔ |
| **MIG-05** | Existing `content_hash` compared before overwrite; mismatch → skip + log | ✅ Fixed in reconciliation | ⛔ |
| **MIG-06** | Idempotent: re-running skips already-AVAILABLE events | ✅ (AVAILABLE not in filter) | ⛔ |
| **ORM-01** | `Event.storage_provider`, `object_key`, `storage_status`, `content_hash`, `content_size`, `uploaded_at`, `failure_reason` present | ✅ `orm.py` lines 188–196 | ⛔ |
| **SCH-01** | `EventResponse` exposes all storage metadata fields | ✅ `schemas.py` lines 433–439 | ⛔ |
