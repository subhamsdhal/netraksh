# Phase 4 WP-4.5: Metrics Dictionary

## Status
**IMPLEMENTED** via `shared/observability/metrics.py`.

## Edge Metrics
| Metric | Type | Description |
|---|---|---|
| `edge_active_streams` | Gauge | Total streams running |
| `edge_cpu_percent` | Gauge | Node CPU utilization |
| `edge_resource_state` | Gauge | Health enum (0=Normal, 1=Warning, 2=Degraded, 3=Critical) |
| `edge_admission_rejected_total` | Counter | Admissions blocked by limits |
| `edge_sync_lag_seconds` | Gauge | Seconds since oldest unsynced evidence |
| `camera_dropped_frames_total` | Counter | Load-shedding queue drops (labeled by `camera_id`) |

## Central Metrics
| Metric | Type | Description |
|---|---|---|
| `http_requests_total` | Counter | Labeled by `method`, `endpoint`, `status` |
| `event_ingest_failures_total` | Counter | Rejections during ingest |
| `mtls_auth_failure_total` | Counter | Node authentication rejections |
| `db_pool_usage` | Gauge | Postgres pool saturation |

## Protection
The `/metrics` endpoint is configured as internal-only. External ingress routers must block access.
