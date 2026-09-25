# Phase 4 WP-3.4: Object Storage Security Review

## Scope

This document reviews the security of the WP-3.3 object storage implementation.
It is limited to what is actually implemented and configured. Claims that require
provider-level configuration that has not been verified are explicitly annotated.

---

## 1. Provider Abstraction

| Item | Status |
|:-----|:-------|
| Provider-agnostic `EvidenceStorageBackend` ABC | ✅ Implemented — `backend/services/evidence_storage.py` |
| `LocalFilesystemStorage` backend | ✅ Implemented |
| `S3Storage` backend (boto3) | ✅ Implemented |
| Provider selected at startup via `OBJECT_STORAGE_PROVIDER` | ✅ Implemented |
| Silent fallback from S3 to local in production | ❌ Not allowed — production startup validation rejects S3 without required credentials |

---

## 2. Bucket / Storage Access

### 2.1 Private Bucket

The application does not configure the bucket at the provider level.
Whether the bucket is private depends entirely on how the administrator
creates it at the object storage provider (AWS S3, MinIO, etc.).

> **ADMINISTRATOR REQUIREMENT**: The bucket MUST be created with:
> - Public access BLOCKED at the bucket level
> - No public-read ACL on individual objects
> - No static website hosting

The application itself never generates public URLs for objects.
All access is via pre-signed URLs (time-limited, authenticated) or
direct backend-mediated retrieval (RBAC gated).

### 2.2 No Frontend Credentials

The frontend receives pre-signed URLs from `GET /events/{event_id}/evidence-image`.
The frontend NEVER receives `OBJECT_STORAGE_ACCESS_KEY` or `OBJECT_STORAGE_SECRET_KEY`.
Credentials are stored only in backend environment variables.

### 2.3 No Public Bucket Listing

The application never calls `list_objects` on the bucket.
Disabling bucket listing must be enforced at the provider level.

---

## 3. Service Credentials and Least Privilege

### Recommended IAM Policy (AWS S3 example)

