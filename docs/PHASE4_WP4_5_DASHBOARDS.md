# Phase 4 WP-4.5: Dashboard Configuration

## Status
**CONFIGURATION / DEPLOYMENT REQUIRED**

Grafana is not inherently deployed into the active Python Edge environment. 

### Suggested Dashboard Panels

#### 1. Edge Overview
- **Active Edges (Gauge):** `active_edges`
- **CPU/RAM Heatmap:** `edge_cpu_percent`, `edge_memory_mb`
- **Resource State Distribution (Pie):** `edge_resource_state`

#### 2. Camera Health
- **Reconnections (Graph):** `rate(camera_reconnect_total[1m])`
- **Frame Drops:** `camera_dropped_frames_total`

#### 3. Synchronization Pipeline
- **Sync Lag (Time Series):** `edge_sync_lag_seconds`
- **Sync Failures (Bar Gauge):** `edge_sync_failures_total`

#### 4. Central API & Security
- **Request Latency (Heatmap):** `rate(http_request_latency_seconds_bucket[5m])`
- **mTLS Rejections (Stat):** `mtls_auth_failure_total`
