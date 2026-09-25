# NETRAKSH — Phase 4 WP-3 Data Protection Architecture

## 1. System Audit & Baseline
The current state of data protection across the system:

### A. PostgreSQL / Supabase
- **Data Stored:** Camera metadata, event state, telemetry metrics snapshots, camera health, user credentials (hashed), audit logs, alerts, `EdgeIdentity` status, and sync queues.
- **Sensitivity:** Contains highly sensitive PII (License Plates, Face Match Names/IDs), moderately sensitive operational data (Camera Health, Zone Rules), and internal credentials (hashed passwords).
- **Existing Protection:** Assumes generic provider-level encryption-at-rest (e.g., Supabase transparent volume encryption). No application-level field/column encryption currently exists.
- **In Transit:** TLS enforced on backend API connections.
- **Backups & Retention:** Currently reliant on DB-provider automated volume snapshots. No application-level TTL or pruning implemented.

### B. Evidence Storage
- **Current State:** Both backend (`backend/data/evidence`) and edge (`edge/data/clips`) utilize raw local filesystem storage.
- **Integrity & Security:** Evidence files are accompanied by Ed25519 cryptographic signatures and SHA-256 hashes. The payload is encrypted (AES-GCM wrap) prior to upload.
- **Gaps:** Filesystem storage does not scale natively. Hard to enforce retention TTLs natively on raw filesystems compared to object-storage lifecycle rules.

### C. Credentials & Keys
- **Edge Private Keys:** Stored locally on edge node file systems (`certs/edge/`).
- **JWT Secrets:** Configured via `config.py` environments.
- **Database Credentials:** Database URI in configuration (plaintext URI strings).
- **Encryption Keys:** `evidence_encryption_key` managed locally, wrapped during transmission. No HSM or central KMS integration.

### D. Logs
- **Sensitive Metadata:** Present in audit logs (IP addresses, User IDs).
- **Edge Telemetry:** Ephemeral in-memory (WebSockets) or stored as JSON snapshots in DB (Metrics/Health).
- **Operator Actions:** Persisted to `audit_logs` table (immutable logic lacking cryptographic append-only guarantees).

---

## 2. Data Classification

| Data Type | Classification | Rationale & Protection Requirement |
|---|---|---|
| Edge Certificates (Public) | **PUBLIC** | Used for verification; needs integrity, not confidentiality. |
| Camera Metadata (Location, Rules) | **INTERNAL** | Operational data; generic DB encryption is sufficient. |
| Event Metadata (Timestamps, BBoxes) | **INTERNAL** | Analytical data; not individually identifying. |
| Telemetry & Logs (Perf, System) | **INTERNAL** | System health; low impact if exposed, but requires integrity. |
| License Plates (ANPR) | **SENSITIVE** | PII; requires access controls, audit logging, and eventual TTL deletion. |
| Face Identities (Watchlist names) | **SENSITIVE** | PII; requires strict RBAC and access monitoring. |
| Face Embeddings | **SENSITIVE** | Biometric data; cannot be reversed trivially but still highly sensitive. |
| Evidence Clips / Images | **SENSITIVE** | Raw surveillance capture; requires encryption-at-rest and strict access via Signed URLs. |
| Operator Audit Logs | **SENSITIVE** | Forensic trail; requires append-only integrity to prevent tampering. |
| Edge Private Keys | **HIGHLY SENSITIVE** | Complete compromise of edge identity if stolen; requires TPM/Secure Enclave. |
| JWT Signing Secrets | **HIGHLY SENSITIVE** | Complete compromise of backend auth if stolen; requires KMS/Vault. |

---

## 3. Evidence Storage Architecture (Target: Object Storage)

**Migration Goal:** Separate PostgreSQL (relational state/metadata) from Object Storage (bulk blobs).
- **PostgreSQL:** Metadata, event indexing, access state.
- **Object Storage (S3/MinIO):** Evidence clips, JPEG snapshots, cryptographic manifests.
- **Edge Node:** Continues as temporary SQLite buffer + FS buffer.

**Design Specs:**
- **Object Naming:** `{camera_id}/{YYYY}/{MM}/{DD}/{event_id}_clip.mp4.enc`
- **Integrity:** `ETag` (MD5) for transfer validation; application-layer SHA-256 injected into object metadata.
- **Encryption:** Keep application-layer envelope encryption before S3 upload (zero-trust storage). 
- **Access Control (Signed URLs):** The backend generates short-lived (e.g., 5-minute) signed URLs for the frontend. The frontend never accesses buckets directly.
- **Retention & Deletion:** Implement S3 Lifecycle Rules (e.g., transition to infrequent access after 30 days, delete after 90 days). Application DB triggers soft-deletes; cloud lifecycle handles hard physical sweeps.

---

## 4. Key Management Architecture

