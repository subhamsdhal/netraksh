# NETRAKSH — Phase 4 WP-2 Security Model

## Threat Model & Mitigations

### 1. Identity Spoofing (Spoofed Edge Node)
**Threat:** An attacker compromises an edge node's API token or intercepts the JSON payload, attempting to submit evidence or health telemetry as another node by modifying `edge_device_id`.
**Mitigation:** The edge identity is bound to the TLS layer via Mutual TLS. The JSON `edge_device_id` field is overridden server-side by the cryptographically verified identity (Certificate Fingerprint) matching the `EdgeIdentity` record in the database.

### 2. TLS Downgrade / Stripping
**Threat:** An active attacker performs a Man-In-The-Middle (MITM) attack to downgrade the TLS connection or serve an invalid certificate.
**Mitigation:** The edge client (`sync_client.py` and `main.py`) strictly enforces `verify=True` (or path to a pinned CA certificate). The system actively throws an exception if `verify=False` is passed, failing closed.

### 3. Certificate Revocation & Suspension
**Threat:** An edge device is physically stolen or compromised. Its certificate is used to ingest malicious data.
**Mitigation:** The `EdgeIdentity` model tracks the state of edge certificates. When the status is set to `REVOKED`, `SUSPENDED`, or `EXPIRED`, the backend forcefully rejects the connection with a 403 Forbidden, and audits the attempt. Rotation of certificates maps new fingerprints to existing edge logical IDs seamlessly.

### 4. Reverse Proxy Header Spoofing (Mode B)
**Threat:** A client sends `X-Client-Fingerprint` headers directly to the backend to bypass TLS validation.
**Mitigation:** `MTLS_TRUSTED_PROXY` mode must only be enabled in architectures where the backend is strictly firewalled to only accept connections from the trusted proxy (which strips arbitrary headers and only injects the validated ones).

## Idempotency & Offline Buffer
The implementation preserves edge offline buffering. If the mTLS handshake fails or the certificate is suspended, the edge sync client marks the payload as `QUEUED` and retries automatically when connectivity or authorization is restored.
