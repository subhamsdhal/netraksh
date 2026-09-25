"""
NETRAKSH — Prometheus metrics registry.

Design constraints:
  1. BOUNDED CARDINALITY: no label value derived from user-controlled data
     (no camera_id, event_id, or user-agent in labels).  The only labels used
     are small finite enumerations: http_method, http_status_class, endpoint_group,
     storage_provider, result.
  2. SINGLE REGISTRY: one prometheus_client.REGISTRY is used; avoid re-registration
     errors on hot-reload by checking CollectorRegistry.
  3. No OpenTelemetry, no Jaeger, no Grafana provisioning — plain Prometheus text format.
  4. All counters use `_total` suffix per Prometheus naming convention.

Exposed metrics:
  netraksh_http_requests_total{method, status_class, endpoint_group}
  netraksh_http_request_duration_seconds{method, endpoint_group}   (Histogram)
  netraksh_ws_connections_active                                    (Gauge)
  netraksh_evidence_uploads_total{provider, result}
  netraksh_evidence_upload_bytes_total{provider}
"""
from prometheus_client import Counter, Gauge, Histogram, REGISTRY

# ─── HTTP Instrumentation ─────────────────────────────────────────────────────
# method: GET, POST, etc.
# status_class: 2xx, 4xx, 5xx (never the exact status code — keeps cardinality ≤ 6)
# endpoint_group: one of {"events", "cameras", "alerts", "auth", "system", "other"}

def _safe_register(metric):
    """Return metric if not already registered; else return existing."""
    try:
        REGISTRY.register(metric)
    except Exception:
        # Already registered (e.g., module imported twice in a live-reload context)
        pass
    return metric


HTTP_REQUESTS_TOTAL = _safe_register(Counter(
    "netraksh_http_requests",
    "Total HTTP requests handled by NETRAKSH backend",
    ["method", "status_class", "endpoint_group"],
))

HTTP_REQUEST_DURATION = _safe_register(Histogram(
    "netraksh_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint_group"],
    # Buckets tuned for a surveillance API: fast (< 50ms), normal (< 500ms),
    # slow (< 5s), very slow (> 5s)
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
))

# ─── WebSocket Connections ────────────────────────────────────────────────────
WS_CONNECTIONS_ACTIVE = _safe_register(Gauge(
    "netraksh_ws_connections_active",
    "Number of currently active WebSocket connections",
))

# ─── Evidence Storage ─────────────────────────────────────────────────────────
# provider: "local", "s3"
# result: "success", "hash_mismatch", "storage_error", "db_error", "already_available"

EVIDENCE_UPLOADS_TOTAL = _safe_register(Counter(
    "netraksh_evidence_uploads",
    "Evidence upload attempts by provider and result",
    ["provider", "result"],
))

EVIDENCE_UPLOAD_BYTES_TOTAL = _safe_register(Counter(
    "netraksh_evidence_upload_bytes",
    "Total bytes of evidence uploaded (successful uploads only)",
    ["provider"],
))

# ─── Endpoint group classifier ────────────────────────────────────────────────

_ENDPOINT_PREFIXES = [
    ("/events", "events"),
    ("/cameras", "cameras"),
    ("/alerts", "alerts"),
    ("/auth", "auth"),
    ("/health", "system"),
    ("/ready", "system"),
    ("/metrics", "system"),
    ("/system", "system"),
    ("/ws", "websocket"),
    ("/sync", "system"),
    ("/api/nodes", "system"),
]


def classify_endpoint(path: str) -> str:
    """Map a URL path to one of the finite endpoint_group label values."""
    for prefix, group in _ENDPOINT_PREFIXES:
        if path.startswith(prefix):
            return group
    return "other"
