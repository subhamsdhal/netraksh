# Phase 4 WP-3.4: Edge Device Compromise Model

## Scope

This document analyses the threat model for a compromised NETRAKSH edge device.
It documents current controls, remaining gaps, and recovery procedures for each
attack scenario. It does NOT claim controls that are not implemented.

> **NOT IMPLEMENTED — explicitly retained per WP-3.4 directive:**
> - TPM / Secure Enclave: NOT IMPLEMENTED
> - SQLCipher offline queue encryption: BLOCKED (runtime unavailable)
> - HSM / KMS: NOT IMPLEMENTED

---

## A. Stolen Physical Edge Device

### Threat
Attacker has physical possession of the edge device (Raspberry Pi, NUC, embedded system).

### Current Controls

| Control | Implementation | File |
|:--------|:--------------|:-----|
| mTLS client certificate | Device must present a valid cert to communicate with backend | `edge/sync/sync_client.py`, `backend/security/auth.py` |
| Edge identity revocation | `EdgeIdentity.status = REVOKED` prevents further sync | `backend/security/auth.py::get_edge_identity()` |
| Backend rejects revoked identity | HTTP 403 on every endpoint | `backend/security/auth.py:238-240` |
| Evidence is encrypted at rest | AES-256-GCM with per-camera key | `edge/evidence/packager.py::EvidenceEncryptor` |

### Remaining Gaps

- **Offline queue plaintext**: The SQLite sync queue at `edge/data/sync_queue.db` is not encrypted. An attacker with the device can read all queued event JSON (metadata, detection results). Evidence binaries themselves are AES-256-GCM encrypted separately.
- **Private signing key on filesystem**: `edge/data/keys/signing_private.pem` is stored unprotected. An attacker can extract it and forge new evidence packages.
- **Private TLS key on filesystem**: `certs/edge/edge.key` is stored unprotected. An attacker can impersonate the edge until the certificate is revoked.

### Mitigation

1. Revoke the `EdgeIdentity` in the backend database immediately upon discovery.
2. Revoke the mTLS certificate (update CA CRL or issue new CA-signed denial).
3. Set `CameraKey.status = "REVOKED"` for any keys associated with this device.
4. Generate new Ed25519 keypair and new mTLS certificate for the replacement device.
5. Audit all evidence synced from this device after the estimated time of theft.

### Recovery

- Historical evidence signed by the stolen key: verifiable (public key retained in CameraKey with status REVOKED). The signature remains cryptographically valid; the key_status = REVOKED is a separate operational judgment.
- Future evidence: new device, new keypair, new certificate.

---

## B. Copied Filesystem (Disk Image Theft)

### Threat
Attacker creates a forensic disk image of the edge device without physical removal (e.g., brief physical access, compromised remote shell).

### Current Controls
Same as Scenario A (all keys, queue, and encrypted evidence binaries are on the filesystem).

### Remaining Gaps
- All of Scenario A's gaps apply.
- Additionally: attacker has a static snapshot and can analyse evidence at leisure, even if live connectivity is revoked.

### Mitigation
- Same as Scenario A plus:
- Rotate the signing keypair immediately.
- File incident report documenting the estimated window of exposure.

### Recovery
Same as Scenario A.

---

## C. Stolen mTLS Private Key (Credential Extraction)

### Threat
Attacker obtains `edge.key` without necessarily having the device (e.g., extracted via malware on a connected laptop, RTSP stream capture machine, etc.).

### Current Controls

| Control | Status |
|:--------|:-------|
| mTLS certificate required for edge endpoints | Implemented |
| EdgeIdentity revocation | Implemented |
| Short-lived tokens | NOT IMPLEMENTED — mTLS cert has a fixed lifetime |

### Remaining Gaps
- The mTLS private key grants the attacker the ability to impersonate the edge device to the backend for the full certificate validity period until revocation is applied.
- Certificate Revocation List (CRL) / OCSP: NOT IMPLEMENTED. Revocation is done by setting `EdgeIdentity.status = REVOKED` in the backend database, which is checked at request time.

### Mitigation
1. Set `EdgeIdentity.status = REVOKED` immediately — backend will return 403 on all subsequent requests.
2. Provision a new certificate for the legitimate device.
3. Audit evidence ingested since estimated key exfiltration time.

### Recovery
The legitimate edge device must be reprovisioned with a new certificate signed by the CA.

---

## D. Compromised Running Process

### Threat
Attacker achieves remote code execution on the edge process (e.g., via vulnerability in the camera stream parser, RTSP library, or OS).

### Current Controls

| Control | Status |
|:--------|:-------|
| Evidence signing at creation time | Implemented — signature is on already-packed JSON |
| Audit trail at backend | Backend records all sync events |
| mTLS for sync | Backend validates certificate per request |

### Remaining Gaps
- A compromised process has access to the Ed25519 private key in memory.
- A compromised process can inject fake events into the local sync queue.
- Injected events will be signed with the real private key and will pass cryptographic verification at the backend.
- The chain continuity check (sequence_number + previous_hash) would detect a gap, but not injected events inserted in-sequence.

