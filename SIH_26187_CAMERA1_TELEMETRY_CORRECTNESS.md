# SIH 26187 — Camera 1 Telemetry Correctness

## Scope and original defect

Camera `cam-border-01` was reproduced with `demo/videos/vtest.avi`. The dashboard rendered an independently clocked HTML5 video while the edge process decoded and analyzed the same file through OpenCV. Counts therefore could not be truthfully compared with the visible browser frame. The three displayed counts were also inferred again in React from the track array instead of being explicit fields from one edge-produced analyzed-frame sample.

`TRACKS` was not hardcoded as `PERSONS + VEHICLES`. It was `telemetry.tracks.length`. Because the detector intentionally admits only COCO person and vehicle classes, the equality was expected, but the UI did not prove unique current ByteTrack IDs or expose the distinction.

## Corrected value sources

- Old `PERSONS`: React filtered `telemetry.tracks` by a string containing `person`.
- New `PERSONS`: edge-produced `person_count`, counting unique current-frame active tracker IDs whose normalized class is exactly `person`.
- Old `VEHICLES`: React filtered `telemetry.tracks` by a string containing `vehicle`.
- New `VEHICLES`: edge-produced `vehicle_count`, counting unique current-frame active tracker IDs mapped from intended COCO classes car (2), motorcycle (3), bus (5), and truck (7).
- Old `TRACKS`: `telemetry.tracks.length`.
- New `TRACKS`: edge-produced `track_count = len(unique active tracker IDs)` from the current ByteTrack output. It is not calculated from the other counters.
- Lost/historical tracks are excluded because only the current `BYTETracker.update()` output enters the snapshot. Defensive ID deduplication prevents continuity re-association duplicates from inflating the total.

The telemetry packet now carries `frame_index`, source and processed timestamps, measured processing FPS, expected interval, raw detector outputs, tracker output IDs, unique active IDs, all three counts, tracks, and analysis-session identity as one atomic object.

## Preview synchronization

The previous browser preview and AI pipeline had separate clocks. The edge now JPEG-encodes the exact frame passed through analysis and uploads it before its telemetry packet. The backend retains only four exact frames per camera in memory, keyed by camera, analysis session, and frame index. The authenticated frontend fetches that exact key and renders it ahead of the independent video element.

The existing HUD toggle now shows boxes, class/track labels, frame index, source time, and the explicit person/vehicle/track counts on that analyzed frame. There is no unbounded frame queue.

## Ordering, replay, and lifecycle

- Backend and frontend reject older frames within the same session.
- A delayed packet from an older analysis session cannot replace a newer session.
- A looping file rotates `stream_id`/analysis-session identity at the replay boundary, clears telemetry queue/cursors, and resets tracker/transient rule state.
- A stale browser upload/session can no longer pause or seek a dedicated looping Camera 1 worker.
- `LAST UPDATE` is based on browser receipt of the newest telemetry sample. Freshness uses three measured processing intervals plus a one-second margin, bounded to 5–15 seconds; offline is at least 30 seconds. Counts become `N/A` outside LIVE state.
- `LATEST EVENT` is restricted to the current camera and current analysis session and includes age/time. With no current-session event it reads `None recorded`.
- FPS is the pipeline's measured processed-frame rate, not declared source FPS.

## Same-frame validation

Final trace: `artifacts/camera1_telemetry_trace_final_20260924.jsonl`.

- Samples checked: 293 (requirement: at least 30)
- Samples with analyzed preview available: 293
- Person-count mismatches: 0
- Vehicle-count mismatches: 0
- Unique-track-count mismatches: 0
- Observed measured processing FPS after warm-up: up to 14.04 FPS (initial samples truthfully report 0 while the rolling measurement is not yet established)

First ten samples:

| Frame | Source s | Raw detections | Tracker outputs | Persons | Vehicles | Unique tracks | Active IDs |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 0.0 | 5 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 2 | 0.1 | 5 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 4 | 0.3 | 5 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 6 | 0.5 | 5 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 8 | 0.7 | 5 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 10 | 0.9 | 5 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 12 | 1.1 | 6 | 5 | 3 | 2 | 5 | 1,2,3,4,5 |
| 14 | 1.3 | 6 | 6 | 4 | 2 | 6 | 1,2,3,4,5,7 |
| 16 | 1.5 | 6 | 6 | 4 | 2 | 6 | 1,2,3,4,5,7 |
| 18 | 1.7 | 7 | 6 | 4 | 2 | 6 | 1,2,3,4,5,7 |

The dashboard values are the explicit fields in these same packets; the frontend no longer recomputes them from separately timed state.

## Verification

- Focused Python telemetry/backend tests: 8 passed.
- Frontend tests: 17 passed across 6 files.
- Frontend production build: passed.
- Python syntax compilation: passed.
- Live analyzed-frame uploads: HTTP 202 from the updated backend.
- Camera 2 was not started.
- Camera 1 and the validation backend were stopped after capture.

## Remaining model limitation

The correction guarantees frame/count identity, not perfect object recognition. YOLO may still miss a visible person or vehicle, and ByteTrack may withhold a raw detection until it is confirmed. The raw-vs-tracker difference is now visible in trace data rather than hidden or compensated with fabricated counts. Final visible-box comparison remains for the user's manual browser retest.

## Status

Waiting for user manual verification. This report does not declare overall NETRAKSH readiness.
