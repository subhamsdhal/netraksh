# Architecture

The edge `CameraAdapter` classifies local finite files, RTSP/RTSPS, HTTP
streams, and USB cameras. A background reader owns `cv2.VideoCapture`, pushes
frames to a bounded drop-oldest queue, and feeds `EdgePipeline`; telemetry then
travels through the existing backend/WebSocket path.

# RTSP Source

No controlled server was run. `ffmpeg`, `mediamtx`, and `rtsp-simple-server`
are not installed or discoverable on this host. No LAN or external camera was
probed.

# Source Classification

`rtsp://`/`rtsps://` are RTSP, local video extensions are finite replayable
files, HTTP(S) is an HTTP stream, and numeric/webcam values are USB cameras.
RTSP does not use finite-file rewind behavior.

# Timeout Policy

The adapter has bounded frame-stall detection and join timeout; reconnect delay
is configurable with minimum/maximum backoff. OpenCV transport-open timeout is
not independently verified because a local RTSP server was unavailable.

# Reconnect Policy

Failed read/stall transitions release the capture, mark reconnecting, and retry
with bounded exponential backoff/jitter. Local-file EOF is handled separately.
Unit tests verify reconnect behavior with controlled capture doubles.

# Credential Protection

Adapter log output redacts user/password portions of RTSP and HTTP URLs. The
current dashboard does not receive an RTSP URL. Encrypted RTSP credential
storage is not implemented and remains a deployment limitation.

# AI Ingestion

The existing adapter queue feeds the actual edge loop and preserves source
metadata. RTSP frame → YOLO → ByteTrack → rules → event/backend was not
executed because no authorized local RTSP source exists.

# Browser Streaming Architecture

The current browser player is an authenticated HTTP video route for uploaded
or demo media. No HLS, WebRTC, or authenticated MJPEG RTSP-preview route is
implemented; browsers are intentionally not sent raw RTSP URLs.

# One-Camera Test

BLOCKED BY TOOLING: no local RTSP server.

# Two-Camera Test

BLOCKED BY TOOLING: no local RTSP server; no independent live source execution.

# Mixed-Source Test

BLOCKED BY TOOLING. Source semantic separation is covered by adapter tests.

# Disconnect / Recovery

Unit-mocked reconnect and stall cases passed. Real server stop/restart,
recovery timing, and other-camera continuity are BLOCKED BY TOOLING.

# Evidence

Existing evidence flow is camera-bound and protected. RTSP-generated evidence
was not produced in this environment.

# Latency

NOT MEASURED without a live stream. The bounded queue prevents unlimited frame
backlog by dropping the oldest frames.

# Resource Use

NOT MEASURED for live RTSP. No capacity claim is made.

# Security

No external devices were contacted. Credential redaction tests pass; RTSP is
not incorrectly subjected to webhook private-network restrictions because real
authorized CCTV commonly uses private addresses.

# Tests

`tests/test_wp4_1_rtsp_resilience.py`: **13 passed**. It covers source
classification, URL redaction, finite-file versus RTSP EOF semantics, bounded
queue/drop-oldest behavior, stalls, decoder errors, and reconnection. Prior
frontend suite: 13 passed; prior frontend build passed.

# Limitations

- Local RTSP server tooling is unavailable.
- RTSP capture through the actual AI pipeline is unexecuted.
- Browser live preview transport is NOT IMPLEMENTED.
- Physical CCTV validation is BLOCKED BY HARDWARE; no authorized endpoint was
  provided.
