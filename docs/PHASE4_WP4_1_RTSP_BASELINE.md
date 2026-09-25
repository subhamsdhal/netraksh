# Phase 4 WP-4.1: RTSP Ingestion Forensic Baseline

## Current Architecture

The edge video ingestion is handled by `edge/ingestion/camera_adapter.py` (`CameraAdapter`) which is consumed by `edge/main.py` (`EdgePipeline`).

### 1. RTSP URL Handling & OpenCV VideoCapture
- `CameraAdapter` takes a `source` string (defaulting to `VIDEO_SOURCE` env var).
- It calls `cv2.VideoCapture(src)` synchronously in `open()`.
- It does NOT sanitize or redact credentials from the `VIDEO_SOURCE` string when logging: `logger.info(f"Camera opened: source={self.source_str}...")`.

### 2. Read Loop & Frame Buffering
- **Synchronous**: The `frames()` generator calls `_cap.read()` synchronously.
- **No Background Thread**: The reading happens entirely within the main pipeline thread (`_run_frame_loop` in `main.py`).
- **Blocking**: If `_cap.read()` blocks due to network jitter or a stalled RTSP stream, the **entire edge pipeline freezes**. The pipeline cannot send health telemetry, run sync, or process other events while blocked.
- **No Queue/Buffering**: Because reading is synchronous, there is no frame queue, no bounded buffer, and no drop policy. The pipeline processes whatever frame `read()` returns next.
- **Pacing**: It implements a naive pacing mechanism: if ahead of real time, it calls `time.sleep()`. If behind real time, it drops the frame and immediately loops `continue` to catch up.

### 3. Reconnect Logic & Timeout Behavior
- **NONE**: There is no reconnect logic. If `_cap.read()` returns `False` (stream ended or disconnected), the adapter attempts to loop the video by setting the position to 0 (for `.mp4` demos). If that fails, it logs a warning and breaks the loop.
- **Result**: The pipeline thread exits `_run_frame_loop()`, and the edge process effectively stops processing video permanently until manually restarted.

### 4. Stall Detection
- **NONE**: OpenCV `VideoCapture` on RTSP can sometimes hang indefinitely if the TCP connection remains open but RTP packets stop arriving (depending on backend FFmpeg/GStreamer configurations). Since the read is synchronous and blocking, there is no timeout or stall detection.

### 5. Camera Health State
- The `CameraHealthMonitor` (Layer 2, Gate 1) evaluates blur, exposure, and frame variance.
- It is updated synchronously *after* a frame is successfully read.
- If the stream stalls or disconnects, `CameraHealthMonitor` is **never updated** because no new frames arrive. It will never transition to `FAILED` due to a disconnect; it will just stop reporting.

### 6. Exception Handling & Decoder Errors
- `CameraAdapter.frames()` does not wrap `_cap.read()` in a try/except block.
- Any exception thrown by OpenCV will bubble up and crash `_run_frame_loop()`.

### 7. Camera Isolation
- `EdgePipeline` currently only supports **one camera per process**. It uses `config["camera_id"]` and initializes exactly one `CameraAdapter`.
- A failure of this single camera halts the entire pipeline for that edge process.

### 8. Worker Lifecycle & Shutdown
- `EdgePipeline.start()` sets `self._running = True` and enters `_run_frame_loop()`.
- `EdgePipeline.stop()` sets `self._running = False`. The loop checks this flag every frame.
- However, if the pipeline is blocked in `_cap.read()`, `stop()` will not take effect until `read()` unblocks.
- `finally` block in `start()` calls `self.adapter.release()` cleanly.

## Critical Gaps for Real-World RTSP

1. **Blocking Read**: The synchronous `read()` is a fatal flaw for unreliable networks. It must be moved to a background thread to allow stall detection and independent pipeline operation.
2. **Missing Reconnect**: The pipeline dies immediately on disconnect. It needs bounded exponential backoff recovery.
3. **Missing Stall Detection**: A hung stream will freeze the edge node indefinitely.
4. **Credential Leak**: RTSP URLs with `rtsp://user:pass@host` are logged in plaintext.
5. **False Health Reporting**: Health monitoring freezes when the stream freezes, failing to alert the backend of the outage.
