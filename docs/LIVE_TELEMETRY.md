# Live Telemetry

## Purpose
The Live Telemetry feature provides a real-time visualization of tracked objects directly on the dashboard's video feed. It completely decouples bounding box rendering from the heavier security event and reliability pipeline, ensuring that operators can see objects moving fluidly without waiting for security events (e.g., LOITERING, INTRUSION) to trigger.

## Architecture
```text
YOLOv8 + ByteTrack
        │
        ├── Security/Event Pipeline
        │
        └── Live Telemetry @ 10 FPS (edge/main.py)
                 │
                 ▼
          Latest-Only Queue
                 │
                 ▼
        POST /system/telemetry (backend/api/system.py)
                 │
                 ▼
          Backend WebSocket (backend/api/websocket.py)
                 │
                 ▼
          React live_telemetry (frontend/src/hooks/useWebSocket.js)
                 │
                 ▼
             VideoFeed (frontend/src/components/VideoFeed.jsx)
```
Live tracking and security events are intentionally separate systems. Live telemetry is ephemeral, unauthenticated (in local demo mode), and never saved to the database.

## Telemetry Payload and Coordinate Format
The payload contains a timestamp, sequence number, and a list of tracks.
Each track contains a stable `track_id`, `detection_class`, `confidence`, and bounding box coordinates: `bbox_x`, `bbox_y`, `bbox_w`, `bbox_h`.

**Coordinate Format:** The bounding box coordinates are completely normalized `[0,1]` relative to the original video frame width and height. 

## Telemetry Frequency and Backpressure Strategy
- **Frequency:** The default edge sampling rate is `10 FPS` (100ms interval).
- **Queue/Backpressure Strategy:** The edge uses a **Latest-Only** queue strategy. If the backend or network is slow and the queue fills up, the edge explicitly pops and drops the *oldest* payload to make room for the newest. This ensures that the frontend always receives the most current state, avoiding rubber-banding or delayed visual lag.

## Track Lifecycle and Stale-Track Behavior
1. **Creation:** A track is created immediately when ByteTrack confirms it.
2. **Persistence:** The `track_id` remains stable even through brief occlusions.
3. **Stale-Track Expiration:** To handle disappeared objects or dropped network packets, the frontend React component utilizes `Date.now()` on local receipt. Any track that does not receive an update within **500ms** is automatically purged from the UI, preventing "ghost" or frozen boxes.

## Configuration
- `TELEMETRY_FPS`: Configurable environment variable in the edge process (default: `10`). Setting this to 0 disables telemetry entirely.

## Troubleshooting
- **Bounding Boxes Missing:** Ensure `TELEMETRY_FPS > 0`. Check network connectivity between edge and backend. 
- **Ghost Boxes:** Verify the client's system clock isn't drifting significantly, though the 500ms timeout relies purely on local `Date.now()` diffs.
- **Misaligned Boxes:** Ensure the video aspect ratio hasn't been warped by CSS without `object-fit: cover`. The React component uses `ResizeObserver` mathematics to map the `[0,1]` normalized coordinates correctly over cropped video elements.
