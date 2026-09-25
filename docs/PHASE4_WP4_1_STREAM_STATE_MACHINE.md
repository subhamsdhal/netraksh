# Phase 4 WP-4.1: Stream State Machine

The ingest lifecycle is managed by an explicit state machine inside `CameraAdapter`.

## States

1. **INITIALIZING**: The adapter is attempting its first connection to the stream.
2. **CONNECTED**: The stream is open, and frames are successfully arriving.
3. **STALLING**: The connection is technically open, but no frames have been received within `FRAME_STALL_TIMEOUT_SECONDS`.
4. **RECONNECTING**: The adapter is actively applying exponential backoff and attempting to recover the connection.
5. **FAILED**: The recovery policy exhausted all attempts (if bounded). The stream is currently unavailable.
6. **STOPPED**: A commanded shutdown via `stop()`.

## State Transitions

### Valid Transitions

- `INITIALIZING -> CONNECTED` (First frame received successfully)
- `INITIALIZING -> RECONNECTING` (Connection failed to open)
- `CONNECTED -> STALLING` (Frame stall timeout reached or read returned False)
- `CONNECTED -> STOPPED` (Commanded shutdown)
- `STALLING -> RECONNECTING` (Decoder released, recovery begins)
- `STALLING -> STOPPED` (Commanded shutdown)
- `RECONNECTING -> CONNECTED` (Recovery successful)
- `RECONNECTING -> FAILED` (Max attempts reached)
- `RECONNECTING -> STOPPED` (Commanded shutdown)
- `FAILED -> RECONNECTING` (Manual intervention or configuration change)

## Health Mapping

This state machine feeds directly into the `CameraHealthMonitor` (Gate 1), ensuring the backend is instantly aware of ingestion layer faults:

- **CONNECTED** -> `HEALTHY`
- **STALLING** -> `DEGRADED`
- **RECONNECTING** -> `DEGRADED`
- **FAILED** -> `FAILED`
- **INITIALIZING** / **STOPPED** -> `DEGRADED` (Stream unavailable)