| Key Type | Current Storage | Threat | Rotation | Revocation | Backup | Future Hardening |
|---|---|---|---|---|---|---|
| **A. Evidence Signing (Ed25519)** | Edge filesystem | Edge node theft | Rotate edge-side; new public key uploaded via API. | Backend invalidates old public key. | No (Keys are ephemeral/replaceable). | TPM / Secure Enclave binding. |
| **B. TLS Private Keys (mTLS)** | Edge filesystem | MITM / Spoofing | Re-issue cert; backend updates `EdgeIdentity` fingerprint. | Update status to `REVOKED`. | No (Re-enroll device). | Edge Hardware Security Module (HSM). |
| **C. JWT Secrets** | Env Vars | Backend compromise | Update environment variable. | Automatic (all current tokens invalidate). | Yes (Infrastructure-as-Code). | HashiCorp Vault / Cloud KMS. |
| **D. Object Storage Keys** | Env Vars | Storage exfiltration | Generate new DEK/KEK hierarchy. | N/A (Data becomes unreadable). | Yes (Critical for data recovery). | Cloud KMS Envelope Encryption. |
| **E. Database Credentials** | Env Vars | DB Exfiltration | Update DB user password; restart backend. | Terminate existing connections. | Yes (IaC). | Dynamic Secrets (Vault). |

---

## 5. Rotation & Versioning Design

**Crucial Constraint:** Rotating a signing key or encryption key must **not** invalidate historical evidence.

**Design: Key Versioning (KID)**
- Every generated signature or encrypted payload will include a Key ID (`kid`) in its header/manifest.
- The backend `Camera` or `EdgeIdentity` tables will maintain a `keys` JSONB array (or dedicated one-to-many table) mapping `kid` -> `public_key`.
- **Edge Certificate Rotation:** The edge generates a new CSR, receives the cert, and connects. The backend registers the new fingerprint, marks the old as `EXPIRED`, but retains historical logs associated with it.
- **Application Secret Rotation:** Support multiple concurrent JWT secrets (e.g., `JWT_SECRET_PRIMARY`, `JWT_SECRET_SECONDARY`) to allow graceful overlap during rotation.

---

## 6. Retention & Lifecycle Policies

Policy-driven lifecycle management, configured centrally:
- **Raw Evidence (No Alert):** 7 Days -> Delete.
- **Processed Evidence (Alert Triggered):** 30 Days -> Archive (Cold Storage) -> 90 Days -> Delete.
- **Event Metadata:** 90 Days.
- **Audit Logs:** 365 Days (or indefinitely for compliance).
- **Telemetry & Health:** 7 Days (Aggregated), then purge raw data.
- **Offline Queues (Edge):** Delete oldest on 80% disk capacity threshold (FIFO ring buffer).
- **Legal Hold:** A `legal_hold=true` flag on the `Event` prevents automated object lifecycle expiration.

---

## 7. Security Threat Model

| Attack Scenario | Current Control | Gap | Mitigation (WP-3 Target) |
|---|---|---|---|
| **Database Compromise** | Network boundaries | Cloud admin can read plaintext DB. | Application-level encryption for highly sensitive fields (e.g., Biometrics). |
| **Object Storage Compromise** | Private Bucket | Admin/IAM leak exposes blobs. | Client-side (Edge) Envelope Encryption before upload. |
| **Stolen Edge Device** | JWT/mTLS | Attacker extracts keys from disk. | Hardened TPM storage; rapid centralized Revocation API. |
| **Stolen Edge Private Key** | None on edge | Key is exposed if disk copied. | Bind keys to hardware (TPM); mTLS Revocation prevents usage. |
| **Insider Access (Backend)** | RBAC | DB Admin can view all data directly. | Separate DB credentials from Key Management (Separation of Duties). |
| **Expired Credentials** | None for DB/Storage | Long-lived credentials increase leak window. | Implement scheduled rotation playbooks. |
| **Offline Queue Theft** | None | Edge SQLite buffer is unencrypted. | Implement SQLite SQLCipher (at-rest encryption) for edge buffers. |

---

## 8. WP-3 Implementation Recommendation

**RECOMMENDED WP-3: Combined Phased Implementation (Focus: Key Management & Storage First)**

**Exact Scope:**
1. **Key Versioning Foundation:** Implement the `kid` versioning logic in the database to support multiple active public keys per edge device, ensuring historical signature validation won't break on rotation.
2. **Object Storage Abstraction Implementation:** Complete the `ObjectStorageBackend` in `evidence_storage.py` (e.g., using MinIO/S3 compatible APIs) with Signed URL generation, replacing local filesystem serving for the dashboard.
3. **Edge Database Encryption (SQLCipher):** Encrypt the local SQLite `sync_queue` buffer to protect evidence at rest on physically vulnerable edge devices.

**Why (Evidence-Based Reasoning):**
Blanket PostgreSQL application encryption is premature. The highest immediate risks based on the architecture audit are (A) physical theft of the edge device compromising the unencrypted offline SQLite buffer and keys, and (B) local filesystem storage bottlenecking the backend evidence serving. By establishing Key Versioning now, we safely enable future key rotation. Moving evidence to Object Storage immediately isolates bulk sensitive media from the operational database network. Implementing SQLCipher on the edge protects the most vulnerable physical attack surface (the camera pole).
