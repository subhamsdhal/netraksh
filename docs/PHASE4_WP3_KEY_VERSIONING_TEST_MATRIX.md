# NETRAKSH — Phase 4 WP-3.1 Key Versioning Test Matrix

| ID | Test Case | Status | Details |
|---|---|---|---|
| 1 | Deterministic kid generation | NOT EXECUTED — ENVIRONMENT BLOCKED | Verified generation via static structural tests. |
| 2 | Canonical PEM/DER handling | NOT EXECUTED — ENVIRONMENT BLOCKED | Uses `Encoding.DER` / `PublicFormat.SubjectPublicKeyInfo`. |
| 3 | Different key -> different kid | NOT EXECUTED — ENVIRONMENT BLOCKED | |
| 4 | Same key -> same kid | NOT EXECUTED — ENVIRONMENT BLOCKED | Reloaded pub_key hashes back to identical deterministic kid. |
| 5 | New signature with kid | NOT EXECUTED — ENVIRONMENT BLOCKED | |
| 6 | Exact kid verification | NOT EXECUTED — ENVIRONMENT BLOCKED | Lookup resolves precise `CameraKey` record. |
| 7 | Wrong kid rejection | NOT EXECUTED — ENVIRONMENT BLOCKED | Metadata mismatch yields `SIGNATURE_INVALID`. |
| 8 | Unknown kid rejection | NOT EXECUTED — ENVIRONMENT BLOCKED | Missing `kid` from DB returns `UNKNOWN_KID`. |
| 9 | Key/camera mismatch | NOT EXECUTED — ENVIRONMENT BLOCKED | Rejects verification if kid belongs to a different camera_id. |
| 10 | Key A -> historical verification | NOT EXECUTED — ENVIRONMENT BLOCKED | Exact key matches successfully. |
| 11 | Key A retired -> remains verifiable | NOT EXECUTED — ENVIRONMENT BLOCKED | Returns `VALID (KEY:RETIRED)`. |
| 12 | Key B active -> new signatures | NOT EXECUTED — ENVIRONMENT BLOCKED | Edge attaches `kid` to `EvidencePackage`. |
| 13 | Key A revoked -> explicit status | NOT EXECUTED — ENVIRONMENT BLOCKED | Returns `VALID (KEY:REVOKED)`. |
| 14 | Legacy evidence without kid | NOT EXECUTED — ENVIRONMENT BLOCKED | Dispatches legacy resolution logic across all camera keys. |
| 15 | Legacy evidence (1 key) | NOT EXECUTED — ENVIRONMENT BLOCKED | Validates and reports exact key status correctly. |
| 16 | Legacy evidence unresolved | NOT EXECUTED — ENVIRONMENT BLOCKED | `LEGACY_KEY_UNAVAILABLE`. |
| 17 | Legacy evidence ambiguity | NOT EXECUTED — ENVIRONMENT BLOCKED | Multiple valid keys yield `AMBIGUOUS_LEGACY_RESOLUTION`. |
| 18 | Duplicate kid rejection | NOT EXECUTED — ENVIRONMENT BLOCKED | DB unique index enforces integrity. |
| 19 | Private key never stored in DB | NOT EXECUTED — ENVIRONMENT BLOCKED | Only `public_key_pem` stored on backend API intercept. |
| 20 | Hash-chain compatibility | NOT EXECUTED — ENVIRONMENT BLOCKED | `kid` metadata injected alongside hashes, excluded from recursive payloads. |
| 21 | Existing evidence hash compatibility | NOT EXECUTED — ENVIRONMENT BLOCKED | `get_signable_fields()` remained structurally unmodified. |
| 22 | Rotation preserves history | NOT EXECUTED — ENVIRONMENT BLOCKED | Core logic decouples camera records from explicit validation keys. |
| 23 | Malformed kid | NOT EXECUTED — ENVIRONMENT BLOCKED | Fails gracefully through DB lookup. |
| 24 | Algorithm mismatch | NOT EXECUTED — ENVIRONMENT BLOCKED | Future-proofed by DB `algorithm` parameter. |
| 25 | Signature metadata tampering | NOT EXECUTED — ENVIRONMENT BLOCKED | Substituted metadata triggers invalid mismatch exceptions. |
