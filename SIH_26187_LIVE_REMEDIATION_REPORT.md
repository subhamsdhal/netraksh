# SIH 26187 – NETRAKSH Live Remediation Report

## 1. Starting State

Preserved the pre-existing dirty `main` worktree (baseline `8a73299`). No reset, stash, commit, or push was performed. The original audit was read before edits.

## 2. Machine / Toolchain State

Windows native validation used Node 24.19.0/npm 11.17.0 and a disposable Python 3.12.14 environment. Docker was unavailable. System Python was unavailable, so copied environments were not reused.

## 3. Actual Localhost Architecture

| Component | Actual endpoint | Status |
|---|---|---|
| Frontend | `http://127.0.0.1:5173` | running |
| Backend | `http://127.0.0.1:8443` | running |
| API liveness/readiness | `/health`, `/ready` | HTTP 200 |
| Database | SQLite `netraksh.db` | native development validation |
| Edge | local finite demo video process | executed to EOF |

## 4. Services Started

Final clean restart used Uvicorn on 8443 and Vite on 5173. Both listeners were verified after terminating only identified NETRAKSH processes.

## 5. Backend Live Verification

`/health` and `/ready` returned 200 after final restart. Protected events returned 401 unauthenticated and 200 with an authorized session. Backend WebSocket connections were accepted without placing JWTs in URLs.

## 6. Frontend Live Verification

Live browser checks covered dashboard, Health, Analytics, Audit, Alerts, Evidence navigation, and map state. Dashboard loaded after the clean restart with six registered camera records; Analytics and Audit loaded API-backed data. Map honestly reports no coordinate-bearing camera rather than invented locations.

## 7. Database Verification

Fresh SQLite `alembic upgrade head` reached `0e04f2547bf8 (head)` and produced 54 tables. Compose now runs migrations before backend. PostgreSQL/container execution remains blocked because Docker is unavailable.

## 8. Edge Pipeline Verification

The edge pipeline ran against `demo/videos/vtest.avi`: decode, PyTorch YOLO, ByteTrack, rules, encrypted/signed evidence packaging, local queue, authenticated backend sync, health/metrics, and EOF queue flush all completed. It produced 49 persisted events and 6 alerts in the test stream. The finite source then exited normally.

## 9. AI/CV Verification

Actual YOLO smoke test passed (`1 passed in 7.45s`) using repository `yolov8n.pt`; bicycle class 1 no longer maps to person. OpenCV contrib/LBPH was installed and verified (`LBPH_RUNTIME_OK 4.10.0`); face suites passed 27 tests. Recognition is still only synthetic known/unknown validated because no enrolled authorized real subject was supplied. ANPR runtime is present but no labeled plate result was available.

## 10. WebSocket Verification

Browser reconnect after backend restart reached `SOCKET CONNECTED`; backend logs show accepted `/ws/dashboard` connections without query-string tokens. Global Header connection state fixed false disconnection on non-dashboard routes.

## 11. End-to-End Event Flow

Observed flow: demo frame → YOLO detection → track IDs → temporal-confirmed virtual-fence/line/loiter rules → evidence hash/signature packaging → queue → backend event/evidence endpoints → SQLite → alert → WebSocket → dashboard/alerts UI. Alert `47c1e7f5…` was acknowledged, closed, visibly rendered `CLOSED`, and persisted after refresh.

## 12. Security Remediation

Removed the public demo-video static mount; protected media/telemetry now enforce authorization. Constrained media path resolution rejects traversal and absolute paths. Verified: public video changed from 200 to 404; unauthenticated protected media/telemetry return 401; normal authorized media works; traversal/absolute requests reject safely. JWT is sent as a WebSocket subprotocol, with legacy query support only for older clients.

## 13. P0 Remediation Results

P0 backend startup/dependencies, migration target selection, edge OpenCV/LBPH runtime, detector class mapping, protected media/path confinement, frontend health contract, WebSocket token handling, and alert lifecycle synchronization are fixed and verified. Added edge Compose service with explicit required model and key mounts.

## 14. P1 Remediation Results

Virtual fence, line crossing, loitering, and temporal verification ran against actual video. Rapid-approach coordinate units were corrected. Event alias handling prevents legacy SQLite values from causing response 500s. ANPR and night accuracy remain partial/unverified due absence of suitable labeled input.

