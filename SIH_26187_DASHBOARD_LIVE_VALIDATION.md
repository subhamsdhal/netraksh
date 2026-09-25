# SIH-26187 Dashboard Live Validation

## FULL DASHBOARD LIVE VALIDATION COMPLETED

Validation date: 2026-09-23. The local SIH stack was exercised end-to-end with two dedicated replay workers using `demo/videos/vtest.avi`.

## Backend

PASS — `http://127.0.0.1:8443/health` returned `status=ok`; `/ready` returned `status=ready`, `database=connected`, and `storage=configured`.

## Frontend

PASS — Vite served `http://127.0.0.1:5173/`; production build completed successfully. The browser showed `BACKEND HEALTHY`, `SOCKET CONNECTED`, and live telemetry.

## Camera 1

PASS — `cam-border-01` / Border Gate reported `ONLINE`, `TELEMETRY LIVE`, `DEMO REPLAY`.

FPS: 9.76 observed in the camera card.

detections: 6 persons, 2 vehicles, 8 active tracks; latest event observed: `LOITERING`.

latest telemetry: frame dimensions and telemetry age were populated; updates were under one second at capture time.

## Camera 2

PASS — `cam-checkpoint-01` / Restricted Perimeter reported `ONLINE`, `TELEMETRY LIVE`, `DEMO REPLAY`.

FPS: 9.77 observed in the camera card.

detections: 6 persons, 2 vehicles, 8 active tracks; latest event observed: `VIRTUAL FENCE CROSSING`.

latest telemetry: frame dimensions and telemetry age were populated; updates were under one second at capture time.

## Root Causes Found

- The checked-in launcher selected a stale/broken virtual environment and did not provide a Windows runtime repair path.
- Dedicated demo workers could inherit a stale browser upload session, causing them to open `uploaded_demo.mp4` instead of the labelled SIH clip.
- Local finite-file replay had no explicit boundary/reset contract, allowing tracker and rule state to leak across cycles.
- Dashboard event hydration and telemetry refresh were filtered by the stale browser session, so real dedicated-worker data could appear empty after reload.
- Camera-card FPS/count rendering did not consistently fall back to live health telemetry.

## Data Flow Repairs

The validated path is:

`vtest.avi` → `CameraAdapter` → detector/ByteTrack/rules → edge REST (`/system/telemetry`, `/events`, evidence) → backend persistence and WebSocket broadcast → React `useWebSocket` → two SIH camera cards, event table, reliability panel, and corroboration panel.

`source_kind`, `demo_replay`, `replay_cycle`, and `replay_boundary` now travel with telemetry. A replay boundary resets transient trajectories, continuity guards, tracker state, and rule/verifier state before the next cycle.

## Edge Worker Status

PASS — two Python 3.12 workers remained alive during validation (PIDs 12556 and 17040):

- `cam-border-01`, `DEMO_LOOP_VIDEO=true`
- `cam-checkpoint-01`, `DEMO_LOOP_VIDEO=true`

Worker logs showed successful model warmup, ByteTrack activity, `POST /system/telemetry 202`, `POST /events 201`, evidence `201`, and replay-cycle reset messages.

## REST Verification

PASS — health/readiness endpoints returned the responses above. Edge logs showed repeated successful telemetry, event, evidence, and internal-sync HTTP calls while the browser was open.

## WebSocket Verification

PASS — browser header showed `SOCKET CONNECTED`; live telemetry timestamps advanced and camera-card values changed without a page refresh. Initial REST hydration was also verified after reload.

## Reliability Pipeline Verification

PASS — the Reliability Decision panel displayed a real `[ DETECTED ]` decision with Gate 1/Gate 2/Gate 3 values, including an observed score such as `R=0.779`, threshold `0.750`, and the honest `DEGRADED camera context` flag. No UI values were fabricated.

## Latest Security Events Verification

PASS — the unified event table showed the latest ten real rows with camera attribution, event type, decision state, severity, and open evidence links. Camera 1 and Camera 2 latest-event labels matched the live cards.

## Cross-Camera Corroboration Verification

PASS — the panel remained honest and displayed `NO CORROBORATION / INSUFFICIENT EVIDENCE` because no spatially and temporally plausible qualifying pair was present during this run. The UI did not manufacture a correlation.

## Camera Telemetry Verification

PASS — both cards rendered live FPS, person count, vehicle count, track count, replay badge, status, latest event, and last-update age. The top live strip now also falls back to health FPS when the metrics timestamp is not fresh.

## Replay Verification

PASS — local finite-file replay is opt-in and bounded: only local finite sources rewind; RTSP/HTTP/USB sources do not. Rewind failure is bounded and transitions the adapter to `FAILED`. The live logs observed replay cycles and transient-state resets.

## Browser Walkthrough

1. Open `/` and select the two SIH demo slots.
2. Confirm `BACKEND HEALTHY`, `SOCKET CONNECTED`, and `TELEMETRY LIVE`.
3. Click `Normal Ops` if the scenario is paused.
4. Verify both camera cards show `ONLINE`, `DEMO REPLAY`, FPS, detections, tracks, and latest event.
5. Scroll to Latest Security Events, Reliability Decision, and Cross-Camera Corroboration.
6. Open an evidence link from the event table; leave the browser in the live state for the SIH walkthrough.

## Tests

- Frontend Vitest: `8 passed`.
- Frontend production build: passed (Vite bundle-size warning only).
- Focused backend/edge tests: `15 passed` (`test_wp4_1_rtsp_resilience.py`, `test_continuity_regression.py`).
- Python syntax/import validation: passed with Python 3.12, OpenCV 4.10, `cv2.face`, FastAPI, and Ultralytics available.

## Remaining Limitations

- The browser does not directly play the AVI edge source; when no browser-uploaded playable media exists, the card intentionally says `TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL` rather than pretending a video stream exists.
- The observed inference rate is approximately 9.8 FPS and reliability may be `DEGRADED` against a 30 FPS target; this is surfaced honestly.
- A pending event backlog can be visible while both workers are active. It did not prevent REST persistence, WebSocket updates, or rendering, but production deployment should size the queue/worker pool for the target throughput.
- Under sustained replay load, the browser can briefly show `STALE` (roughly 7–13 seconds) while the edge queue drains; the underlying workers continue producing telemetry and the next fresh session repopulates both cards.
- Cross-camera corroboration remains data-dependent and will stay empty until the backend receives a qualifying pair.
