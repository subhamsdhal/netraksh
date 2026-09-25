# Phase 4 WP-3.4: Secret Rotation Playbook

## Overview

This document covers rotation procedures for every secret in the NETRAKSH system.

> **NOT IMPLEMENTED — explicitly retained:**
> - Centralized Vault / KMS: NOT IMPLEMENTED
> - Automatic rotation: NOT IMPLEMENTED
> - HSM-backed key material: NOT IMPLEMENTED

All secrets are currently stored as environment variables loaded at startup via
`backend/config.py` (pydantic-settings / `.env` file). Rotation requires
restarting the backend service after updating the environment.

---

## Secret Inventory

| Secret | Source | Current Storage | Rotation Impact |
|:-------|:-------|:----------------|:----------------|
| `SECRET_KEY` (JWT) | `openssl rand -hex 32` | `.env` / env var | All active sessions invalidated |
| `DATABASE_URL` (PostgreSQL credentials) | DB admin | `.env` / env var | Reconnect pool on restart |
| `OBJECT_STORAGE_ACCESS_KEY` | Object storage provider | `.env` / env var | Existing signed URLs remain valid until TTL |
| `OBJECT_STORAGE_SECRET_KEY` | Object storage provider | `.env` / env var | Must rotate with ACCESS_KEY |
| `EVIDENCE_ENCRYPTION_KEY` | `openssl rand -hex 32` | `.env` / env var | Re-wrap all `Camera.evidence_key_wrapped` values |
| `ADMIN_PASSWORD` | Admin | `.env` / env var | Only affects future logins |
| `INITIAL_OPERATOR_PASSWORD` | Admin | `.env` / env var | Only affects future logins |
| `INITIAL_AUDITOR_PASSWORD` | Admin | `.env` / env var | Only affects future logins |
| Edge TLS private key | `edge/certs/edge.key` | Edge filesystem | Revoke old cert, provision new cert |
| Ed25519 signing private key | `edge/data/keys/signing_private.pem` | Edge filesystem | Upload new public key, old key RETIRED |
| Edge AES-256-GCM evidence key | Edge memory / `Camera.evidence_key_wrapped` | Wrapped in PostgreSQL | Upload new key, re-encrypt evidence |

---

## 1. JWT Secret Rotation

### Impact
All currently valid JWT access tokens are immediately invalidated.
All active user sessions will receive 401 and must re-login.

### Procedure
```bash
# 1. Generate a new secret
NEW_SECRET=$(openssl rand -hex 32)

# 2. Update .env (or the environment/Render dashboard)
SECRET_KEY=<new_secret>

# 3. Restart the backend
# Render: re-deploy or trigger a restart
# Local: kill and restart uvicorn

# 4. All users must re-login
```

### Does NOT affect
- Historical evidence signatures (Ed25519, separate key)
- Evidence encryption (AES-256-GCM, separate key)
- Edge sync (mTLS certificate, separate credential)

---

## 2. Database Credential Rotation

### Impact
Existing SQLAlchemy connection pool will fail. Backend restart required.

### Procedure
```bash
# 1. Create a new PostgreSQL user/password via psql or your DB admin panel
# (Keep old user active until backend restarts successfully on new creds)

# 2. Update .env
DATABASE_URL=postgresql://new_user:new_password@host:5432/netraksh

# 3. Restart backend
# Verify startup succeeds and DB migration state is intact (alembic current)

# 4. Remove old PostgreSQL user/role
```

### Does NOT affect
- JWT sessions (different secret)
- Object storage (different credential)
- Evidence signatures (Ed25519, different key)

### Historical Evidence
No evidence data is stored in PostgreSQL directly (images are in object storage / filesystem). Rotating DB credentials does not affect evidence retrieval once the backend reconnects.

---

## 3. Object Storage Credential Rotation

### Impact
- New credentials take effect immediately after backend restart.
- Existing pre-signed URLs remain valid until their TTL (default 3600 seconds).
- Do NOT revoke old credentials at the provider until the TTL window has elapsed, or active users will receive broken URLs.

### Procedure
```bash
# 1. At the object storage provider, create a new access key pair.
# (Keep old key active — see TTL window above)

# 2. Update .env
OBJECT_STORAGE_ACCESS_KEY=<new_access_key>
OBJECT_STORAGE_SECRET_KEY=<new_secret_key>

# 3. Restart backend

# 4. After TTL window (3600s default), revoke old key at provider

# 5. Audit object access logs for any access with old key after revocation
```

### Does NOT affect
- Evidence signing (Ed25519, edge filesystem)
- Evidence encryption (AES-256-GCM — evidence files remain valid)
- JWT sessions (different secret)

---

## 4. Edge Certificate (mTLS) Rotation

### Impact
- Until the new certificate is provisioned on the edge device, sync will fail.
- Old certificate must be revoked in `EdgeIdentity` table after new cert is operational.

