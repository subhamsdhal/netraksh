# NETRAKSH SIH Demo Runbook

## QUICK START

Run `start_netraksh.cmd` from the repository root. It launches the native
backend, frontend, and named edge workers without terminating unrelated
processes.

## PRE-DEMO CHECK

Set `NETRAKSH_DEMO_USERNAME` and `NETRAKSH_DEMO_PASSWORD` in the current shell,
then run `powershell -File scripts/demo_smoke.ps1`. Confirm health, readiness,
authenticated API access, and WebSocket connectivity before judges arrive.

## NORMAL DEMO

Login, show the stable camera source, telemetry/detections, a real event,
reliability decision, latest event, alert, and signed evidence. Present ANPR,
face, low-light, RTSP, and deployment status only with the evidence-backed
claims in `SIH_26187_FINAL_DEMO_READINESS.md`.

## STOP

Close only the named NETRAKSH service windows. Do not delete local databases,
keys, evidence, or watchlist data as routine cleanup.

## TROUBLESHOOTING

Use `scripts/demo_smoke.ps1` and System Health first. If a worker fails,
restart that worker only; its durable outbox retries after backend recovery.

Validated on Windows on 23 September 2026. This runbook starts the native SQLite demo stack. Docker/PostgreSQL instructions are a separate deployment path and were not executable on the validation host because Docker was unavailable.

## 1. Prerequisites

- Python 3.12 virtual environment at `venv\Scripts\python.exe` or `.venv\Scripts\python.exe`.
- Backend and edge requirements installed; `python -c "import fastapi,cv2,ultralytics,uvicorn"` must succeed.
- Node.js/npm and `frontend\node_modules` installed.
- Repository model `yolov8n.pt` and video `demo\videos\vtest.avi` present.
- A local `.env` containing development settings and an edge token. Never commit real secrets.
- For continuous prerecorded replay, set `DEMO_LOOP_VIDEO=true` in the local demo environment. Production defaults remain conservative.

For authenticated smoke checks, set credentials only in the current terminal:

```powershell
$env:NETRAKSH_DEMO_USERNAME = "admin"
$env:NETRAKSH_DEMO_PASSWORD = Read-Host -AsSecureString | ConvertFrom-SecureString -AsPlainText
```

Use provisioned demo credentials; do not use development defaults in a shared or network-accessible deployment.

## 2. Startup

From the repository root:

```powershell
.\start_netraksh.cmd
```

The launcher checks Python imports, npm, the demo model/video inputs, and opens named service terminals. It starts backend, frontend, and two finite-video demo workers without terminating unrelated processes.

## 3. URLs

- UI/login: `http://127.0.0.1:5173/login`
- Backend health: `http://127.0.0.1:8443/health`
- Backend readiness: `http://127.0.0.1:8443/ready`
- OpenAPI: `http://127.0.0.1:8443/docs`

## 4. Automated Demo Check

```powershell
.\scripts\demo_smoke.ps1
```

The script exits non-zero unless frontend, health, readiness, unauthenticated denial, login, protected events/alerts, node health, and JWT-subprotocol WebSocket connection all pass.

## 5. Demonstration Sequence

1. Sign in and open Dashboard. Confirm `SYSTEM OPERATIONAL`, `EDGE ONLINE`, socket connected, and live track boxes.
2. Human intrusion: allow the demo video to enter the configured restricted zone; show the event, alert, evidence reference, and persisted result after refresh.
3. Line crossing: filter Alerts/Events to the line-crossing event and show camera, track, timestamp, and decision metadata.
4. Loitering: show a temporally confirmed loitering event; explain that confirmation suppresses single-frame noise.
5. Alert lifecycle: acknowledge an alert, close it, refresh, and show the durable state and audit record.
6. Evidence: open an authorized evidence item; an unauthenticated request must return 401.
7. Health/performance: show camera health, actual FPS, metrics, and offline buffer state.
8. ANPR, face, and night: label these honestly as functional/partial unless the demonstration uses approved labeled data. Do not quote an accuracy percentage.
9. Offline recovery: cite the automated real queue/reconnect integration test. A live outage drill should be rehearsed separately before judging.

## 6. Expected Results

- The finite video reaches normal EOF without an edge crash.
- YOLO produces supported person/vehicle detections and ByteTrack IDs.
- Confirmed rules create signed/encrypted evidence metadata, events, and alerts.
- The dashboard receives authenticated WebSocket updates and retains server state after refresh.
- Unauthorized protected API/media access is denied.

