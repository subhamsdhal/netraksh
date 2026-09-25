# Phase 4 WP-3.3: Object Storage & Evidence Lifecycle — Completion Report

## Status

| | |
|:---|:---|
| **Implementation** | **COMPLETE** |
| **Verification** | **NOT EXECUTED — ENVIRONMENT BLOCKED** |

---

## Reconciliation Defects Found and Fixed (2026-09-14)

Four defects were identified during the final reconciliation gate and corrected:

### DEFECT-1 — No production S3 configuration validation
**File**: `backend/config.py`
**Problem**: When `OBJECT_STORAGE_PROVIDER=s3`, the application would start successfully even if `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY`, or `OBJECT_STORAGE_SECRET_KEY` were absent. The first upload would then crash with an obscure boto3 `ClientError` rather than a clear startup failure.
**Fix**: Added an explicit S3 configuration check to `_validate_production_secrets()`. In `ENV=production` or `ENV=staging`, if S3 is selected but any required credential is absent, startup is refused with a descriptive error listing the missing variables.

### DEFECT-2 — `LocalFilesystemStorage` flattened subdirectory paths
**File**: `backend/services/evidence_storage.py`
**Problem**: `_get_safe_path` extracted only `os.path.basename(object_key)`, discarding all subdirectory structure. A WP-3.3 key like `evidence/cam-1/20240101/event-id.jpg.enc` would be written as `clips_dir/event-id.jpg.enc`, breaking deterministic key lookup on a local deployment.
**Fix**: Replaced basename-only extraction with `os.path.normpath` + containment check. The full subdirectory structure is now preserved under `clips_dir`. Intermediate directories are created with `os.makedirs(..., exist_ok=True)`. Legacy bare filenames (no slashes) behave identically to before.

### DEFECT-3 — `HTTPException(413)` swallowed by generic `except Exception` handler
**File**: `backend/api/events.py` — `ingest_evidence`
**Problem**: The file size check raised `HTTPException(status_code=413)` inside the `try` block. FastAPI `HTTPException`s are not caught by `except Exception`, but since `HTTPException` inherits from `Exception`, it *was* caught, and the handler then set `storage_status=FAILED` and re-raised a 500.
**Fix**: Moved the size read and size guard above the `try` block. An oversized upload now correctly returns 413 and sets `storage_status=FAILED` before re-raising.

### DEFECT-4 — Migration script missed events with `storage_status='CREATED'`
**File**: `scripts/migrate_evidence_to_object_storage.py`
**Problem**: The ORM sets `storage_status='CREATED'` as the column default. The migration script queried only `storage_status IS NULL`, which matches only pre-ORM-change rows. Any event inserted after the WP-3.3 model was deployed would silently be skipped.
**Fix**: The filter now includes `OR storage_status = 'CREATED'` using `sqlalchemy.or_`. Also added a `content_hash` consistency check: if a row already has a `content_hash`, the newly computed hash must match before the record is overwritten.

---

## Components and Source Locations

| Component | File | Status |
|:---|:---|:---|
| `boto3` dependency | `requirements.txt:42` | ✅ Declared |
| `python-multipart` dependency | `requirements.txt:34` | ✅ Declared |
| S3 config settings | `config.py:122–128` | ✅ Present |
| S3 production startup validation | `config.py:_validate_production_secrets` | ✅ Fixed |
| `EvidenceStorageBackend` ABC | `evidence_storage.py` | ✅ Present |
| `LocalFilesystemStorage` (path traversal + subdirs) | `evidence_storage.py` | ✅ Fixed |
| `S3Storage` (lazy boto3 import) | `evidence_storage.py` | ✅ Fixed |
| Event ORM storage fields | `orm.py:188–196` | ✅ Present |
| `EventResponse` storage fields | `schemas.py:433–439` | ✅ Present |
| `POST /events/{id}/evidence` (binary upload) | `api/events.py` | ✅ Fixed (413 bug) |
| `GET /events/{id}/evidence-image` (signed URL) | `api/events.py` | ✅ Present |
| Edge two-stage sync | `edge/sync/sync_client.py` | ✅ Present |
| Migration script | `scripts/migrate_evidence_to_object_storage.py` | ✅ Fixed (CREATED filter + hash guard) |

---

## Two-Stage Sync Durability Confirmation

| Property | Verified |
|:---|:---|
| Stage 1 (metadata) failure → event NOT queued in edge SQLite | ✅ `_mark` keeps status `QUEUED` on any Stage 1 failure |
| Stage 2 (binary) failure → event remains `QUEUED` on edge | ✅ `_upload` returns `(False, error)` → `_mark` keeps `QUEUED` |
| Stage 1 duplicate on retry → idempotent skip | ✅ `ingest_event` duplicate guard |
| Stage 2 duplicate on retry (already AVAILABLE) → early return | ✅ `if event.storage_status == "AVAILABLE": return` |
| Backend distinguishes metadata-available vs evidence-available | ✅ `storage_status` field: `CREATED/UPLOADING/AVAILABLE/FAILED/MISSING` |
| Event cannot appear AVAILABLE when evidence object is absent | ✅ `GET /evidence-image` rejects non-AVAILABLE status with 404 |

---

## Hash Separation Confirmation

| Hash | Location | Purpose |
|:---|:---|:---|
| `EvidencePackage.sha256` | `shared/schemas.py`, `orm.py:EvidencePackage` | Ed25519-signed logical chain hash — unchanged |
| `EvidencePackage.digital_signature` | Same | Ed25519 signature — unchanged |
| `Event.content_hash` | `orm.py:192` | SHA-256 of the physical binary transferred over the wire — separate |

The two hash concepts are stored in separate ORM models and computed independently. No WP-3.3 change modifies the logical evidence hash or its verification path.

---

## Pending (Environment Blocked)

- Alembic migration to add storage columns to existing `events` table
- Runtime execution of `scripts/migrate_evidence_to_object_storage.py`
- Execution of all test cases in `tests/matrix_wp3_3.md`