## 15. P2 Remediation Results

Evidence ingestion cleanup, live alert history/filtering, protected video telemetry, audit/analytics fetch race handling, and fresh migration behavior were exercised. No broad refactor was applied.

## 16. P3/P4 Work Completed

Removed the broken mock health image dependency, ensured real health-field naming, added explicit edge setup automation, and documented honest production mounts. Existing lint warnings remain technical debt rather than hidden failures.

## 17. Tests Added

Added `tests/unit/test_live_remediation_security.py` and opt-in `tests/integration/test_real_yolo_smoke.py`; expanded detector mapping, temporal verifier, and behavior regression coverage.

## 18. Test Results

- Targeted remediation suite: **39 passed**.
- LBPH face/wiring suite: **27 passed**.
- Maintained unit suite: **537 passed, 1 order-dependent test failure**. The failure is `test_cleanup_failure_logged_original_error_preserved`; it passes in isolation and logs both cleanup and original errors, but loses `caplog` records after preceding suite state. This is a test-harness/log-capture issue, not evidence cleanup behavior.
- Bare repository `pytest` is invalid: it collects legacy scratch scripts, browser harnesses without Playwright, and a binary `.txt` file (11 collection errors). These are categorized TEST_DEFECT/DEPENDENCY, not product-suite failures.

## 19. Build Results

`npm run lint` completed with existing warnings; `npm run build` succeeded (2,435 modules, production bundle emitted). `pip check` passed after the OpenCV/LBPH repair.

## 20. Files Modified

Key changes: backend media/dashboard/events/cameras/websocket/logging paths; frontend auth, Header, WebSocket hook, Alerts, Analytics, Audit, Health, VideoFeed; edge runtime/rules/temporal requirements/Dockerfile; Alembic, Compose, tests, and `scripts/setup_edge_runtime.ps1`.

## 21. Remaining Blockers

Docker is unavailable, so PostgreSQL/MinIO/Compose container execution cannot be verified. No authorized RTSP endpoint or multi-camera hardware was configured. No real enrolled person image or labeled night/plate corpus was available.

## 22. Remaining Missing Features

No verified weapon/violence/action-recognition capability; plate-watchlist matching remains outside this remediation. Production calibration requires properly labeled two-class field data.

## 23. Remaining Unverified Features

Real RTSP reconnect/error paths, 2+/5+ live streams, PostgreSQL/MinIO deployment, real face enrollment/recognition, ANPR accuracy, and night accuracy are unverified—not claimed working.

## 24. Current SIH Requirement Matrix

| Capability | Status |
|---|---|
| Backend/frontend localhost | VERIFIED WORKING |
| SQLite migrations | VERIFIED WORKING |
| Demo edge detection/tracking/rules/evidence/alerts | VERIFIED WORKING |
| Protected media/path security | FIXED AND VERIFIED |
| LBPH runtime | VERIFIED PARTIAL |
| ANPR/night | VERIFIED PARTIAL / accuracy unverified |
| RTSP/multi-camera | BLOCKED_BY_EXTERNAL_RESOURCE |
| Docker PostgreSQL deployment | FIXED BUT BLOCKED FROM FULL VERIFICATION |

## 25. Final Live System Status

The native localhost system is running on ports 5173/8443 and passes final health/readiness and browser smoke checks. It is demonstrable with a finite local video pipeline and real persisted alerts/evidence. It is not production/SIH-ready for real cameras until the listed external validation, calibration, container, and scale gaps are closed.

# Phase 2 – Production & Real-World Validation

Continuation date: 23 September 2026.

## Environment

Windows native validation used Python 3.12.14, Node 24.19.0/npm 11.17.0, CPU PyTorch/YOLO, SQLite, Vite, and Uvicorn. The dirty `main` worktree and all user changes were preserved. Docker and FFmpeg executables were absent.

## Clean Restart Results

Only command-line-verified NETRAKSH listeners were stopped. A fresh backend and frontend started on 8443/5173; `/health`, `/ready`, and frontend `/` returned 200. Alembic reported `3d86d25c0fdc (head)`. A fresh edge process ran the repository `vtest.avi` through YOLO, ByteTrack, rules, evidence, telemetry, and backend synchronization to normal EOF. Browser state showed system/edge/socket operational and six live tracks.

