# Phase 5: End-to-End Test Matrix

| Test Script | Target | Classification | Status |
|---|---|---|---|
| `test_e2e_happy_path.py` | Complete Pipeline | TRUE E2E | NOT EXECUTED — ENVIRONMENT BLOCKED |
| `test_e2e_offline_recovery.py` | Edge/Central Sync | TRUE E2E | NOT EXECUTED — ENVIRONMENT BLOCKED |
| `test_e2e_mtls_failure.py` | Security/Ingress | INTEGRATION / FAILURE INJECTION | NOT EXECUTED — ENVIRONMENT BLOCKED |
| `test_e2e_storage_failure.py` | Backend/MinIO | INTEGRATION / FAILURE INJECTION | NOT EXECUTED — ENVIRONMENT BLOCKED |
| `test_e2e_rtsp_failure.py` | Edge/Camera | INTEGRATION / FAILURE INJECTION | NOT EXECUTED — ENVIRONMENT BLOCKED |
| `test_e2e_resource_pressure.py` | Edge/Governor | INTEGRATION / FAILURE INJECTION | NOT EXECUTED — ENVIRONMENT BLOCKED |

*Note: All tests require a running Docker-based STAGING environment to execute.*
