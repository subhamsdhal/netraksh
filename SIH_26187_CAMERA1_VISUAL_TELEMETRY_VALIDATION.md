# SIH 26187 — Camera 1 Visual Telemetry Validation

Date: 2026-09-24  
Scope: `cam-border-01` with `demo/videos/vtest.avi` only. Camera 2 was not started.

## Implementation contract

- `edge.telemetry.build_frame_snapshot()` creates the single immutable current-frame object tuple after YOLO + ByteTrack.
- `edge.telemetry.render_snapshot()` draws exactly that tuple onto the annotated JPEG and derives its HUD summary from the snapshot properties.
- `edge.main.EdgePipeline` publishes the clean JPEG, annotated JPEG, identity, timestamps, objects, and P/V/T values from the same snapshot.
- `backend.api.system` stores frames by `(camera_id, analysis_session_id, frame_index)` and serves either the clean or annotated JPEG with no-cache semantics and identity/count response headers.
- `frontend/src/components/VideoFeed.jsx` requests the exact session/frame and accepts it only when `frameResponseMatchesTelemetry()` confirms session, frame, and P/V/T header equality.

ByteTrack output was checked against the installed Ultralytics implementation. Returned active tracks are filtered to current `frame_id`; NETRAKSH also rejects objects not marked `matched_current_frame` and de-duplicates track IDs before freezing the snapshot.

## Runtime reconciliation

The captured trace contained 2,428 snapshots across seven analysis sessions and six completed replay cycles at the time of reconciliation.

| Assertion | Result |
|---|---:|
| Rendered-person versus telemetry-person mismatches | 0 |
| Rendered-vehicle versus telemetry-vehicle mismatches | 0 |
| Rendered-unique-track versus telemetry-track mismatches | 0 |
| Frames containing duplicate track IDs | 0 |
| Lost, predicted-only, or non-current objects in snapshots | 0 |
| Non-increasing frame identities within a session | 0 |

Replay validation confirmed a new analysis-session identity and tracker reset at each boundary. The first snapshot in each new replay contained only the new replay's current-frame objects.

## Five selected annotated proof frames

Location: `artifacts/camera1_visual_validation_20260924/selected/`

| Frame | Rendered persons | Rendered vehicles | Rendered tracks | Telemetry persons | Telemetry vehicles | Telemetry tracks |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 2 | 5 | 3 | 2 | 5 |
| 34 | 4 | 2 | 6 | 4 | 2 | 6 |
| 75 | 5 | 2 | 7 | 5 | 2 | 7 |
| 123 | 7 | 2 | 9 | 7 | 2 | 9 |
| 167 | 7 | 2 | 9 | 7 | 2 | 9 |

These are detector/tracker observations, not human-ground-truth annotations. No manual count was substituted for model output.

## Browser verification

The authenticated live dashboard was tested against the running backend:

- HUD ON displayed the analyzed JPEG with bounding boxes, class names, track IDs, frame/session identity, and the P/V/T summary.
- HUD OFF visibly replaced it with the clean JPEG.
- HUD was restored ON for the Camera 1 demo default.
- The dashboard P/V/T row matched the same-sample HUD values.
- A stale or incomplete response-header set was rejected and produced the safe placeholder rather than a mismatched image/count pair.

## Automated verification

- Focused Python tests: 10 passed.
- Frontend tests: 19 passed across seven files.
- Frontend production build: passed.
- Python syntax compilation for changed backend/edge modules: passed.

## Acceptance state

Engineering validation is complete. Camera 1 is intentionally not declared accepted; final acceptance remains pending the user's manual screenshot inspection.
