# Phase 4 WP-4.5: Alerting Guidelines

## Status
**CONFIGURATION REQUIRED** (Needs PromQL/Alertmanager setup).

## Sustained Thresholds
Alerts must not fire on transient single-frame or single-second spikes.

### Recommended Alert Configurations
- **Edge Node Critical (`EdgeNodeCritical`)**
  - **Expr:** `edge_resource_state == 3`
  - **For:** 3 minutes
  - **Desc:** Node is heavily saturated, module-skipping active.
- **Sync Lag Escalation (`SyncLagCritical`)**
  - **Expr:** `edge_sync_lag_seconds > 600`
  - **For:** 5 minutes
  - **Desc:** Edge node has been unable to communicate with Central DB for > 10m.
- **Camera Stalled (`CameraStalled`)**
  - **Expr:** `camera_last_frame_age_seconds > 10`
  - **For:** 1 minute
  - **Desc:** Connection open, but decoder isn't yielding frames.
- **High 5xx Rate (`BackendHigh5xx`)**
  - **Expr:** `rate(http_error_total{status=~"5.."}[5m]) > 5`
  - **For:** 2 minutes
  - **Desc:** Central Database or Object Storage is failing.
