# Phase 4 WP-3.4: Key Lifecycle Architecture

## Overview

This document describes the complete lifecycle of all cryptographic keys used in NETRAKSH, covering registration, rotation, retirement, revocation, and forensic recovery.

---

## Key Types

| Key | Algorithm | Location | Purpose |
|:----|:----------|:---------|:--------|
| Evidence Signing Key | Ed25519 | Edge filesystem (PEM) | Signs EvidencePackage hash-chain records |
| Evidence Encryption Key | AES-256-GCM | Edge memory / backend (wrapped) | Encrypts evidence images at rest |
| JWT Signing Secret | HMAC-SHA256 | Backend environment variable | Signs access tokens |
| mTLS Client Certificate | X.509 / ECDSA or RSA | Edge TLS keystore | Authenticates edge to backend |
| mTLS CA Certificate | X.509 | Backend `certs/ca/ca.crt` | Validates edge client certificates |

---

## 1. Evidence Signing Key Lifecycle

### 1.1 Key Identifier (kid) Derivation

Per WP-3.1, the Key ID is derived deterministically from the public key alone:

```
canonical_bytes = DER SubjectPublicKeyInfo encoding of Ed25519 public key
digest          = SHA-256(canonical_bytes)
kid             = "ed25519-" + lowercase(hex(digest))[:32]
```

**Properties:**
- kid is public metadata — it is embedded in every EvidencePackage
- kid is NOT a secret and must never be treated as one
- kid is NOT an authentication credential
- kid is NEVER derived from the private key
- The same public key always produces the same kid (deterministic)
- Different public keys always produce different kids (collision-resistant)

