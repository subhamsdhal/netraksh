# Phase 4 WP-4.1: Test Matrix

The following test cases validate the resilience requirements of WP-4.1.

| ID | Test Case | Status | Objective |
|---|---|---|---|
| 1 | Initial connection success | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `INITIALIZING` -> `CONNECTED`. |
| 2 | Initial connection failure | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `INITIALIZING` -> `RECONNECTING`. |
| 3 | Reconnect success | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify recovery to `CONNECTED` after failure. |
| 4 | Reconnect failure | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify transition to `FAILED` (if bounded attempts). |
| 5 | Backoff growth | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify exponential increase in delay. |
| 6 | Maximum backoff bound | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify delay does not exceed `MAX_RECONNECT_DELAY`. |
| 7 | Jitter bound | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify jitter does not push delay over `MAX`. |
| 8 | Retry reset | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify counter resets upon successful frame. |
| 9 | Stall detection (post-init) | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `STALLING` on timeout after first frame. |
| 10 | No false stall (pre-init) | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify stall timeout doesn't fire before connection. |
| 11 | Queue boundedness | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify memory doesn't leak if inference is slow. |
| 12 | DROP_OLDEST behavior | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify oldest frame drops when queue is full. |
| 13 | Queue timeout behavior | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `get_frame` yields after timeout instead of blocking. |
| 14 | Decoder exception | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify exceptions are caught and trigger reconnect. |
| 15 | Empty frame | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify empty/False return triggers reconnect. |
| 16 | Camera health transition | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify adapter state feeds into `CameraHealthMonitor`. |
| 17 | Process isolation | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify main loop doesn't crash on camera fail. |
| 18 | URL redaction | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `rtsp://user:pass` is sanitized in logs. |
| 19 | Shutdown/join behavior | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify adapter releases resources and joins cleanly. |
| 20 | Central outage | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify ingest continues decoupled from mTLS/backend. |

*(Note: Execution is currently blocked in this environment; tests rely on static verification.)*
