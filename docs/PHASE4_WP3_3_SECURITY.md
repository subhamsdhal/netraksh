# Phase 4 WP-3.3: Object Storage Security

## 1. Binary Content Hash
WP-3.3 introduces a clear distinction between Logical Evidence Hashes (which protect the cryptographic Ed25519 payload signatures) and Binary Content Hashes.

- **Integrity Guarantee**: The edge computes the SHA-256 hash of the binary file before upload and passes it as `expected_hash`. The backend recalculates the hash from the received byte stream (`hashlib.sha256(content).hexdigest()`) and explicitly rejects the upload (`400 Bad Request`) if a mismatch occurs.
- **Trust Boundary**: The backend never trusts a client-provided hash for the physical binary without independently recomputing it.

## 2. Path Traversal Prevention
Object storage keys are generated deterministically by the backend upon ingest, eliminating client-provided filename injection vectors:
`evidence/{camera_id}/{date_str}/{event_id}.jpg[.enc]`
Additionally, the legacy `LocalFilesystemStorage` backend employs rigorous `os.path.commonprefix` validation to ensure that any legacy read requests cannot escape the configured `EVIDENCE_CLIPS_DIR` sandbox.

## 3. Oversized Payload Rejection
The `/events/{event_id}/evidence` endpoint actively limits uploads, raising a `413 Request Entity Too Large` error if the binary length exceeds `settings.MAX_UPLOAD_SIZE_BYTES`. This mitigates volumetric Denial of Service (DoS) attacks on the backend ingest API.

## 4. Signed URL RBAC Protection
The `generate_signed_url` mechanism ensures that the object store does not become a bypass vector circumventing Application RBAC:
1. Client requests `GET /events/{event_id}/evidence-image` using existing JWT authentication.
2. Backend validates `require_any_role` and verifies the event ID exists.
3. Upon success, the backend securely computes and issues a short-lived (e.g., 3600 seconds) Signed URL directly to the requesting client via a `307 Temporary Redirect`.
4. Unauthorized actors cannot generate or guess URLs for raw objects.

## 5. mTLS Identity Binding
The endpoint `POST /events/{event_id}/evidence` validates the caller's edge identity using the `get_edge_identity` dependency. If an authenticated `edge_id` is present, it explicitly enforces that the uploading device matches the device that originally reported the event metadata (`event.edge_device_id`), blocking lateral spoofing where a compromised device attempts to inject evidence into a different device's event.
