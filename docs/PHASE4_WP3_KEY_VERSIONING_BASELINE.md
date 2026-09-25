# NETRAKSH — Phase 4 WP-3 Key Versioning Baseline

## Forensic Audit of Current Cryptographic Operations

Before introducing Key Identifiers (`kid`) and key versioning, this is the current state of cryptographic signing and verification within the system.

### 1. Current Key Model
- **Generation:** `EdgeKeyManager` (`edge/evidence/packager.py`) generates an Ed25519 keypair on first run.
- **Storage (Edge):** Private and public keys are saved to the edge filesystem as PEM files.
- **Storage (Backend):** The backend stores exactly **one** public key per camera in the `cameras` table (`public_key_pem` column).

### 2. Current Signature Format
- The edge computes a SHA-256 hash over a deterministically sorted JSON serialization of the mandatory fields of an `EvidencePackage` (`shared/schemas.py`).
- The edge signs the raw bytes of this hash using the Ed25519 private key.
- The resulting hex string is attached to the `EvidencePackage.signature` field.
- **Deficiency:** The signature metadata does NOT specify which key generated it. It implicitly assumes the current key.

### 3. Current Verification Flow
- **Ingest & API:** `backend/services/verification.py` handles the verification (`verify_signature`).
- **Resolution:** It retrieves the `public_key_pem` from the associated `Camera` record.
- **Validation:** It uses `cryptography.hazmat` to verify the Ed25519 signature against the re-computed SHA-256 hash.

### 4. Historical-Key Failure Risk
Because the `Camera` model only supports a single `public_key_pem` string:
- Rotating an edge key currently requires overwriting the `public_key_pem` field in the database.
- Once overwritten, all historical evidence packages that were signed with the old key will **fail** verification when a user or auditor queries them.
- This creates an unacceptable paradox where an organization cannot rotate keys without cryptographically invalidating their own historical evidence chain.

### 5. Files/Tables Affected
To implement safe key versioning, the following core components will need modification:
- **`backend/models/orm.py`**:
  - `Camera` (or a new `CameraKey` / `EdgeKeyRegistry` table) to support multiple versioned keys.
  - `EvidencePackage` to store `kid`.
  - `EvidenceChain` to store `kid`.
- **`shared/schemas.py`**:
  - `EvidencePackage` schema to include an optional `kid`.
- **`edge/evidence/packager.py`**:
  - `EdgeKeyManager` to derive or store a `kid`.
  - `EvidencePackager` to attach `kid` to the payload.
- **`backend/services/verification.py`**:
  - Modified signature verification to resolve public keys by `kid` instead of blindly trusting the single camera-level key.
