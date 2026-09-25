# NETRAKSH — Phase 4 WP-2 Test Matrix

## Execution Status

**ALL TESTS RECORDED AS:** `NOT EXECUTED — ENVIRONMENT BLOCKED`

Due to the lack of terminal execution capability in the current restricted environment, these tests have been written and structurally documented, but cannot be claimed as passed.

## Matrix

| Test Case ID | Component | Scenario | Expected Result | Execution Status |
|---|---|---|---|---|
| MTLS-1 | Identity Ingress | `POST /events` with valid TLS cert | Payload accepted, `edge_device_id` bound to cert | NOT EXECUTED |
| MTLS-2 | Identity Ingress | `POST /events` with missing TLS cert (Required Mode) | 401 Unauthorized | NOT EXECUTED |
| MTLS-3 | Identity Ingress | `POST /events` with unknown cert | 403 Forbidden | NOT EXECUTED |
| MTLS-4 | Edge Client | `SyncClient` upload with `verify=False` | `ValueError` raised, connection fails closed | NOT EXECUTED |
| MTLS-5 | Edge Client | Secondary telemetry threads (main.py) missing CA | connection fails, handled gracefully | NOT EXECUTED |
| MTLS-6 | Identity Revocation | `POST /events` with revoked certificate | 403 Forbidden | NOT EXECUTED |
| MTLS-7 | Identity Suspension | `POST /events` with suspended certificate | 403 Forbidden | NOT EXECUTED |
| MTLS-8 | Trusted Proxy Mode | `X-Client-Fingerprint` mapped securely | Correct identity bound | NOT EXECUTED |

## Future Remediation
Once terminal and environment execution capability is restored:
1. Initialize test database.
2. Generate mock x509 certificates and keys.
3. Configure Uvicorn for mTLS locally.
4. Execute `pytest tests/test_mtls_auth.py`.
5. Update this matrix with actual passage states.
