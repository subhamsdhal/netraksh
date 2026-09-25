# SIH-26187 Cross-Camera Corroboration Validation

## Existing Root Cause

The pane was not failing because of the React layout. The persisted demo cameras
`cam-border-01` and `cam-checkpoint-01` had no GPS coordinates, and the previous
correlator returned `INSUFFICIENT_EVIDENCE` before it could inspect the second
camera. The UI therefore had a real negative result to display, but no useful
reason or live state model.

## Camera IDs

The SIH pair is explicitly scoped to `cam-border-01` and `cam-checkpoint-01`.
Both cameras are active in the database and are selectable as the two dashboard
sources.

## Active Session Filtering

The API accepts current `stream_ids`, and candidate selection keeps only the
latest stream for each active camera. Older events from a previous worker run
are rejected as `STALE_SESSION`; a camera-local track ID is never treated as a
cross-camera identity key.

## Correlation Rules

Correlation is explainable temporal-camera plausibility, not biometric Re-ID:
the active cameras must be related, event types must be compatible, the event
times must fall inside the configured window, and the elapsed time must fit the
configured movement interval. The result is persisted symmetrically on both
events.

## Temporal Window

The SIH topology uses a 20-second correlation window (`CROSS_CAMERA_CORRELATION_WINDOW_SECONDS`, default `20`).
The configured border/checkpoint movement rule is 80 m, expected travel time 8 s,
with a 0–16 s admissible interval.

## Camera Relationship

`backend/services/camera_topology.py` contains the reviewable demo relationship:
`cam-border-01 <-> cam-checkpoint-01`, distance 80 m, expected travel time 8 s,
tolerance 8 s. This is an explicit demo topology because these camera rows do
not carry coordinates; production deployments can replace it with persisted
adjacency/topology configuration.

## Event Compatibility Matrix

`LINE_CROSSING`, `VIRTUAL_FENCE_CROSSING`, and `INTRUSION` share the
`PERIMETER_ACTIVITY` family. `LOITERING` and `INTRUSION` share
`PERSISTENT_PRESENCE`. If no family applies, the safe fallback requires the
same detection class. No track ID or appearance embedding is required.

## API Contract

`GET /events/correlation/current?active_camera_ids=cam-border-01,cam-checkpoint-01&stream_ids=...`
returns the current primary event, status, active camera IDs, window, reason,
and (when present) the secondary event, camera, time delta, and correlation
method `TEMPORAL_CAMERA_RELATION_RULE`. It reports actionable states including
`WAITING_FOR_SECOND_CAMERA`, `OUTSIDE_TIME_WINDOW`, `INCOMPATIBLE_EVENT_TYPES`,
`STALE_SESSION`, `CAMERAS_NOT_RELATED`, and `CORROBORATED`.

## WebSocket Contract

Event ingestion emits a typed `correlation` message containing the status,
primary/secondary event and camera IDs, time delta, and window. The dashboard
consumes this as a fast path and polls the current-correlation endpoint as a
recovery path.

## Browser Panel States

The pane now distinguishes: one/zero active sources (`REQUIRES TWO ACTIVE
CAMERA SOURCES`), two-camera waiting (`MONITORING TWO CAMERAS`), actionable
rejections (`NOT CORROBORATED · <reason>`), and a genuine match (`CORROBORATED`)
with the camera pair, rule match, and elapsed time. It never claims identity.

## Live Candidate Evaluation

Persisted evidence contained real events from both cameras:

- Border: `f5fbd7cc-7629-42d4-a68a-b7889df278d4`, `LINE_CROSSING`,
  `2026-09-23 08:14:05.271703`, stream `e378fb4c-7af9-4a70-ac8d-a67f1771ff28`.
- Checkpoint: `2fdd8812-0da1-412b-ba09-3cfcb8715ddc`, `LINE_CROSSING`,
  `2026-09-23 08:13:56.971252`, stream `d0bfb316-d12e-40e1-ae9d-297cc9f8f993`.

Their timestamp delta is 8.300451 s, inside the configured 0–16 s movement
interval and 20 s window.

## Genuine Corroborated Event

Running the correlator against those persisted rows produced `CORROBORATED`,
secondary event `2fdd8812-0da1-412b-ba09-3cfcb8715ddc`, distance 80 m, expected
time 8 s, and Tc `0.963140119`. Applying the result persisted symmetric
`CORROBORATED` annotations and the two event IDs in SQLite. This is existing
camera evidence, not a fabricated event or Re-ID claim.

## Tests

- Cross-camera and Re-ID unit suites: **24 passed**.
- Frontend dashboard suite: **13 passed** (6 files).
- Vite production build: **passed**.
- Python compilation for the changed correlation/API modules: **passed**.

## Remaining Limitations

The SIH relationship is an explicit 80 m/8 s demo topology, not a surveyed
map-derived route. Physical RTSP deployment still depends on worker/network
availability, and the browser must be connected to a backend process that has
loaded the current code. Corroboration remains plausibility evidence and must
not be presented as biometric identity.
