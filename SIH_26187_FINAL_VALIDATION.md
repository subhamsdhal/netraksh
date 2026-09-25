# NETRAKSH – SIH 26187 Final Validation

Validation date: 23 September 2026. Baseline branch: `main`, commit baseline `8a73299`, with the pre-existing dirty worktree preserved.

## 1. Executive Status

The native Windows SIH demo path is **VERIFIED WORKING** for authenticated frontend/backend operation, SQLite migration, real repository-video decode, actual YOLO inference, ByteTrack tracking, temporal behavior rules, event/evidence/alert persistence, WebSocket updates, and alert lifecycle. Docker/PostgreSQL, physical or localhost RTSP, real enrolled-face acceptance, labeled ANPR/night accuracy, and full-inference multi-camera scale remain explicitly unverified.

## 2. Exact Verified Architecture

`Vite/React :5173 → FastAPI/Uvicorn :8443 → SQLite` with a separate Python edge process performing OpenCV decode, PyTorch YOLOv8n, ByteTrack, health/scene/reliability gates, rules, encrypted/signed evidence packaging, local SQLite outbox, authenticated synchronization, and WebSocket dashboard broadcast. The intended container path adds PostgreSQL, MinIO, a migration job, frontend, backend, and edge.

## 3. Localhost Services

Clean-start checks returned HTTP 200 from frontend `/`, backend `/health`, and `/ready`. Browser inspection showed `SYSTEM OPERATIONAL`, `EDGE ONLINE`, `SOCKET CONNECTED`, live telemetry, six tracks, 768×576 input, and actual processing FPS during the edge run.

## 4. Build Status

- `npm run build`: **VERIFIED WORKING**, 2,435 modules transformed.
- `npm run lint`: exit 0 with existing warnings; warnings remain technical debt.
- `pip check`: no broken requirements.
- Compose YAML static parse and service/dependency assertions: passed.

## 5. Test Status

- Canonical `python -m pytest`: **673 passed, 13 skipped, 1 deselected**, 34.67 s.
- Opt-in real YOLO smoke: **1 passed**, 3.66 s.
- Frontend `npm test`: **4 files, 6 tests passed**.
- Frontend coverage includes login/token behavior, protected routes, health realtime merge, and JWT-subprotocol WebSocket processing.
- One non-fatal unawaited-AsyncMock warning remains in the Python suite.

## 6. Detection & Tracking

**VERIFIED WORKING** against `demo/videos/vtest.avi`: packaged YOLOv8n loaded and warmed on CPU, supported objects were detected, COCO bicycle was not mapped to PERSON, ByteTrack IDs appeared in telemetry, and a finite source exited cleanly.

## 7. Facial Analytics

Face detection/LBPH wiring and synthetic known/unknown tests are **VERIFIED PARTIAL**. No repository-owned suitable real enrollment pair was found; end-to-end known/unknown real-face acceptance is **BLOCKED BY TEST DATA**. No production accuracy or liveness claim is supported.

## 8. ANPR

ANPR artifact/session, localization evaluator, OCR metrics, temporal fusion wiring, and LPD-YuNet shape compatibility are **FIXED AND VERIFIED** by maintained tests. The hard `python-Levenshtein` dependency was removed, model output dimensions were normalized, and degenerate quadrilaterals are rejected correctly. `PlateWatchlist.match()` remains a stub, no labeled Indian plate corpus was available, and searchable operator history was not executed; accuracy is **BLOCKED BY TEST DATA**.

## 9. Intrusion & Behavior

Virtual fence, line crossing, loitering, movement/behavior rules, temporal confirmation, and evidence escalation executed in the actual finite-video edge run. This is **VERIFIED WORKING** for the configured demo, not a field-accuracy claim.

## 10. Night Surveillance

Low-light classification, preprocessing, motion fallback, and uncertainty semantics have maintained tests, but no labeled repository night corpus was available for a measured comparison in this continuation. Status: **VERIFIED PARTIAL**; accuracy is not established.

## 11. RTSP / CCTV

CameraAdapter reconnect, invalid/open failure, decoder exception, bounded queue, blocking-read stall detection, backoff, and shutdown tests pass (8/8 focused tests). The implementation was fixed so read-duration stalls trigger reconnect with bounded backoff. No FFmpeg or RTSP server and no authorized physical URL were available. Actual `rtsp://` transport is **BLOCKED BY TOOLING/HARDWARE**.

## 12. Multi-Camera

The ingestion-only harness admitted 1/1 and 2/2 streams; at a requested 5 it enforced the configured hard limit and admitted 4/5. The harness decodes and paces frames but does not run independent YOLO models, so its ~60 FPS/stream figures are not inference capacity. Full-inference 5/10-stream scalability is **NOT IMPLEMENTED/UNVERIFIED**; no 100-camera claim is safe.

## 13. Alerts & Evidence

Event insertion, alert creation, evidence encryption/hash/signature/chain checks, authorized retrieval, tamper detection, acknowledgement, closure, audit, and persistence are **VERIFIED WORKING** through integration tests and the prior live UI lifecycle. Verification status strings were restored to their stable API contract.

## 14. Offline Resilience

The real integration test queued edge events while the backend endpoint was unavailable, restored reachability, synchronized exactly once, and passed. Status: **VERIFIED WORKING at integration-test level**. A second live process/network outage drill was not run in this continuation.

## 15. Cybersecurity

Authentication/RBAC, protected evidence, path confinement, key lifecycle, signature tamper detection, edge bearer authentication, and JWT WebSocket subprotocol tests pass. Live smoke confirmed unauthenticated `/events` returns 401 and authenticated access succeeds. Private-destination webhook SSRF policy, per-device token-to-camera binding, comprehensive biometric input limits, video quotas/retention, and durable signed webhook outbox remain high-priority gaps.

