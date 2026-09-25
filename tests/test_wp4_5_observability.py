"""
Tests for WP-4.5 Edge & Central Observability, Logging, Metrics, and Correlation IDs.
"""
import logging
import json
import pytest
from unittest.mock import patch, MagicMock

from shared.observability.logging import RedactingJSONFormatter, correlation_id_var, edge_id_var, camera_id_var
from shared.observability.metrics import MetricsRegistry

def test_json_formatting_and_correlation_ids():
    formatter = RedactingJSONFormatter()
    record = logging.LogRecord(
        name="test.component", level=logging.INFO, pathname="", lineno=0,
        msg="Test event", args=(), exc_info=None
    )
    
    # Inject context
    correlation_id_var.set("req-12345")
    edge_id_var.set("edge-999")
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    assert parsed["message"] == "Test event"
    assert parsed["severity"] == "INFO"
    assert parsed["correlation_id"] == "req-12345"
    assert parsed["edge_id"] == "edge-999"
    assert "camera_id" not in parsed

def test_secret_redaction_in_extras():
    formatter = RedactingJSONFormatter()
    record = logging.LogRecord(
        name="test.component", level=logging.INFO, pathname="", lineno=0,
        msg="Test event", args=(), exc_info=None
    )
    record.password = "supersecret"
    record.rtsp_url = "rtsp://admin:password@10.0.0.1/stream"
    record.public_data = "safe"
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    assert parsed["password"] == "***REDACTED***"
    assert "rtsp://***:***@10.0.0.1/stream" in parsed["rtsp_url"]
    assert parsed["public_data"] == "safe"

def test_secret_redaction_in_message():
    formatter = RedactingJSONFormatter()
    record = logging.LogRecord(
        name="test.component", level=logging.INFO, pathname="", lineno=0,
        msg="Connection to rtsp://admin:secret123@192.168.1.1/cam1 failed", args=(), exc_info=None
    )
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    # Should redact credentials from raw string messages
    assert parsed["message"] == "Connection to rtsp://***:***@192.168.1.1/cam1 failed"

def test_nested_secret_redaction():
    formatter = RedactingJSONFormatter()
    record = logging.LogRecord(
        name="test.component", level=logging.INFO, pathname="", lineno=0,
        msg="Nested struct", args=(), exc_info=None
    )
    record.nested_payload = {
        "status": "active",
        "jwt": "header.payload.signature",
        "config": {
            "database_url": "postgres://user:pass@db:5432/db"
        }
    }
    
    output = formatter.format(record)
    parsed = json.loads(output)
    
    payload = parsed["nested_payload"]
    assert payload["status"] == "active"
    assert payload["jwt"] == "***REDACTED***"
    assert payload["config"]["database_url"] == "***REDACTED***"

@patch('shared.observability.metrics._PROMETHEUS_AVAILABLE', True)
def test_metrics_registration():
    with patch('shared.observability.metrics.Counter') as mock_counter, \
         patch('shared.observability.metrics.Gauge') as mock_gauge, \
         patch('shared.observability.metrics.Histogram') as mock_hist:
         
        registry = MetricsRegistry()
        
        assert registry.edge_active_streams is not None
        assert registry.http_requests_total is not None
        mock_counter.assert_called()
        mock_gauge.assert_called()
        mock_hist.assert_called()

def test_metrics_failure_isolation():
    # Even if Prometheus throws an exception, pipeline must not crash
    with patch('shared.observability.metrics.Counter', side_effect=Exception("Prometheus unavailable")):
        registry = MetricsRegistry()
        assert registry.edge_admission_total is None
        
        # Calling increment should fail gracefully
        registry.inc_counter("edge_admission_total", 1) 
        # If this does not raise, isolation is verified.