## 7. Recovery

- Backend unhealthy: close only the `NETRAKSH Backend` terminal, restart the launcher backend command, then check `/health` and `/ready`.
- Frontend unavailable: restart only `NETRAKSH Frontend`; backend/edge state remains durable.
- Edge reaches EOF: restart only the named edge terminal to replay the deterministic clip.
- Port occupied: identify the listener with `Get-NetTCPConnection`; do not kill a process until its command line confirms it belongs to NETRAKSH.
- Stale browser state: sign out/in and reload. Tokens are intentionally not placed in WebSocket URLs.
- Smoke failure: read the named failed check; the script does not modify data.

## 8. Shutdown

Close the four named launcher terminals or use Task Manager after verifying their NETRAKSH command lines. The launcher intentionally has no broad kill command. Do not delete `netraksh.db`, evidence, uploads, or the edge outbox as part of ordinary shutdown.

## Docker/PostgreSQL Validation Checklist

On a host with Docker Desktop/Compose:

1. Copy `.env.example` to an untracked `.env` and provision strong unique secrets, PostgreSQL credentials, model path, and edge certificate path.
2. Run `docker compose config`; verify no secret is expanded into a frontend build argument.
3. Run `docker compose build --no-cache`.
4. Run `docker compose up -d db minio migrate`; require healthy DB/MinIO and successful migration exit.
5. Run `docker compose up -d backend frontend edge` and inspect every container log.
6. Verify `alembic current` is the head revision, `/health` and `/ready` return 200, and all smoke checks pass through deployed URLs.
7. Create/login users, register a camera, ingest an event/evidence item, query analytics/audit/watchlist, then restart DB/backend and confirm persistence.
8. Run `alembic upgrade head` again to prove migration idempotency.
9. Confirm MinIO/PostgreSQL are not exposed beyond the intended host/network policy before deployment.

## Two-Camera Demo Layout

The Dashboard presentation surface is intentionally capped at `MAX_VISIBLE_CAMERAS = 2`; this is a UI/demo constraint only and does not remove or disable backend multi-camera ingestion, WebSocket routing, health, or event storage.

- **Camera 01 — Border Gate / Check Post** (`cam-border-01`): use the backend video/demo source to demonstrate person and vehicle detection, tracking, and any line-crossing or ANPR event that is actually emitted. The card shows the real camera id, location, health, FPS, track counts, and last update.
- **Camera 02 — Restricted Perimeter** (`cam-checkpoint-01`): use the registered checkpoint source to demonstrate person tracking, virtual-fence, and loitering events when emitted by the backend. Unsupported or unavailable analytics remain labelled `WAITING`, `N/A`, or `PARTIAL`.
- The two cards are side-by-side on desktop and stack on narrow screens. Operators can select any two registered backend cameras locally; no fake camera ids or synthetic detections are created.
- The unified **Latest Security Events** feed below the cards is limited to the newest ten verified backend events for the selected slots. Each row retains camera attribution and links to the authorized Evidence Vault workflow.
- WebSocket updates refresh the relevant card telemetry and event list without opening a popup for every event. Confirm the `SOCKET CONNECTED` header chip before starting the walkthrough.
- The card’s video area uses the currently supported upload/browser-playable demo source. Do not describe it as RTSP unless an approved RTSP gateway is deployed and verified for the specific camera.

## Continuous Demo Replay

Both judge-facing camera cards use finite prerecorded demonstration video. In explicit demo mode, local MP4/AVI/MOV sources automatically rewind at EOF and continue processing as an independent replay cycle. The adapter uses bounded reopen/rewind handling and resets only timeline-bound tracker and rule state; persisted alerts, evidence, users, camera registration, and configuration are retained.

The dashboard labels these sources **DEMO REPLAY** / **PRERECORDED DEMO**. This is a presentation mechanism and is not being presented as verified physical RTSP CCTV. RTSP, HTTP, USB, and other physical-camera sources retain normal disconnect/failure semantics and are never given finite-file looping behavior.

## Flexible One/Two Camera Operation

The dashboard derives its live scope from the selected/running camera slots; no separate mode switch is required.

### One-camera demo

1. Leave the unused slot as `NOT CONFIGURED`.
2. Click `＋ ADD VIDEO` on the desired slot and choose a supported local video.
3. Start/play the uploaded source. The selected slot becomes the single-camera scope.
4. Expect camera-specific telemetry, events, reliability values, and a corroboration message stating that a second source is required.