## 16. PostgreSQL / Deployment

Docker commands were absent. Container and PostgreSQL execution are **BLOCKED BY TOOLING**. Compose statically contains `db`, `minio`, `migrate`, `backend`, `frontend`, and `edge`, with DB health-gated migration and migration-gated backend. Native Alembic is at `3d86d25c0fdc (head)`. The runbook contains the exact external validation checklist.

## 17. Performance

Actual finite-video run: 768×576, 265 measured frames, end-to-end 3.4 FPS, frame mean 108.9 ms and p95 133.7 ms; 39 event samples, event mean 19.5 ms and p95 24.6 ms; 39 emitted events/alerts; process RSS 716.6 MB; zero dropped telemetry; CPU PyTorch inference, ANPR/face/behavior enabled. These are current-machine demo figures, not scale projections.

## 18. Demo Scenarios

Human intrusion, line crossing, loitering, alert lifecycle, evidence integrity, and dashboard persistence are deterministic with the repository clip. Vehicle/ANPR, face watchlist, night, and a visible live outage drill require rehearsal with approved data/tooling. `scripts/demo_smoke.ps1` provides a non-zero-exit stack check.

## 19. Remaining Limitations

No executed Docker/PostgreSQL/MinIO deployment; no actual RTSP session; no real face dataset; no labeled Indian plates or night corpus; no full-inference 5/10-stream test; no 100-camera evidence; no true browser live CCTV gateway; zone editing remains file/config driven; plate watchlist matching is stubbed; webhook SSRF/signing/outbox, identity-bound camera authorization, upload/retention controls, and evidence semantic crypto-v2 require further work.

## 20. SIH Requirement Traceability Matrix

| SIH Capability | Current State | Verification Method | Evidence | Remaining Limitation |
|---|---|---|---|---|
| RTSP/CCTV ingestion | VERIFIED PARTIAL | CameraAdapter failure suite | 8 focused tests pass | No real `rtsp://` source |
| Human detection | VERIFIED WORKING | Real YOLO/video run | Actual supported detections | Demo clip only |
| Human tracking | VERIFIED WORKING | Edge telemetry | Stable ByteTrack IDs | Field occlusion not calibrated |
| Vehicle detection | VERIFIED WORKING | Real YOLO smoke | COCO vehicle classes | Demo data only |
| Vehicle classification | VERIFIED PARTIAL | Mapping/unit tests | car/motorcycle/bus/truck subtype path | No labeled evaluation |
| Face detection | VERIFIED PARTIAL | Maintained face tests | detector/crop wiring passes | No approved real images |
| Face recognition | BLOCKED BY TEST DATA | Synthetic LBPH tests only | Known/unknown logic passes | No real enrollment acceptance |
| ANPR | VERIFIED PARTIAL | Artifact/evaluator/runtime tests | LPD/OCR/fusion tests pass | No labeled Indian plates; watchlist stub |
| Virtual fence | VERIFIED WORKING | Actual edge run | Confirmed events | Site calibration needed |
| Intrusion | VERIFIED WORKING | Actual edge run | Event/evidence/alert flow | Demo scenario only |
| Suspicious activity | VERIFIED PARTIAL | Rule/tests and loiter demo | Temporal rules execute | No weapon/violence model |
| Night movement | VERIFIED PARTIAL | Unit/integration semantics | Low-light/motion code tested | No labeled night benchmark |
| Alerts | VERIFIED WORKING | API/UI lifecycle | create/ack/close/persist | None for demo scope |
| Event logging | VERIFIED WORKING | Backend integration | DB and audit queries pass | PostgreSQL not executed |
| Evidence | VERIFIED WORKING | Crypto/storage E2E | tamper detection/retrieval | Crypto-v2 semantics pending |
| Multi-camera | VERIFIED PARTIAL | Ingest-only 1/2/5 harness | 1/1, 2/2, 4/5 admitted | Not multi-model inference |
| Dashboard | VERIFIED WORKING | Browser + frontend tests | live status/tracks/socket | Bundle size warning |
| Auth | VERIFIED WORKING | Live smoke + tests | login/401/token expiry paths | Login throttling review remains |
| RBAC | VERIFIED WORKING | Integration tests | unauthorized/wrong-role denied | Enterprise IAM out of scope |
| C2/API integration | VERIFIED PARTIAL | Export/webhook tests/source | API and best-effort webhook path | SSRF/signing/outbox gaps |
| Offline operation | VERIFIED WORKING | Real integration test | queue→restore→sync once | Live outage drill pending |
| Remote deployment | BLOCKED BY TOOLING | Compose static check | service graph parsed | Docker/PostgreSQL unexecuted |
| Cybersecurity | VERIFIED PARTIAL | Security/integration suite | media/path/auth/crypto fixed | listed P1 security gaps |
| Scalability | VERIFIED PARTIAL | Admission harness | four-stream configured ceiling | no full inference scale test |
| Existing-camera cost support | VERIFIED PARTIAL | OpenCV/file adapter path | commodity CPU/file source works | CCTV codec/RTSP field validation |

## 21. Final Demo Readiness

**SIH DEMO READY WITH EXPLICIT LIMITATIONS** for the native deterministic video scenario. Judges may safely be shown real detection/tracking/rules/evidence/alerts/dashboard/auth behavior and measured current-machine performance. The team must not present Docker/PostgreSQL, physical CCTV, real face accuracy, ANPR accuracy, night accuracy, or 100-camera scalability as validated.
