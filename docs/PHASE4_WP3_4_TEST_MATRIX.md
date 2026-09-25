# Phase 4 WP-3.4: Test Matrix

Status: **NOT EXECUTED — ENVIRONMENT BLOCKED**

Test file: [`tests/test_wp3_4_key_lifecycle.py`](file:///D:/SIH/netraksh/tests/test_wp3_4_key_lifecycle.py)

## Legend
- ✅ = Implementation verified in source code
- ⛔ = NOT EXECUTED — environment blocked

| ID | Test | Implementation | Execution |
|:---|:-----|:--------------|:----------|
| **T-01** | Deterministic kid: same public key always yields same kid matching WP-3.1 spec | ✅ `derive_kid_from_pem` mirrors packager + cameras API | ⛔ |
| **T-02** | Repeated backfill idempotency: second run reports ALREADY, no duplicate CameraKey | ✅ `_categorise_camera` returns ALREADY when key exists for same camera | ⛔ |
| **T-03** | Missing legacy key: camera with null `public_key_pem` reports MISSING, no crash | ✅ | ⛔ |
| **T-04** | Malformed legacy key: invalid PEM reports INVALID, no crash | ✅ `_categorise_camera` catches parse exception | ⛔ |
| **T-05** | Duplicate kid conflict: kid already mapped to different camera → CONFLICT | ✅ camera_id comparison in `_categorise_camera` | ⛔ |
| **T-06** | Duplicate kid same camera: kid mapped to same camera → ALREADY | ✅ | ⛔ |
| **T-07** | Existing CameraKey preservation: backfill never calls delete on existing records | ✅ ALREADY path returns immediately | ⛔ |
| **T-08** | Key rotation: new key upload → old ACTIVE key becomes RETIRED, new key is ACTIVE | ✅ `upload_public_key` loop marks differing keys RETIRED | ⛔ |
| **T-09** | Retired key historical verification: signature made with RETIRED key still verifies cryptographically | ✅ `verify_signature` does not reject RETIRED keys | ⛔ |
| **T-10** | Revoked key semantics: `sig_valid=True` AND `key_status='REVOKED'` are independently returned | ✅ `verify_signature` returns `(bool, str, key_status)` | ⛔ |
| **T-11** | Unknown kid: `verify_signature` with unregistered kid returns `UNKNOWN_KID` | ✅ exact lookup path returns `UNKNOWN_KID` when `first()` is None | ⛔ |
| **T-12** | Deleted historical key: missing CameraKey record returns `UNKNOWN_KID` (not 500) | ✅ same path as T-11 | ⛔ |
| **T-13** | Post-rotation signature isolation: key_A sig verifies with key_A, fails with key_B | ✅ Ed25519 cryptographic property | ⛔ |
| **T-14** | Object metadata preserves kid: `EvidencePackage` ORM and Schema have kid field | ✅ `orm.py:EvidencePackage.kid`, `schemas.py:EvidencePackage` | ⛔ |
| **T-15** | Object metadata preserves content_hash: `Event` ORM and `EventResponse` schema have content_hash | ✅ `orm.py:Event.content_hash`, `schemas.py:EventResponse.content_hash` | ⛔ |
| **T-16** | Signed URL RBAC: `evidence-image` route has RBAC dependency | ✅ `require_any_role` dependency present | ⛔ |
| **T-17** | Object storage credential validation: S3 provider with missing credentials raises at startup in production | ✅ `config.py::_validate_production_secrets` S3 check | ⛔ |
| **T-18** | Production secret validation: weak SECRET_KEY rejected at startup | ✅ `config.py::_validate_production_secrets` | ⛔ |
| **T-19** | Unknown kid fails closed: no fallback to legacy path when kid is present but unknown | ✅ exact lookup path returns `UNKNOWN_KID` without fallback | ⛔ |
| **T-20** | No key material in VerificationResponse: schema fields do not include any private/secret key fields | ✅ `VerificationResponse` schema inspection | ⛔ |

---

## Additional Manual Verification

The following items require runtime environment to verify:

| Item | What to Verify | Blocked |
|:-----|:--------------|:--------|
| Backfill script dry-run output | Run `python scripts/backfill_camera_keys.py` — no DB writes | ⛔ |
| Backfill script --commit | Run `python scripts/backfill_camera_keys.py --commit` — audit event written | ⛔ |
| KEY_REGISTERED audit event | Call `PUT /cameras/{id}/public-key`, check `audit_logs` table | ⛔ |
| KEY_RETIRED audit event | Call `PUT /cameras/{id}/public-key` with a different key | ⛔ |
| KEY_ROTATION_REQUESTED audit event | Same as KEY_RETIRED — both emitted in same request | ⛔ |
| KEY_ROTATION_FAILED audit event | Call `PUT /cameras/{id}/public-key` with invalid PEM | ⛔ |
| KEY_BACKFILL_COMPLETED audit event | Run backfill with `--commit` | ⛔ |
| Revoked key in verify endpoint | Set `CameraKey.status='REVOKED'`, call `POST /events/{id}/verify` | ⛔ |
| Legacy resolution (no kid) | Create event without kid, call verify — expect ACTIVE legacy key used | ⛔ |
| S3 path traversal rejection | Submit `object_key = "../../etc/passwd"` — expect `PathTraversalError` | ⛔ |
