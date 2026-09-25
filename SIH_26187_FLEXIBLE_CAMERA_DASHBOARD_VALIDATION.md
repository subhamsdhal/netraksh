# SIH-26187 Flexible Camera Dashboard Validation

## Source Upload

The existing authenticated upload flow remains the source of truth. A selected file is uploaded to the backend, receives a server-generated session/source id, and is then assigned to the selected camera slot for analysis. Arbitrary browser filesystem paths are never sent to edge workers.

## Camera 1 Independent Start

Slot 1 can be selected independently and its live scope is derived from `cam-border-01` telemetry. Slot 2 may remain `NOT CONFIGURED`; no fake FPS, tracks, or events are rendered for it.

## Camera 2 Independent Start

Slot 2 has equivalent upload/selection behavior and can be the only active scope. Backend scenario/session payloads now accept `camera_id`, and edge demo polling requests camera-scoped state.

## Dual Camera Operation

When both slots are active, the dashboard enters `DUAL` mode, keeps per-camera telemetry separated, and exposes the unified event stream with `ALL`, `CAM 1`, and `CAM 2` filters.

## Single Camera Event Filtering

The live event scope is filtered by the active slot set before display. In `SINGLE` mode, persisted events from inactive cameras are excluded from the current dashboard timeline.

## Dual Camera Event Filtering

In `DUAL` mode, `ALL` shows both active cameras; camera filter buttons select one camera without changing backend persistence. Inactive historical cameras remain excluded.

## Reliability Analysis

The reliability panel follows the active camera. In dual mode, a camera selector chooses the latest real event for Gate 1/2/3 values; if no current decision exists, the panel shows an awaiting state instead of stale data.

## Cross-Camera Behavior

Corroboration is enabled only in `DUAL` mode and still requires a real backend temporal/spatial match. In empty/single mode the panel explicitly says a second active source is required.

## Balanced Layout Verification

The analytics area now uses equal responsive grid columns. Cross-camera corroboration and the judge-facing active fleet-health summary occupy the left column; reliability and decision details occupy the right column. The legacy oversized fleet card is hidden from the right column. At narrow widths the grid collapses to one column and camera cards stack.

## WebSocket Verification

REST remains the initialization path and WebSocket remains the incremental path. Incoming telemetry/events are filtered against the current active camera set, so changing slot scope does not require a page refresh.

## Source Replacement

Uploading a new source clears the transient dashboard state and records the new server session/source name. Existing persisted evidence/events are not deleted. The backend now stores optional per-camera session/scenario state so the same camera id can represent a new uploaded run.

## Tests

- Frontend: 6 Vitest files, 13 tests passed.
- Frontend production build: passed; Vite reports only the existing large-chunk warning.
- Python syntax check: backend dashboard/demo APIs and edge demo runner passed `py_compile`.
- Prior focused edge regression suite: 15 tests passed.

## Remaining Limitations

- The current upload API still has one browser preview surface; independent edge source control is camera-scoped, while a full production deployment should expose a durable per-camera upload/session registry rather than the in-memory local demo state.
- A local stop currently pauses the camera-scoped demo scenario; a production supervisor should terminate/release a dedicated worker process through an authenticated lifecycle service.
- Physical RTSP/USB validation remains separate from prerecorded demo replay.
- Under sustained inference/event backlog, telemetry can briefly appear stale before the next WebSocket snapshot arrives; the dashboard labels this state rather than fabricating freshness.

## Live Browser Scenarios

- Scenario A (one camera): PASS — selecting `Not connected` for Slot 2 immediately rendered `CAMERA SLOT 2 · NOT CONFIGURED`, `WAITING FOR SOURCE`, no fake metrics, and single-camera corroboration messaging.
- Scenario B (add second camera): PASS at the UI scope level — restoring Slot 2 exposes the second independent card and dual-mode controls without a refresh; live edge source startup remains dependent on the authenticated upload/analyze session.
- Scenario C (return to one camera): PASS — stopping/deselecting a slot clears it from the active set and returns the dashboard to single/empty scope without deleting persisted events.
- Scenario D (source replacement): PASS for the upload/session reset path in code and tests; full two-browser-source playback requires a durable per-camera media-preview service, documented above.
