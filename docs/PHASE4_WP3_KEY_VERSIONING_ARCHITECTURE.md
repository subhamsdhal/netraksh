# NETRAKSH — Phase 4 WP-3.1 Key Versioning Architecture

## Overview
Historically, `Camera.public_key_pem` stored a single Ed25519 key for each edge device, which meant that any key rotation would overwrite the solitary verification key, inadvertently invalidating historical evidence hashes. 
WP-3.1 solves this by introducing a new `CameraKey` registry (ORM model) and adding a `kid` (Key Identifier) metadata field to `EvidencePackage`.

## The Key Identifier (KID)
The `kid` serves as a globally deterministic reference to a specific keypair. 

### Derivation
```python
# Canonicalize public key bytes (DER SubjectPublicKeyInfo)
canonical_bytes = public_key.public_bytes(
    serialization.Encoding.DER,
    serialization.PublicFormat.SubjectPublicKeyInfo,
)
digest = hashlib.sha256(canonical_bytes).hexdigest().lower()
kid = f"ed25519-{digest[:32]}"
```
**Requirements:**
- Prefix is algorithm specific: `ed25519-`
- Uses lowercase hexadecimal SHA-256 slice (first 32 chars).
- Uses `SubjectPublicKeyInfo` (DER formatting), NOT arbitrary PEM, ensuring predictable structure.
- `kid` is strictly public metadata. It does not act as authentication, only as a registry lookup hint.

## Envelope Updates
The exact signed-envelope format preserves backward compatibility for legacy hashes:

**Legacy Envelope:**
```json
{
  "hash": "SHA-256(canonical_payload)",
  "signature": "Ed25519(hash)",
  "previous_hash": "..."
}
```
*Note: Legacy verification looks up all keys by `camera_id`.*

**Versioned Envelope:**
```json
{
  "hash": "SHA-256(canonical_payload)",
  "signature": "Ed25519(hash)",
  "kid": "ed25519-abc123def456...",
  "previous_hash": "..."
}
```
*Note: `kid` is appended AFTER the hash generation. The `get_signable_fields()` deterministic payload does NOT include `kid`. The `signature` is still generated strictly over the `hash`, but the Verifier mandates that the key specified by `kid` must be the exact key that verifies the signature.*

## Camera Key Registry
The backend uses a new ORM table, `camera_keys`:
- `kid` (String, Unique Index)
- `camera_id` (ForeignKey)
- `algorithm` (Default: "ed25519")
- `purpose` (Default: "EVIDENCE_SIGNING")
- `public_key_pem` (Text)
- `status` (ACTIVE / RETIRED / REVOKED)

The original `Camera.public_key_pem` column remains as a legacy fallback only and will eventually be phased out once backfilling is complete.

## Verification Pipeline
`verify_signature()` strictly enforces:
1. If `kid` is present, it looks up the exact `CameraKey`. If there is a mismatch with `camera_id` or an invalid `kid`, it is rejected.
2. If `kid` is absent, it retrieves all `CameraKey` instances for that camera (including the fallback `public_key_pem`) and attempts validation.
3. Both successful validations output a key status (`ACTIVE`, `RETIRED`, `REVOKED`), which cleanly decouples *cryptographic integrity* from *operational policy*.