**Implementation locations:**
- Edge: [`edge/evidence/packager.py::EdgeKeyManager._derive_kid()`](file:///D:/SIH/netraksh/edge/evidence/packager.py#L69-L79)
- Backend upload: [`backend/api/cameras.py::upload_public_key()`](file:///D:/SIH/netraksh/backend/api/cameras.py)
- Backfill: [`scripts/backfill_camera_keys.py::derive_kid()`](file:///D:/SIH/netraksh/scripts/backfill_camera_keys.py)

### 1.2 Key Registration (First Upload)

1. Admin calls `PUT /cameras/{camera_id}/public-key` with `public_key_pem`
2. Backend parses PEM → derives kid
3. No existing ACTIVE key → new `CameraKey` created with `status=ACTIVE`
4. `Camera.public_key_pem` is updated (backward-compatibility retained)
5. Audit event: `KEY_REGISTERED` (camera_id, kid — no key material)

### 1.3 Key Rotation

Triggered by a second call to `PUT /cameras/{camera_id}/public-key` with a **different** key.

```
Old ACTIVE key (old_kid)
        ↓
status = RETIRED  ←  audit: KEY_RETIRED
        
New key (new_kid)
        ↓
status = ACTIVE   ←  audit: KEY_ROTATION_REQUESTED
```

**Invariants:**
- `RETIRED` keys are NEVER deleted from `CameraKey`
- Historical evidence signed with `old_kid` remains verifiable via `old_kid → RETIRED key → public key`
- `Camera.public_key_pem` is updated to new key (backward compat)
- Re-uploading the same key is idempotent (no RETIRED transition, no new record)

### 1.4 Key Revocation

Revocation is a manual administrative action, distinct from rotation.

```
PUT /cameras/{camera_id}/public-key  (rotation)    ← ordinary lifecycle
Manual DB update: CameraKey.status = "REVOKED"     ← administrative action
```

> **KEY STATUS vs CRYPTOGRAPHIC VALIDITY are independent concepts.**
>
> | State | Signature Valid? | Operationally Trusted? |
> |:------|:----------------|:----------------------|
> | ACTIVE | Yes (if properly signed) | Yes |
> | RETIRED | Yes (if properly signed) | Yes — for historical evidence |
> | REVOKED | Yes (if properly signed) | No — operationally untrusted |
>
> The verification service returns both independently:
> `verify_signature()` → `(sig_valid: bool, message: str, key_status: Optional[str])`
>
> A `VerificationResponse` with `signature_valid=True` and `key_status="REVOKED"` means:
> - The evidence was cryptographically authentic when it was created
> - The signing key has since been declared untrusted
> These are separable facts for forensic and legal purposes.

### 1.5 Key Expiry

`CameraKey.expires_at` is stored but not automatically enforced by the application. Background expiry enforcement (setting status to `EXPIRED`) is a future operational concern.

---

## 2. Legacy Key Backfill (WP-3.4)

### Purpose

Cameras registered before WP-3.1 stored their public key only in `Camera.public_key_pem`. The `CameraKey` registry did not exist. The backfill script migrates these keys into the registry.

### Script

[`scripts/backfill_camera_keys.py`](file:///D:/SIH/netraksh/scripts/backfill_camera_keys.py)

### Usage

```bash
# Audit without writing (safe — dry-run default):
python scripts/backfill_camera_keys.py

# Commit migration:
python scripts/backfill_camera_keys.py --commit

# Limit to a single camera:
python scripts/backfill_camera_keys.py --camera-id <camera_id> --commit
```

### Outcome Categories

| Category | Meaning |
|:---------|:--------|
| `ELIGIBLE` | Has `public_key_pem`, no `CameraKey` record yet → will be migrated |
| `ALREADY` | Has a matching `CameraKey` record → skipped (idempotent) |
| `INVALID` | `public_key_pem` present but unparseable → manual investigation required |
| `CONFLICT` | kid derived from this key already mapped to a different camera → manual investigation |
| `MISSING` | `Camera.public_key_pem` is NULL or empty → no key to migrate |

### Invariants

- `Camera.public_key_pem` is NEVER deleted or modified
- Existing valid `CameraKey` records are NEVER overwritten
- Migrated keys receive `status=ACTIVE`
- Emit `KEY_BACKFILL_COMPLETED` audit event on `--commit`

---

## 3. Key Resolution During Verification

[`backend/services/verification.py::verify_signature()`](file:///D:/SIH/netraksh/backend/services/verification.py)

```
EvidencePackage.kid present?
    YES → exact lookup: CameraKey WHERE kid = evidence.kid
            → not found: UNKNOWN_KID (fail closed)
            → camera_id mismatch: KEY_CAMERA_MISMATCH (fail closed)
            → found, any status: attempt cryptographic verification
    NO  → legacy lookup: all CameraKey WHERE camera_id = evidence.camera_id
            → none found: fallback to Camera.public_key_pem
            → none at all: LEGACY_KEY_UNAVAILABLE (fail closed)
```

> RETIRED and REVOKED keys are still used for cryptographic verification.
> The key_status is returned in the response so callers can distinguish
> "signature valid with revoked key" from "signature valid with active key".

---

## 4. Key Recovery Procedures

See [docs/PHASE4_WP3_4_SECRET_ROTATION.md](file:///D:/SIH/netraksh/docs/PHASE4_WP3_4_SECRET_ROTATION.md) for full playbooks.

| Scenario | Recovery Path |
|:---------|:-------------|
| Active signing key lost (private key file deleted) | Generate new keypair, upload via `PUT /cameras/{id}/public-key`, old evidence no longer signable but historical evidence remains verifiable via retained public key |
| Retired signing key needed for forensic verification | Retrieve from `CameraKey` table (RETIRED status, public key PEM retained) |
| Signing key compromised | Revoke in CameraKey, rotate, investigate evidence signed in the window |
| Edge device stolen | Revoke edge identity + certificate, rotate all keys on device |
| CameraKey record accidentally deleted | Historical evidence returns UNKNOWN_KID — restore from backup |

> **Historical verification depends on the retained PUBLIC key, not the private key.**
> Private key loss does not prevent verification of already-signed evidence.
> Private key loss only prevents signing of NEW evidence until rotated.
