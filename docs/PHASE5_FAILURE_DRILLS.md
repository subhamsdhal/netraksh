# Phase 5: Failure Drills

## 1. Offline Recovery
Designed to trigger intentional edge isolation via Docker/network disconnect. Asserts that the local edge SQLite sync queue grows while Central is down, the mTLS error rate spikes but is caught cleanly, and subsequent reconnection reliably drains the queue without creating duplicated objects or falsified metadata states on Central.

## 2. mTLS Failures
Invalidates certificates (expired, revoked, mismatched CN) and attempts synchronization. Validates that Central FastAPI strictly rejects unauthorized payloads while Edge logs an explicit `EDGE_CERTIFICATE_REVOKED` or `EDGE_AUTHENTICATION_FAILED` security audit event.

## 3. Object Storage Faults
Drops MinIO connectivity on Central. Evaluates how Central handles `upload_evidence` endpoints, specifically testing the metadata commit rollback to prevent falsely claiming evidence is `AVAILABLE` when the binary never reached the disk.

## 4. RTSP Faults
Targets the cv2 ingestion bounds. Injects stream drops and corrupted packets to trigger the `CameraHealthMonitor` transitions (`STALLING` -> `RECONNECTING` -> `FAILED`), ensuring the Edge python worker does not fatally crash and takes appropriate exponential backoffs.

## 5. Resource Pressure
Hooks into the WP-4.4 `EdgeResourceGovernor` by simulating massive CPU loads. Ensures `DEGRADED` logic safely sheds ANPR/Face loads while continuing to collect core detection evidence.