## Full Test Results

Added root `pytest.ini` and repository-local runtime/temp directories so plain `python -m pytest` selects maintained tests and is reproducible. Fixed the order-dependent authentication/logging fixtures instead of skipping them. Final result: **673 passed, 13 skipped, 1 slow test deselected**. The separately enabled real YOLO test passed. Frontend Vitest infrastructure now provides `npm test`: **4 files, 6 tests passed**. Lint exits 0 with warnings and production build succeeds.

## Docker Results

`where docker`, `docker version`, and `docker compose version` confirmed Docker is unavailable: **BLOCKED BY TOOLING**. Static YAML parsing verified the six intended services and health/migration dependency order. An exact Docker checklist is in the demo runbook.

## PostgreSQL Results

No PostgreSQL container/service was available: **BLOCKED BY TOOLING**. SQLite migration and persistence are verified; this is not substituted for a PostgreSQL claim.

## RTSP Results

CameraAdapter focused tests pass for open success/failure, bounded drop-oldest queue, reconnect, decoder exceptions, stalls, and shutdown. Blocking-read duration now triggers a stalled/reconnecting state and bounded wait. No actual RTSP server or authorized camera was available: transport validation is **BLOCKED BY TOOLING/HARDWARE**.

## Face Enrollment Results

LBPH and recognition wiring tests pass, but no suitable repository-owned real known/unknown enrollment images were found. Status: **BLOCKED BY TEST DATA** for real acceptance; synthetic functionality remains **VERIFIED PARTIAL**.

## ANPR Results

Fixed undeclared edit-distance dependency, LPD-YuNet output-shape compatibility, schema compatibility, and degenerate quadrilateral classification. Maintained ANPR tests pass. No labeled Indian plate set was available and plate watchlist matching is still stubbed. Status: **VERIFIED PARTIAL / BLOCKED BY TEST DATA**; no accuracy percentage is claimed.

## Night Results

Low-light/motion/uncertainty code remains test-covered but a labeled night corpus was unavailable. Status: **VERIFIED PARTIAL**, not dataset validated.

## Multi-Camera Results

The decode/admission harness ran at requested counts 1, 2, and 5: 1/1 and 2/2 admitted, while the configured safety ceiling admitted 4/5. This harness does not execute a YOLO model per stream; it is not evidence of full-inference scale. Ten streams were not attempted because the safety controller already rejected the fifth.

## Offline Recovery Results

The maintained integration test exercised unreachable backend → local queued event → backend restoration → exactly-once synchronization and passed. Status: **VERIFIED WORKING at integration-test level**; a second manual process outage drill was not run.

## Security Regression Results

Full tests cover unauthenticated evidence denial, path/key traversal, RBAC, edge auth, key lifecycle, signature/hash tampering, and WebSocket JWT handling. The executable demo smoke confirmed unauthenticated protected API 401, authenticated events/alerts/node health 200, and authenticated WebSocket connection. Webhook SSRF policy, identity-bound camera authorization, upload limits/quotas, and signed durable delivery remain high-priority gaps.

## Performance Results

Actual edge run recorded 768×576 input, 3.4 end-to-end FPS, frame mean 108.9 ms/p95 133.7 ms over 265 frames, event mean 19.5 ms/p95 24.6 ms over 39 events, RSS 716.6 MB, zero dropped telemetry, and normal EOF flush. CPU inference, ANPR, face, and behavior paths were enabled. Results are demo-host measurements only.

## Remaining Blockers

Docker/PostgreSQL/MinIO, actual RTSP, true live browser CCTV gateway, approved real face images, labeled Indian plate/night data, full-inference 5/10-stream scale, operator zone editor, plate history/watchlist completion, webhook SSRF/signing/outbox, per-device camera binding, retention/quota policy, and crypto-v2 signed semantics.

## Final Requirement Matrix

The complete evidence-linked capability matrix is maintained in `SIH_26187_FINAL_VALIDATION.md`. Overall status is **SIH DEMO READY WITH EXPLICIT LIMITATIONS**, not production border-deployment ready.
