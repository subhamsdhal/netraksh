# NETRAKSH — Phase 4 WP-2 mTLS Architecture

## Overview
This document outlines the architectural changes implemented in Phase 4 Work Package 2 to enforce Mutual TLS (mTLS) for Edge-to-Cloud communication. 

The primary goal of this package was to cryptographically bind edge devices (cameras and processing nodes) to the cloud backend, ensuring that no untrusted device can ingest telemetry, evidence, or health statistics, even if they possess a valid API token.

## Architectural Enforcement

### 1. Identity Abstraction
The system no longer blindly trusts the JSON payload for identity (`edge_device_id`). Instead, it extracts the identity from the authenticated TLS connection itself.
- **Direct TLS (Mode A)**: Extracted directly from Uvicorn's ASGI `extensions.tls.client_cert` if TLS is terminated directly at the application layer.
- **Trusted Proxy (Mode B)**: Extracted from `X-Client-Fingerprint` and `X-Client-Serial` headers, relying on a trusted reverse proxy (e.g., NGINX, Envoy) that performs client certificate validation.

### 2. Configuration & Validation
`MTLS_MODE` ("disabled", "optional", "required") and `MTLS_TRUSTED_PROXY` (boolean) dictate the security posture. 
When set to `required`, the backend immediately rejects any connection on the edge ingress endpoints without a verified cryptographic identity. Configuration is validated at runtime startup in `backend/config.py`.

### 3. Client Strict TLS
The edge client (`edge/sync/sync_client.py` and secondary HTTP requests in `edge/main.py`) explicitly forbids `verify=False`. It strictly mandates using the CA certificate for server verification to prevent man-in-the-middle (MITM) attacks and credential theft.

## Affected Components
- `backend/security/auth.py`: `get_edge_identity` dependency added.
- `backend/api/events.py`: Replaces arbitrary `edge_device_id` with authenticated ID for `POST /events`.
- `backend/api/system.py` & `backend/api/cameras.py`: Telemetry and health endpoints now demand the `get_edge_identity` dependency.
- `edge/sync/sync_client.py`: `httpx.Client` strictly enforces `verify`.
- `edge/main.py`: Secondary telemetry endpoints wrapped in strict TLS.