### Two-camera demo

1. Upload/start a source in Slot 1, then upload/start a source in Slot 2.
2. Both cards retain independent FPS, people, vehicles, tracks, health, source name, and latest-event values.
3. The event table becomes a unified feed with `ALL`, `CAM 1`, and `CAM 2` filters. Cross-camera analysis is shown only when two active sources exist and the backend supplies a real temporal/spatial match.

### Stop/restart behavior

Pause/stop a slot and its data is removed from the live dashboard scope without deleting persisted events or evidence. Starting the slot again creates a fresh source/session context; stale transient tracks and reliability selection are not reused. The other active slot continues without a page refresh.
## Cross-camera corroboration pane

For the SIH two-camera demonstration, select `cam-border-01` and
`cam-checkpoint-01` and start both prerecorded workers. The dashboard scopes
correlation to those active camera IDs and their current stream sessions. The
demo topology is explicit (80 m, expected travel time 8 s, admissible 0–16 s)
and the correlation window is 20 seconds; it is used because the demo camera
rows do not contain GPS coordinates.

The pane is intentionally explainable: it shows `MONITORING TWO CAMERAS` while
waiting, `CORROBORATED` with the paired event and elapsed time when the temporal
camera rule matches, and `NOT CORROBORATED` with a concrete reason for stale
sessions, incompatible event families, out-of-window events, or unrelated
cameras. It does not claim cross-camera identity or use a shared track ID as a
person key. The REST current-correlation endpoint is the recovery path when a
WebSocket update is missed.

## ANPR demonstration

The dashboard uses the enhanced ANPR path by default: vehicle track, the valid
repository `lpd_yunet.onnx` localizer, quality filtering, EasyOCR, confidence
gating, Indian plate normalization, and per-track temporal consensus. OCR is
sampled rather than run on every frame (`ANPR_FRAME_INTERVAL`, default `5`),
with `ANPR_OCR_MIN_CONFIDENCE=0.55` as the default acceptance threshold.

Each camera card shows a real plate read or `No plate read`. The
`RECENT NUMBER PLATE READS` table respects the active one/two-camera session
scope and ALL/CAMERA 1/CAMERA 2 filters. Historical operators can use the
protected `/events/anpr` endpoint. The repository vtest clip is suitable for
pipeline smoke testing but does not contain a labeled readable plate in the
executed segment, so do not present it as an accuracy benchmark. A confirmed
plate can optionally match the explicit `ANPR_WATCHLIST_PLATES` edge
configuration; low-confidence reads never alert.

## Face watchlist demonstration

Use an admin account to enroll a consented face image from the Watchlist page.
The backend accepts only a valid image under 2 MiB with exactly one detectable
face; add two or more varied reference images when available. The edge sync is
RBAC/edge-auth protected and retrains a fresh LBPH recognizer at startup and
periodically thereafter.

Start a person source in a verification zone and watch the camera card’s
`FACE WATCHLIST` row. It will show a real `MATCH · <label>`, `UNKNOWN`,
`INSUFFICIENT QUALITY`, or `No face evaluated`; it never fabricates a subject
name. The protected `/events/face` endpoint provides the bounded historical
view. The disclosed default threshold is `FACE_RECOGNITION_THRESHOLD=60.0`
(LBPH distance, lower is stronger). Unknown/low-quality results do not become
critical alerts, and a match is an investigative lead requiring human review.

The repository has no consented real-person fixture, so automated face
validation uses controlled synthetic crops for functionality and does not claim
recognition accuracy. Do not present those tests as a real-world benchmark.

## Night / Low-Light Demo

Night state is measured from each frame, not inferred from a demo toggle. Each
camera card reports `DAYLIGHT`, `LOW LIGHT`, or `VERY LOW LIGHT` plus the active
analytics method. With `ADVERSE_PROCESSING=adaptive` (the default), CLAHE is
used only on the detector input for measured low-light/adverse frames; original
frames remain the evidence source.

If YOLO has no reliable track in a low-light frame, the explainable motion
fallback requires a changed region of at least `NIGHT_MOTION_MIN_AREA=500` and
two consecutive observations (`NIGHT_MOTION_REQUIRED_FRAMES=2`). The dashboard
labels this as `LOW LIGHT MOVEMENT · MOTION FALLBACK`, never as confirmed person
intrusion. Static dark scenes should produce no motion event; a dark camera is
not automatically treated as failed unless the existing frozen/health checks
also fail.