### Mitigation
- Process isolation (separate user, restricted filesystem permissions): RECOMMENDED, not enforced by this application.
- TPM-protected private key: NOT IMPLEMENTED.
- Intrusion detection on the edge host: out of scope for this application.

### Recovery
1. Revoke EdgeIdentity + signing key.
2. Review all events from the device in the window of compromise.
3. Flag affected evidence in the audit trail.

---

## E. Database Credential Theft (Backend PostgreSQL)

### Threat
Attacker obtains `DATABASE_URL` credentials (backend PostgreSQL access).

### Current Controls

| Control | Status |
|:--------|:-------|
| Evidence images not in PostgreSQL | Images stored in object storage or filesystem separately |
| Passwords bcrypt-hashed | `backend/security/auth.py::hash_password()` |
| JWT secret not in DB | Stored only in environment variable |
| Evidence encryption key stored wrapped | `Camera.evidence_key_wrapped` — never stored in plaintext |

### Remaining Gaps
- Full access to all event metadata, alert records, user records (bcrypt-hashed passwords), audit logs, CameraKey registry (public keys — not secret).
- `Camera.evidence_key_wrapped` is stored in PostgreSQL. The wrapping key is derived from `settings.EVIDENCE_ENCRYPTION_KEY`. If that env var is also obtained, evidence decryption is possible.
- Evidence signing public keys are in PostgreSQL — not a secret, but confirms which cameras are active.

### Mitigation
1. Rotate `DATABASE_URL` credentials immediately.
2. Rotate `EVIDENCE_ENCRYPTION_KEY` and re-wrap all stored evidence keys.
3. Rotate `SECRET_KEY` (JWT) to invalidate all active sessions.
4. Audit logs must be exported to an independent system — DB access does not automatically give audit log integrity.
5. Enable PostgreSQL row-level security and audit logging at the DB layer.

### Recovery
- User passwords: cannot be recovered (bcrypt hash is one-way). Users must reset passwords.
- Evidence data: if `EVIDENCE_ENCRYPTION_KEY` was not obtained, evidence files remain encrypted and inaccessible.

---

## F. Object Storage Credential Theft

### Threat
Attacker obtains `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY`.

### Current Controls

| Control | Status |
|:--------|:-------|
| Credentials stored only in env vars | Not committed to source, not in DB |
| Signed URLs are short-lived | Default TTL: 3600 seconds |
| Evidence images are AES-256-GCM encrypted | Even if downloaded, decryption requires the separate `EVIDENCE_ENCRYPTION_KEY` |
| No public bucket listing | Must be enforced at provider level (not app-enforced) |

### Remaining Gaps
- An attacker with object storage credentials can:
  - List all objects (if bucket listing is not disabled at provider)
  - Download all evidence binaries (encrypted, but readable with the correct decryption key)
  - Delete evidence objects (no Object Lock / WORM — NOT IMPLEMENTED)
  - Upload malicious objects (if write access is included in the leaked credential)
- WORM / Object Lock: NOT IMPLEMENTED
- Provider-managed encryption (SSE-S3, SSE-KMS): NOT CONFIGURED BY DEFAULT — see `docs/PHASE4_WP3_4_OBJECT_STORAGE_SECURITY.md`

### Mitigation
1. Rotate `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` immediately.
2. Review object storage access logs for unauthorized access.
3. Apply least-privilege IAM policy: separate read and write credentials.
4. Enable bucket versioning to detect/recover deleted objects.

### Recovery
- If evidence was deleted and no versioning: data loss. Enable bucket versioning before this happens.
- If evidence was accessed only: rotate credentials, audit access logs.

---

## G. Evidence Signing Key Compromise

### Threat
Attacker obtains the Ed25519 private signing key (`edge/data/keys/signing_private.pem`).

### Current Controls

| Control | Status |
|:--------|:-------|
| Private key never transmitted to backend | Only public key PEM uploaded |
| kid derivation from public key only | Private key not used to derive kid |
| Backend verifies signatures with public key | Public key is what is stored in CameraKey |

### Remaining Gaps
- Attacker can sign arbitrary evidence packages that will pass cryptographic verification.
- There is no mechanism to distinguish legitimate evidence from adversary-forged evidence signed with the same key.
- Chain continuity (sequence_number + previous_hash) provides some protection: forged events injected out of sequence will break the chain. In-sequence injection is still possible if the attacker has live process access.

### Mitigation
1. Revoke the key: `CameraKey.status = "REVOKED"`.
2. Rotate: generate new keypair, upload new public key via `PUT /cameras/{id}/public-key`.
3. Old evidence (signed with the now-REVOKED key): signature_valid=True, key_status=REVOKED — operationally flagged.
4. Audit all evidence from the window of potential compromise.

### Recovery
- Generate new Ed25519 keypair on the edge device.
- Upload new public key to backend.
- Old public key retained as REVOKED in CameraKey for historical forensic use.
- Do NOT claim recovery of the private key — it cannot be recovered; it must be replaced.
