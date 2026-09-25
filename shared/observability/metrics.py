import logging

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Safely isolate metrics creation to not break the pipeline if prometheus is missing
def _create_counter(name, desc, labels=None):
    if not _PROMETHEUS_AVAILABLE: return None
    try:
        return Counter(name, desc, labels or [])
    except Exception as e:
        logger.error(f"Failed to register metric {name}: {e}")
        return None

def _create_gauge(name, desc, labels=None):
    if not _PROMETHEUS_AVAILABLE: return None
    try:
        return Gauge(name, desc, labels or [])
    except Exception as e:
        logger.error(f"Failed to register metric {name}: {e}")
        return None

def _create_histogram(name, desc, labels=None):
    if not _PROMETHEUS_AVAILABLE: return None
    try:
        return Histogram(name, desc, labels or [])
    except Exception as e:
        logger.error(f"Failed to register metric {name}: {e}")
        return None

class MetricsRegistry:
    def __init__(self):
        # EDGE METRICS
        self.edge_active_streams = _create_gauge('edge_active_streams', 'Number of active camera streams')
        self.edge_cpu_percent = _create_gauge('edge_cpu_percent', 'Edge node CPU utilization')
        self.edge_memory_mb = _create_gauge('edge_memory_mb', 'Edge node memory usage in MB')
        self.edge_resource_state = _create_gauge('edge_resource_state', 'Resource state enum (0=Normal, 1=Warning, 2=Degraded, 3=Critical)', ['state'])
        self.edge_admission_total = _create_counter('edge_admission_total', 'Total stream admission requests')
        self.edge_admission_rejected_total = _create_counter('edge_admission_rejected_total', 'Total stream admissions rejected')
        self.edge_sync_queue_depth = _create_gauge('edge_sync_queue_depth', 'Depth of evidence sync queue')
        self.edge_sync_lag_seconds = _create_gauge('edge_sync_lag_seconds', 'Time since oldest unsynchronized evidence')
        self.edge_sync_failures_total = _create_counter('edge_sync_failures_total', 'Total edge to central sync failures')
        self.edge_module_skips_total = _create_counter('edge_module_skips_total', 'Total modules skipped due to resource pressure')
        
        # CAMERA METRICS (Edge local)
        self.camera_fps = _create_gauge('camera_fps', 'Frames per second', ['camera_id'])
        self.camera_last_frame_age_seconds = _create_gauge('camera_last_frame_age_seconds', 'Age of last processed frame', ['camera_id'])
        self.camera_reconnect_total = _create_counter('camera_reconnect_total', 'Total camera reconnects', ['camera_id'])
        self.camera_dropped_frames_total = _create_counter('camera_dropped_frames_total', 'Total frames dropped due to queue pressure', ['camera_id'])
        self.camera_queue_depth = _create_gauge('camera_queue_depth', 'Current frame queue depth', ['camera_id'])

        # CENTRAL METRICS
        self.http_requests_total = _create_counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
        self.http_request_latency_seconds = _create_histogram('http_request_latency_seconds', 'HTTP request latency', ['method', 'endpoint'])
        self.http_error_total = _create_counter('http_error_total', 'Total HTTP errors', ['status'])
        
        self.event_ingest_total = _create_counter('event_ingest_total', 'Total events ingested')
        self.event_ingest_failures_total = _create_counter('event_ingest_failures_total', 'Total event ingest failures')
        
        self.evidence_upload_total = _create_counter('evidence_upload_total', 'Total evidence uploads')
        self.evidence_upload_failures_total = _create_counter('evidence_upload_failures_total', 'Total evidence upload failures')
        self.evidence_missing_total = _create_counter('evidence_missing_total', 'Total missing evidence references')
        
        self.object_storage_errors_total = _create_counter('object_storage_errors_total', 'Total object storage interface errors')
        self.webhook_delivery_total = _create_counter('webhook_delivery_total', 'Total webhooks delivered')
        self.webhook_failure_total = _create_counter('webhook_failure_total', 'Total webhook delivery failures')
        
        self.db_pool_usage = _create_gauge('db_pool_usage', 'Database connection pool active count')
        self.db_query_latency = _create_histogram('db_query_latency', 'Database query execution latency')
        
        self.mtls_auth_failure_total = _create_counter('mtls_auth_failure_total', 'Total mTLS authentication failures')
        self.edge_identity_rejection_total = _create_counter('edge_identity_rejection_total', 'Total Edge identity rejections (revoked/unknown)')
        self.active_edges = _create_gauge('active_edges', 'Number of active reporting edges')

    def inc_counter(self, metric, amount=1, labels=None):
        if not _PROMETHEUS_AVAILABLE: return
        try:
            m = getattr(self, metric, None)
            if m:
                (m.labels(**labels) if labels else m).inc(amount)
        except Exception as e:
            logger.debug(f"Failed to increment {metric}: {e}")

    def set_gauge(self, metric, value, labels=None):
        if not _PROMETHEUS_AVAILABLE: return
        try:
            m = getattr(self, metric, None)
            if m:
                (m.labels(**labels) if labels else m).set(value)
        except Exception as e:
            logger.debug(f"Failed to set gauge {metric}: {e}")

    def observe_histogram(self, metric, value, labels=None):
        if not _PROMETHEUS_AVAILABLE: return
        try:
            m = getattr(self, metric, None)
            if m:
                (m.labels(**labels) if labels else m).observe(value)
        except Exception as e:
            logger.debug(f"Failed to observe {metric}: {e}")

# Global singleton
metrics = MetricsRegistry()

def get_metrics_payload() -> tuple[bytes, str]:
    if not _PROMETHEUS_AVAILABLE:
        return b"# Prometheus client not installed\n", "text/plain"
    try:
        return generate_latest(), CONTENT_TYPE_LATEST
    except Exception as e:
        logger.error(f"Failed to generate metrics payload: {e}")
        return b"", "text/plain"
