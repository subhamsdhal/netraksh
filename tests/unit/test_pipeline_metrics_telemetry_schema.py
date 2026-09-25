from datetime import datetime

from shared.schemas import PipelineMetricsReport, PipelineMetricsResponse


def _metric_fields():
    return {
        "edge_device_id": "cam-border-01",
        "timestamp": datetime(2026, 9, 17, 12, 0, 0),
        "uptime_seconds": 12.5,
        "fps": 4.2,
        "frames": {},
        "events": {},
    }


def test_metrics_report_preserves_real_telemetry_counters():
    report = PipelineMetricsReport(
        **_metric_fields(),
        telemetry_produced=42,
        telemetry_dropped=3,
        telemetry_errors=1,
    )

    assert report.telemetry_produced == 42
    assert report.telemetry_dropped == 3
    assert report.telemetry_errors == 1


def test_legacy_metrics_response_keeps_missing_counters_null():
    response = PipelineMetricsResponse(
        **_metric_fields(),
        alerts_generated=0,
        cpu_percent=None,
        rss_mb=None,
        psutil_available=False,
    )

    assert response.telemetry_produced is None
    assert response.telemetry_dropped is None
    assert response.telemetry_errors is None
