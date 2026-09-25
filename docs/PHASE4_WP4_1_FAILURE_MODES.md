# Phase 4 WP-4.1: Failure Modes

This document catalogues expected failure modes in edge video ingestion and how the WP-4.1 architecture mitigates them.

## 1. Network Jitter & Missing Frames
- **Symptom**: `_cap.read()` occasionally returns `False` or drops frames.
- **Mitigation**: The adapter immediately recognizes a `False` return as a stream disconnect (or end of file), transitions to `STALLING`, releases the decoder, and enters the `RECONNECTING` backoff loop.

## 2. Silent Stalls (RTP Packet Loss)
- **Symptom**: The TCP connection remains open, but RTP streaming has halted. `_cap.read()` blocks indefinitely inside OpenCV.
- **Mitigation**: The background reader thread monitors `time.time() - last_frame_time`. Once it exceeds `FRAME_STALL_TIMEOUT_SECONDS`, the thread unilaterally declares a `STALLING` state, drops the decoder handle, and begins reconnecting.

## 3. Decoder Exception
- **Symptom**: Underlying FFmpeg or GStreamer library throws an exception up through OpenCV Python bindings.
- **Mitigation**: A `try/except` block wraps the `read()` call in the reader thread. Exceptions do not crash the pipeline; they are caught, logged, and treated as a read failure (transition to `STALLING` -> `RECONNECTING`).

## 4. Initialization Failure (Bad Credentials/Host Down)
- **Symptom**: `cv2.VideoCapture(src)` fails immediately or `isOpened()` returns `False`.
- **Mitigation**: Transitions from `INITIALIZING` to `RECONNECTING`. Exponential backoff begins. The edge pipeline remains alive, polling the adapter, emitting `FAILED` telemetry until the camera comes online.

## 5. Main Pipeline Blocking (CPU Exhaustion)
- **Symptom**: Without frames, the pipeline spins at 100% CPU.
- **Mitigation**: `get_frame(timeout=0.1)` enforces a bounded wait. If the queue is empty, the pipeline uses the timeout to yield CPU time, allowing background threads (health, telemetry, sync) to execute without starvation.

## 6. Shutdown Hangs
- **Symptom**: OpenCV blocks on `cap.release()` or a native call.
- **Mitigation**: The reader thread uses a timeout `join(timeout=5.0)`. If the thread fails to join, the shutdown process logs the error and proceeds, preventing a permanent zombie process lockup. Native decoder blocking is a known limitation of OpenCV/FFmpeg.