The service account used for `OBJECT_STORAGE_ACCESS_KEY` / `SECRET_KEY` should
have ONLY the following permissions on the evidence bucket:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:HeadObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::netraksh-evidence/*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::netraksh-evidence",
      "Condition": {
        "StringLike": {"s3:prefix": ["evidence/*"]}
      }
    }
  ]
}
```

The service account must NOT have:
- `s3:DeleteBucket`
- `s3:PutBucketPolicy`
- `s3:PutBucketAcl`
- `s3:PutBucketPublicAccessBlock`

---

## 4. TLS for Object Storage Communication

The `S3Storage` client connects to `OBJECT_STORAGE_ENDPOINT`.
boto3 uses HTTPS by default for AWS S3 endpoints.

For self-hosted MinIO or other S3-compatible stores:
- The endpoint MUST use `https://`
- The server certificate must be valid (boto3 verifies by default)
- Do NOT set `verify=False` in boto3 client configuration

The application code does NOT set `verify=False` anywhere in `S3Storage`.

---

## 5. Signed URL Authorization

### 5.1 RBAC Before URL Issuance

`GET /events/{event_id}/evidence-image` requires `require_any_role` dependency.
An unauthenticated request receives 401 before a signed URL is ever generated.

```
Request → require_any_role → event lookup → storage_status check →
    LocalFilesystem: stream bytes directly
    S3: generate_signed_url → 307 redirect
```

### 5.2 Signed URL TTL

Default TTL: **3600 seconds** (1 hour).

This is controlled by the `expires_in` parameter in `generate_signed_url()`.
The TTL is a balance between:
- Too short: broken URLs if network latency or client delay
- Too long: leaked URL remains valid longer

The TTL is NOT currently configurable via `settings`. This is a future hardening item.

### 5.3 Signed URL Scope

The signed URL grants access to exactly one object (one evidence file).
It does NOT grant access to:
- Other objects in the bucket
- Any metadata or listing
- Any write operations

---

## 6. Object Key Safety

Object keys follow a deterministic, safe format:

```
evidence/{camera_id}/{UTC-date}/{event_id}{ext}
```

Example: `evidence/cam-border-01/20260914/evt-abc-123.jpg.enc`

### Path Traversal Prevention

For `LocalFilesystemStorage`:
- `_get_safe_path()` uses `os.path.normpath` then containment check
- Traversal sequences (`../`) are detected and raise `PathTraversalError`
- Final path must start with `clips_dir + os.sep`

For `S3Storage`:
- Object keys are constructed by the backend from trusted values only (`camera_id`, `event.timestamp`, `event_id`)
- No client-provided path component is ever used directly as an object key

---

## 7. Upload Size Limits and Content-Type Validation

| Control | Value | Source |
|:--------|:------|:-------|
| Maximum upload size | 5 MiB (default) | `settings.MAX_UPLOAD_SIZE_BYTES` |
| Size check position | Before `try` block (correct — returns 413, not 500) | `backend/api/events.py::ingest_evidence` |
| Content-type forwarded to storage | `file.content_type or "application/octet-stream"` | `ingest_evidence` |
| Content-type enforcement | NOT enforced — any content_type accepted | Gap: future hardening |

> **Remaining gap**: The application does not enforce that uploaded evidence must be
> a specific MIME type (e.g., `image/jpeg` or `application/octet-stream`). A client
> could upload arbitrary binary content. The content_hash check ensures integrity,
> but not type conformance. Type enforcement is a future hardening item.

---

## 8. Binary Content Hash Verification

The backend independently computes `SHA-256(received_bytes)` and requires it to
match the `expected_hash` provided by the edge in the multipart upload.

```
Edge: SHA-256(binary) → sends as expected_hash
Backend: reads bytes → SHA-256(bytes) → calculated_hash
    if expected_hash != calculated_hash → 400 Bad Request
    storage_status = FAILED, failure_reason recorded
```

The backend NEVER trusts the client-provided hash without recomputing independently.

This hash (`content_hash`) is stored separately from the `EvidencePackage.sha256`
(the logical chain hash signed by Ed25519). They protect different things:

| Hash | Covers | Algorithm | Signed? |
|:-----|:-------|:---------|:--------|
| `EvidencePackage.sha256` | Event metadata fields (JSON) | SHA-256 | Yes — Ed25519 |
| `Event.content_hash` | Physical evidence binary bytes | SHA-256 | No — integrity check only |

---

## 9. Orphan Object Handling

An orphan object is an evidence binary in object storage for which no corresponding
`Event` record exists (or whose `Event` has been deleted).

**Current status**: No automated orphan detection or cleanup is implemented.

**Recommended future hardening**:
- Periodic reconciliation script: list all objects, verify each has a matching Event
- Orphaned objects should be moved to a quarantine prefix, not immediately deleted

---

## 10. Object Versioning

Object versioning is NOT enabled by default at the application level.
Whether object versions are retained depends on bucket configuration at the provider.

**Recommendation**: Enable S3 bucket versioning to allow recovery of accidentally
deleted evidence objects. See Scenario F in `docs/PHASE4_WP3_4_EDGE_COMPROMISE_MODEL.md`.

---

## 11. Server-Side Encryption (SSE)

The application stores AES-256-GCM encrypted evidence files (encrypted by the edge
device before transmission). The object storage provider receives already-encrypted bytes.

**Application-level encryption**: ✅ Evidence images are AES-256-GCM encrypted at the edge.

**Provider-managed SSE**: NOT CONFIGURED by default. This is an additional layer
that can be enabled at the bucket level:

| Provider | Configuration |
|:---------|:-------------|
| AWS S3 | Enable SSE-S3 (AES-256) or SSE-KMS: `Bucket → Properties → Default encryption` |
| MinIO | Enable server-side encryption at the MinIO server config: `MINIO_KMS_SECRET_KEY` or KES integration |

**NOT CLAIMED**:
- WORM / Object Lock: NOT CONFIGURED
- Legal Hold: NOT CONFIGURED
- Immutable storage: NOT CONFIGURED

These would require explicit provider-level configuration that has not been verified
in this deployment.

---

## 12. Summary of Controls

| Control | Status |
|:--------|:-------|
| Private bucket (no public access) | Administrator MUST configure — not app-enforced |
| No frontend credentials | ✅ |
| No public listing | Administrator MUST disable — not app-enforced |
| Least-privilege IAM | Administrator MUST configure — recommendation provided above |
| TLS for S3 communication | ✅ boto3 default; administrator must use HTTPS endpoint |
| Signed URL RBAC gate | ✅ require_any_role before URL issuance |
| Signed URL TTL (1h) | ✅ Hardcoded default |
| Object key path safety | ✅ Traversal guard in LocalFilesystem; deterministic construction for S3 |
| Upload size limit (5 MiB) | ✅ |
| Binary content hash verification | ✅ Backend recomputes independently |
| Application-level AES-256-GCM encryption | ✅ Evidence encrypted before upload |
| Provider SSE | NOT CONFIGURED — administrator action required |
| Object Lock / WORM | NOT IMPLEMENTED |
| Bucket versioning | NOT CONFIGURED — administrator action required |
| Orphan detection | NOT IMPLEMENTED |
| Content-type enforcement | NOT IMPLEMENTED |
