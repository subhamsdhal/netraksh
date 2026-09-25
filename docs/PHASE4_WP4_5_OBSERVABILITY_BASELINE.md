# Phase 4 WP-4.5: Observability Baseline

## Current Audit Results

**1. Logging:**
- *EXISTING:* Python standard `logging.getLogger(__name__)` used universally across `edge/` and `backend/`.
- *MISSING:* No structured JSON logging layout natively enabled. No global correlation ID tying edge ingestion -> inference -> evidence upload -> backend DB.
- *RISKS:* Standard string formatting risks leaking sensitive data (e.g. RTSP URLs with credentials, DB passwords) into stdout if a developer logs `app_config` or raw exception objects.

**2. Metrics:**
- *EXISTING:* `edge/instrumentation/metrics.py` collects rolling window latency stats (`PipelineMetrics`), CPU/RAM samples, and dumps them to local JSON.
- *EXISTING:* `EdgeResourceGovernor` (WP-4.4) collects state (`NORMAL`, `WARNING`, `DEGRADED`, `CRITICAL`).
- *MISSING:* No Prometheus-compatible HTTP export (`/metrics`). No counters for HTTP API routes on Central. No aggregated counters for evidence upload failures or mTLS handshake rejections.
- *RISKS (Cardinality):* Current metrics map keys explicitly; if we emit metrics using arbitrary labels like `evidence_id`, it will explode cardinality.

**3. Health & Telemetry:**
- *EXISTING:* `CameraHealthMonitor` emits camera state (`CONNECTED`, `RECONNECTING`, etc).
- *MISSING:* Sync lag measurement (how long since last successful mTLS sync with central).

**4. Tracing:**
- *MISSING:* No distributed tracing across the edge-to-central boundary.

**5. Security-Sensitive Data:**
- The system handles private keys (`Ed25519`), cryptographic signatures, RTSP passwords, and JWT tokens.
- These must be strictly filtered from all observability planes.