### Procedure
```bash
# 1. Generate a new CSR on the edge device
openssl req -new -key edge.key -out edge_new.csr

# 2. Sign the new certificate with the CA
openssl x509 -req -in edge_new.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out edge_new.crt -days 365

# 3. Copy new cert to edge device
# Replace edge/certs/edge.crt with edge_new.crt

# 4. Register the new certificate in EdgeIdentity:
#    Either via the backend admin panel or directly in the DB
#    (backend needs an EdgeIdentity endpoint — currently manual DB operation)

# 5. Restart the edge sync client

# 6. Verify successful sync with new certificate

# 7. Revoke old EdgeIdentity:
#    UPDATE edge_identities SET status='REVOKED', revoked_at=NOW()
#    WHERE certificate_fingerprint = '<old_fingerprint>';
```

### Does NOT affect
- Evidence signing keypair (Ed25519, separate key files)
- Historical evidence (already synced before rotation)
- Offline queue (continues to buffer — syncs when new cert is operational)

---

## 5. Evidence Signing Key (Ed25519) Rotation

### Impact
- Old evidence (signed with previous key) remains verifiable: old kid → RETIRED CameraKey → public key.
- New evidence will be signed with the new key.
- Gap in signing capability: period between old key removal and new key upload.

### Procedure
```bash
# 1. On the edge device — the key manager auto-generates if the file doesn't exist,
#    or manually:
rm edge/data/keys/signing_private.pem
rm edge/data/keys/signing_public.pem
# On next edge startup, a new keypair will be generated automatically.

# 2. Restart the edge device (or the EdgeKeyManager will detect the missing file)

# 3. Extract the new public key:
cat edge/data/keys/signing_public.pem

# 4. Upload new public key to backend:
curl -X PUT https://<backend>/cameras/<camera_id>/public-key \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"public_key_pem": "<new_public_key_pem>"}'

# Backend actions (automatic):
#   - Derives new_kid from new public key
#   - Sets old ACTIVE key to RETIRED (KEY_RETIRED audit event)
#   - Sets new key to ACTIVE (KEY_ROTATION_REQUESTED audit event)
```

### Historical Evidence After Rotation
```
Historical event → EvidencePackage.kid = old_kid
    ↓
verify_signature() → lookup CameraKey WHERE kid = old_kid
    ↓
Found: status = RETIRED, public_key_pem = <old public key>
    ↓
Cryptographic verification: VALID
key_status returned: RETIRED
```
Historical evidence remains fully verifiable. `RETIRED` status is informational — it does not invalidate the signature.

### Does NOT Affect
- mTLS certificates (different key material)
- Evidence encryption key (AES-256-GCM, different key)
- JWT sessions (different secret)

---

## 6. Evidence Encryption Key Rotation

The AES-256-GCM evidence encryption key is the most complex rotation because
it requires re-encrypting all previously encrypted evidence images.

> **WARNING**: This rotation modifies evidence files. Evidence byte-for-byte
> integrity (content_hash) will change after re-encryption. The original
> cryptographic hash of evidence encrypted with the old key will no longer
> match the stored content_hash if the file is re-encrypted.
>
> **RECOMMENDED APPROACH**: Do NOT re-encrypt historical evidence. Instead:
> - Retain the old wrapped key in a secure archive.
> - Use a versioned evidence key scheme (future hardening).
> - For new evidence, configure the new key.

### Procedure (if re-encryption is required)
```bash
# 1. Generate a new AES-256 key on the edge device:
#    edge/evidence/packager.py::EvidenceEncryptor generates the key at startup
#    if evidence_key.bin does not exist, or:
python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"

# 2. Upload new key to backend (this wraps it before storage):
python scripts/upload_evidence_key.py --camera-id <id> --key-b64 <base64_key>

# 3. Re-encrypt existing evidence images with the new key.
#    CAUTION: No automated script exists for this. Manual re-encryption
#    requires decrypting with the old key and encrypting with the new key.
#    The content_hash values in the database must be recomputed after.

# 4. Retain old wrapped key in a secure offline archive.
```

---

## Rotation Safety Rules

The following rules apply to ALL rotation procedures:

1. **Historical evidence must not be invalidated**: rotating signing keys uses RETIRED status — evidence remains verifiable.
2. **Offline queue must not be discarded**: rotation must not cause edge sync queue items to be lost or corrupted.
3. **Active edge nodes must reconnect**: certificate rotation requires graceful reconnection, not forced disconnection.
4. **No dry-run for credential rotation**: rotation is inherently destructive — plan maintenance window.
5. **Audit log every rotation**: all key events are emitted to `AuditLog` via `audit()`.
6. **Never log secret values**: audit detail fields contain only kid / fingerprint / camera_id — never key bytes.
