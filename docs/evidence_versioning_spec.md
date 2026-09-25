# Evidence Versioning and Backward Compatibility Specification
Phase 8.3 Design Specification (Reference only - NOT PRODUCTION)

## A. Terminology
*   **Envelope**: The transport and storage structure of the EvidencePackage.
*   **Signable Payload**: The exact canonical bytes over which the hash and signature are computed.
*   **KID**: Key Identifier prefix mapping to the public key and signature algorithm.
*   **Crypto Profile**: A strict mapping of hashing, canonicalization, and signature algorithms to a version string.

## B. Version Identifiers
*   `schema_version` (String, e.g., "1.0"): Indicates the presence, types, and semantics of business logic fields in the payload.
*   `crypto_version` (String, e.g., "crypto-v1"): Indicates the exact rules for canonical serialization, hashing, and encryption wrappers.

## C. Legacy Profile Definition
`legacy-v0` MUST refer to evidence lacking explicit version tags.
*   **Hash**: SHA-256
*   **Canonicalization**: JSON dict, sort_keys=True, ensure_ascii=True, mapping None to empty string `""` across exactly 11 hardcoded fields.
*   **Signature**: Ed25519 over UTF-8 hex-encoded string of the hash.

## D. Future EvidencePackage Envelope
The future envelope SHOULD separate identity, metadata, proofs, and event data:
```json
{
  "schema_version": "1.0",
  "crypto_version": "crypto-v1",
  "event_id": "...",
  "camera_id": "...",
  "timestamp": "...",
  "zone_id": "...",
  "detection_class": "...",
  "confidence": 0.99,
  "scene_condition": "...",
  "camera_health_state": "...",
  "decision_state": "...",
  "evidence_clip_ref": "...",
  "previous_hash": "...",
  "sequence_number": 42,
  "hash": "...",
  "signature": "...",
  "kid": "..."
}
```

## E. Canonicalization Contract
The canonical payload MUST consist of all properties EXCEPT `hash`, `signature`, and `kid`, AND MUST explicitly EXCLUDE `sequence_number`.
The payload MUST be serialized to JSON with `sort_keys=True`, `ensure_ascii=True`, without spaces around separators.
Strings MUST be UTF-8 encoded.

> [!NOTE]
> **Design Note:** `previous_hash` cryptographically binds the record to its predecessor in the evidence chain. `sequence_number` records chain-store position but is outside the current cryptographic contract because it is assigned after hashing/signing. Including `sequence_number` in the cryptographic contract would require a separate architectural redesign (moving sequence assignment before hashing) and is explicitly OUT OF SCOPE for Phase 8.4.

## F. Signable Field Rules
Version metadata (`schema_version`, `crypto_version`) MUST be inside the signed payload.

## G. Version Metadata Rules
*   `schema_version` MUST be immutable.
*   `crypto_version` MUST be immutable.
*   Both MUST be hash-bound.

## H. Algorithm Registry / Profile Rules
A central registry SHOULD maintain profiles linking `crypto_version` to specific hash (e.g., SHA-256), signature, and serialization algorithms. Profiles MUST be append-only and immutable once active.

## I. Key / KID Rules
*   KID MUST NOT be part of the signable payload.
*   KIDs MUST remain globally unique and immutable.
*   Camera keys MAY rotate, but historical verification MUST lookup the key strictly by KID.

## J. Chain Compatibility Rules
The `previous_hash` MUST be strictly preserved as part of the signable payload to maintain hash-chain continuity. A chain MAY interleave legacy and versioned evidence as long as `previous_hash` matches identically.

## K. Legacy Verification Rules
Legacy evidence (missing version fields) MUST fall back to `legacy-v0`.
The verifier MUST reconstruct the legacy 11-field dict exactly as implemented in Phase 7.

## L. Unsupported Version Rules
Any envelope containing a `crypto_version` not present or marked `UNSUPPORTED` in the verifier's registry MUST be rejected (fail closed).

## M. Verifier State Machine
1.  Parse envelope. Extract `schema_version`, `crypto_version`.
2.  If missing -> profile = `legacy-v0`. Else profile = `crypto_version`.
3.  If profile unsupported/unknown -> **UNSUPPORTED**.
4.  Canonicalize according to profile.
5.  If hash mismatch -> **REJECT**.
6.  Lookup `kid` in key registry. If missing -> **UNVERIFIABLE**.
7.  Verify signature. If invalid -> **REJECT**.
8.  Return **ACCEPT**.

## N. Migration Rules
Legacy evidence MUST NOT be mutated to add version fields. It MUST remain in `legacy-v0` format to guarantee the original cryptographic proof remains intact and self-verifying.

## O. Compatibility Matrix
*   Current Code -> Legacy Evidence: ACCEPT
*   Future Code -> Legacy Evidence: ACCEPT (via fallback)
*   Future Code -> Future Evidence: ACCEPT
*   Current Code -> Future Evidence: REJECT (Hash mismatch due to new fields)

## P. Security Considerations
*   **Downgrade Attacks**: Prevented. Removing version fields forces fallback to `legacy-v0`, which computes hash over 11 hardcoded fields, leading to a hash mismatch on versioned data.
*   **Schema Tampering**: Prevented. `schema_version` is hash-bound.

## Q. Normative Implementation Requirements
Any implementation (Rust, Go, Java) MUST exactly reproduce Python's JSON float representation (e.g., `0.9`) and `ensure_ascii` escaping (`\uXXXX`) to achieve hash reproducibility.
