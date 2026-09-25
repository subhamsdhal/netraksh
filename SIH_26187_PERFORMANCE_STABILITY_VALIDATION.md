# Test Host

Windows 11, Intel logical 16 cores, 15.65 GiB RAM, CPU-only PyTorch. GPU/CUDA
was not used. Measurements are specific to this host and clip.

# Benchmark Method

`scripts/benchmark_full_inference.py` ran the real `EdgePipeline` against
`demo/videos/vtest.avi`, with unique camera IDs, independent state directories,
YOLO, tracking, rules, telemetry, evidence path, and outbox. Runs were bounded
to 20 seconds for one/two streams and 10 seconds for four streams.

# Profile A — Core

The measured runs used the existing production pipeline and were classified as
CORE for reporting. The code path still initializes the configured face/ANPR
modules; no artificial per-frame OCR loop was added.

# Profile B — Enhanced

An enhanced 120-second run was not performed in this pass. Existing ANPR, face,
and night validations remain authoritative for feature behavior.

# 1 Stream Results

One stream: 157 input frames, 13 processed frames, 114 capture drops, 1.05
measured FPS, 3,481 ms p95 total-frame latency, 1 queued event, RSS grew from
533 MiB to 703 MiB during the short run.

# 2 Stream Results

`cam-border-01`: 168 input, 8 processed, 130 drops, 0.60 FPS, 4,499 ms p95.
`cam-checkpoint-01`: 168 input, 8 processed, 130 drops, 0.60 FPS, 4,489 ms
p95. No telemetry errors and no event outbox backlog remained. RSS was 609 MiB
at start and 888 MiB at end of the bounded run.

# 4 Stream Results

Four workers were admitted and completed one measured frame each, but did not
sustain realtime processing: approximately 6.0 seconds total-frame latency per
worker and zero stable FPS sample. RSS reached approximately 1,198 MiB. This
is CPU stress characterization, not a supported camera-capacity claim.

# CPU

CPU-only inference is the dominant cost. GPU usage was not applicable.

# RAM

Short-run RSS increased as models and runtime state initialized. A 10–15 minute
leak test was not completed; no monotonic leak conclusion is claimed.

# Frame Latency

One-stream detection/tracking mean was 612 ms; two-stream means were about 966–
977 ms. Event-processing p95 was elevated by occasional evidence work.

# Frame Drops

Capture queues are bounded at 30 and use drop-oldest backpressure. Drops were
intentional stale-frame shedding, not silent inference errors.

# Queue Behavior

Telemetry queue depth is bounded at 2; adapter queues remained bounded at 30.
Outbox depth was 0–1 at completion.

# Replay Stability

Existing adapter tests cover finite-file replay/EOF semantics. A long empirical
multi-cycle run was not completed.

# Start/Stop Stability

Existing lifecycle tests passed previously; extended repeated dashboard cycling
was not rerun in this performance pass.

# Source Replacement

Existing session-scoped pipeline design remains in place. Extended replacement
stress was not rerun.

# Edge Failure Recovery

Native offline/reconnect behavior is previously validated. A new process-kill
stress run was not performed.

# Backend Restart Recovery

Previously validated through native recovery tests; not repeated during the
bounded CPU benchmark.

# Offline Queue

Outbox remained bounded in the benchmark. Existing offline recovery tests are
the authoritative result.

# Dashboard Responsiveness

No fresh two-stream browser load walkthrough was completed. Prior dashboard and
WebSocket validation remains valid; CPU-only four-stream load is unsuitable for
judge-facing use.

# Database Behavior

Native SQLite was used by the running backend. No PostgreSQL performance claim
is made; container validation remains blocked by missing Docker.

# Feature Performance Cost

Detection/tracking is the dominant measured stage. Evidence event work is
occasional but can raise frame latency. ANPR/face cadence remains configured by
their existing gating and was not changed.

# Optimizations Applied

No performance optimization was applied in this phase. Existing bounded queues,
telemetry cadence, and stale-frame dropping were retained.

# Before/After Measurements

NOT APPLICABLE: no code optimization was introduced, so there is no honest
before/after comparison.

# Full Regression

The focused RTSP suite previously passed 13 tests; frontend previously passed
13 tests and built successfully. A broad run launched but was interrupted after
partial progress because an extended test did not complete within the bounded
validation window. Prior maintained backend regression result remains 157
passed.

# Remaining Limitations

- CPU-only host sustains the two-stream demo functionally but below source FPS.
- Four-stream run is degraded and not a capacity claim.
- Long memory, browser-under-load, restart, and 10–15 minute stability tests
  remain incomplete.
- Docker/PostgreSQL/MinIO, RTSP, and physical CCTV remain externally blocked.
