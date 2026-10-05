"""Focused transport accounting tests for the edge telemetry worker."""
from queue import Queue
from types import SimpleNamespace
import logging

import httpx

from edge.main import EdgePipeline


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _ScriptedClient:
    def __init__(self, pipeline, actions):
        self.pipeline = pipeline
        self.actions = list(actions)
        self.urls = []

    def post(self, url, **kwargs):
        self.urls.append(url)
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        if url.endswith("/system/telemetry"):
            self.pipeline._running = False
        return action

    def close(self):
        pass


def _pipeline_with_one_payload(include_frame=True):
    pipeline = object.__new__(EdgePipeline)
    pipeline._running = True
    pipeline._backend_url = "https://api.example.test"
    pipeline.sync_client = SimpleNamespace(_ca_cert=None, _client_cert=None)
    pipeline.telemetry_queue = Queue(maxsize=2)
    pipeline._telemetry_metrics = {"produced": 1, "dropped": 0, "errors": 0}
    pipeline._edge_auth_headers = lambda: {}
    payload = {
        "camera_id": "cam-border-01",
        "analysis_session_id": "session-1",
        "frame_index": 1,
        "source_timestamp": 1.0,
        "processed_timestamp": 2.0,
        "person_count": 1,
        "vehicle_count": 0,
        "track_count": 1,
        "tracks": [],
    }
    if include_frame:
        payload.update({
            "_clean_preview_jpeg_base64": "clean",
            "_annotated_preview_jpeg_base64": "annotated",
            "preview_available": True,
        })
    pipeline.telemetry_queue.put(payload)
    return pipeline


def test_frame_and_snapshot_acceptance_do_not_increment_errors(monkeypatch):
    pipeline = _pipeline_with_one_payload()
    client = _ScriptedClient(pipeline, [_Response(202), _Response(202)])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)

    pipeline._run_telemetry_loop()

    assert pipeline._telemetry_metrics["errors"] == 0
    assert client.urls == [
        "https://api.example.test/system/telemetry/frame",
        "https://api.example.test/system/telemetry",
    ]


def test_frame_transport_exception_is_counted_and_identified_without_payload_logging(monkeypatch, caplog):
    monkeypatch.setattr(logging.getLogger("edge.main"), "disabled", False)
    caplog.set_level(logging.WARNING, logger="edge.main")
    pipeline = _pipeline_with_one_payload()
    client = _ScriptedClient(pipeline, [httpx.ReadTimeout("read timed out"), _Response(202)])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)

    pipeline._run_telemetry_loop()

    assert pipeline._telemetry_metrics["errors"] == 1
    assert "frame upload transport error: ReadTimeout" in caplog.text
    assert "annotated" not in caplog.text


def test_snapshot_http_rejection_is_counted_separately_from_drops(monkeypatch, caplog):
    monkeypatch.setattr(logging.getLogger("edge.main"), "disabled", False)
    caplog.set_level(logging.WARNING, logger="edge.main")
    pipeline = _pipeline_with_one_payload(include_frame=False)
    pipeline._telemetry_metrics["dropped"] = 7
    client = _ScriptedClient(pipeline, [_Response(422)])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)

    pipeline._run_telemetry_loop()

    assert pipeline._telemetry_metrics == {"produced": 1, "dropped": 7, "errors": 1}
    assert "snapshot upload rejected: HTTP 422" in caplog.text


def test_terminal_transition_discards_all_lossy_live_packets():
    pipeline = object.__new__(EdgePipeline)
    pipeline.telemetry_queue = Queue(maxsize=2)
    pipeline.tracking_queue = Queue(maxsize=2)
    pipeline.telemetry_queue.put({"analysis_state": "PROCESSING"})
    pipeline.tracking_queue.put({"analysis_state": "PROCESSING"})

    pipeline._clear_live_queues()

    assert pipeline.telemetry_queue.empty()
    assert pipeline.tracking_queue.empty()
    assert pipeline.telemetry_queue.unfinished_tasks == 0
    assert pipeline.tracking_queue.unfinished_tasks == 0
