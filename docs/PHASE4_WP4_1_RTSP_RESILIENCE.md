# Phase 4 WP-4.1: RTSP Resilience

## Architecture

This document describes the stream reader architecture designed for unreliable real-world CCTV/RTSP networks.

### Reader Thread Decoupling
The core of the resilience architecture isolates video ingestion into a background `CameraReader` thread. 
- The main pipeline thread (`EdgePipeline._run_frame_loop`) uses a non-blocking `get_frame(timeout)` to fetch frames.
- If the stream hangs or is disconnected, the main pipeline remains alive, continuing to emit health telemetry, process events, and verify events.
- Single-camera process isolation is preserved. If the stream disconnects, the edge worker does not crash.

### Bounded Queue
The reader thread pushes frames into a thread-safe `queue.Queue`.
- The maximum depth is configurable (default 30).
- **DROP_OLDEST policy**: If the queue fills up because the inference pipeline is slower than the ingestion FPS, the reader thread drops the oldest unconsumed frame to make room for the newest frame. This ensures inference always acts on real-time data instead of processing an accumulating stale backlog.

### Reconnect Strategy
A robust recovery policy is implemented:
- Uses bounded exponential backoff.
- Configurable base delay (default `MIN_RECONNECT_DELAY=2.0s`) and max delay (default `MAX_RECONNECT_DELAY=60.0s`).
- Jitter is added (`random.uniform(0, 1.0)`) without allowing the total delay to exceed `MAX_RECONNECT_DELAY`.
- The retry counter resets immediately upon the first successful frame acquisition.

### Stall Detection
`cv2.VideoCapture` can hang indefinitely when RTP packets stop arriving.
- The reader thread tracks `last_frame_time`.
- If `time.time() - last_frame_time > FRAME_STALL_TIMEOUT_SECONDS`, a stall is declared.
- The decoder is explicitly released and the state transitions to `RECONNECTING`.
- This timeout logic is only armed *after* the first frame is received successfully, preventing false-positive stall detection during slow initial connections.

### URL Sanitization
Credentials in the video source string are stripped via `sanitize_url()` using regex (`re.sub(r'(?<=://)[^/:]+:[^/@]+@', '***:***@', url)`) before any logging or telemetry, preventing secret leakage.

### Offline Resilience
The ingestion logic is decoupled from backend connectivity. The stream reader continues capturing frames and inserting them into the pipeline, which buffers them locally as evidence packages in the sync queue, even if the central command backend is completely offline.