The bounded repository validation uses synthetic brightness transforms of
`demo/videos/vtest.avi`. It validates routing and noise behavior only; there is
no labeled real-night dataset, so do not present it as night accuracy evidence.

## Security / Operational Notes

Use explicit frontend origins and non-default secrets outside development.
Video uploads are authenticated, streamed with a 200 MiB bound, and checked
against container signatures. Media is served only through authorized routes.
Webhook destinations are restricted to HTTP(S) hosts resolving to public
addresses unless explicitly allowlisted; signed deliveries carry a stable
event ID. Review the Health page before demonstrations. These are specific
controls, not a claim that the platform is hack-proof.

## Docker / Production-like Validation

The native Windows procedure remains the preferred SIH demo path because Docker
Desktop is not available in the current validation environment. On a clean
machine with Docker Desktop, copy `.env.example` to `.env`, set strong
`POSTGRES_*`, `SECRET_KEY`, `EDGE_AUTH_TOKEN`, MinIO credentials, and the model
path, then run `docker compose up -d --build`. Check `docker compose ps` and
`http://localhost/`; use `docker compose down` for normal shutdown. Do not use
`docker compose down -v` except when intentionally destroying database and
object-storage volumes. The containerized PostgreSQL, MinIO, two-worker,
restart, and browser flow remains pending execution and is documented as
BLOCKED BY TOOLING in the deployment validation report.

## RTSP / IP Camera Demonstration

NETRAKSH classifies `rtsp://` and `rtsps://` sources as live streams, separate
from replayable local files. The edge reader uses a bounded latest-frame queue,
stall detection, and reconnect backoff; it redacts credentials in logs. A real
RTSP-to-browser preview requires a controlled local RTSP server plus an
authenticated browser-compatible transport. Neither FFmpeg nor MediaMTX is
available on this validation host, so use the stable uploaded-video route for
the SIH demo until the documented localhost RTSP test is executed. Never put
CCTV URLs or credentials in the browser configuration.

## FINAL UI CHECK

## Judge-Day Clean Demo Environment

Judge day uses the isolated `data/demo/sih_demo.db` database. The development
forensic database is preserved under `data/archive/` and is never mixed into
the judge-day dataset. The clean database is created with the current Alembic
head, then normal application bootstrap seeds only the two required demo
cameras/zones (`cam-border-01` and `cam-checkpoint-01`). Evidence is generated
normally by the edge workers; no historical evidence is copied or rewritten.

Set `SIH_DEMO_ADMIN_PASSWORD`, `SIH_DEMO_OPERATOR_PASSWORD`, and
`SIH_DEMO_AUDITOR_PASSWORD` in the process environment, then run
`powershell -File scripts/reset_sih_demo.ps1` to archive any prior demo DB,
create a fresh migrated database, and bootstrap users. Passwords are not stored
in source or embedded in the reset script. Switch back to engineering analysis
by restoring the normal `DATABASE_URL`/environment and restarting the backend;
the archived development database remains available for forensic inspection.

Immediately before judges arrive, keep the native backend, frontend and both
named edge workers running. Log in as the prepared admin/operator and open:

1. `/` — BACKEND `HEALTHY`, SOCKET `CONNECTED`, both SIH slots `ONLINE`, fresh
   last-update ages, live events, reliability gates and a nonblank correlation state.
2. `/camera-health` — both demo cameras have recent health/FPS; old registered
   performance nodes are not described as active dashboard sources.
3. `/map` — expect `NO GEOLOCATION CONFIGURED` until real coordinates are saved.
4. `/cross-command-alerts` — real OPEN rows and severity/status filters.
5. `/evidence` — protected media, metadata, SHA-256 and Ed25519 on a preverified
   record. Disclose any pending/broken predecessor instead of claiming continuity.
6. `/watchlist` — real list or explicit empty state; enroll only a consented image.
7. `/analytics` — aggregates finish, a camera filter works, Export CSV is enabled.
8. `/audit` — recent real audit rows and filters.
9. `/performance` — measured CPU metrics and documented limits.
10. `/architecture` — latency points to Performance; Fabric is described as mock.
11. `/camera-management` — both demo cameras exist; do not change nodes mid-demo.

Finally return to `/`, refresh once, and confirm REST restoration plus WebSocket
reconnection. If a slot remains paused after reload, use its restored
`START / ANALYZE` button. If a worker is offline, restart only that named worker
and wait for fresh telemetry; never relabel stale values as live.
