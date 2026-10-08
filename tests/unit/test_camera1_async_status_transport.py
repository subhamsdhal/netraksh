from queue import Queue
import threading
from types import SimpleNamespace

from edge.main import EdgePipeline


def _pipeline(maxsize=4):
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.camera_id = "cam-border-01"
    pipeline.status_queue = Queue(maxsize=maxsize)
    pipeline._status_transport_metrics = {"produced": 0, "dropped": 0, "errors": 0}
    pipeline._status_transport_stop = threading.Event()
    return pipeline


def test_status_queue_is_bounded_and_keeps_the_newest_reports():
    pipeline = _pipeline(maxsize=2)

    pipeline._enqueue_status_report("health", {"sequence": 1})
    pipeline._enqueue_status_report("metrics", {"sequence": 2})
    pipeline._enqueue_status_report("health", {"sequence": 3})

    assert list(pipeline.status_queue.queue) == [
        ("metrics", {"sequence": 2}),
        ("health", {"sequence": 3}),
    ]
    assert pipeline._status_transport_metrics == {"produced": 3, "dropped": 1, "errors": 0}


def test_health_report_only_enqueues_from_the_frame_loop():
    pipeline = _pipeline()
    pipeline._last_health = SimpleNamespace(
        model_dump=lambda mode: {"health_state": "HEALTHY", "mode": mode},
    )

    pipeline._report_camera_health()

    assert pipeline.status_queue.get_nowait() == (
        "health", {"health_state": "HEALTHY", "mode": "json"},
    )


def test_status_transport_sends_each_append_only_report_once(monkeypatch):
    import httpx

    calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            self.statuses = iter((201, 503))

        def post(self, url, *, json, headers):
            calls.append((url, json, headers))
            return SimpleNamespace(status_code=next(self.statuses))

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    pipeline = _pipeline()
    pipeline._running = False
    pipeline._status_transport_stop.set()
    pipeline.sync_client = SimpleNamespace(
        _ca_cert=None,
        _client_cert=None,
        backend_url="https://backend.example",
    )
    pipeline._edge_auth_headers = lambda: {"Authorization": "test"}
    pipeline.status_queue.put_nowait(("health", {"sample": 1}))
    pipeline.status_queue.put_nowait(("metrics", {"sample": 2}))

    pipeline._run_status_transport_loop()

    assert [call[0] for call in calls] == [
        "https://backend.example/cameras/cam-border-01/health",
        "https://backend.example/system/metrics",
    ]
    assert pipeline._status_transport_metrics["errors"] == 1
    assert pipeline.status_queue.unfinished_tasks == 0


def test_status_transport_drains_final_snapshot_after_stop_is_requested(monkeypatch):
    import httpx

    calls = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def post(self, url, *, json, headers):
            calls.append((url, json))
            return SimpleNamespace(status_code=201)

        def close(self):
            pass

    monkeypatch.setattr(httpx, "Client", FakeClient)
    pipeline = _pipeline()
    pipeline._running = False
    pipeline.sync_client = SimpleNamespace(
        _ca_cert=None,
        _client_cert=None,
        backend_url="https://backend.example",
    )
    pipeline._edge_auth_headers = lambda: {"Authorization": "test"}
    pipeline.status_queue.put_nowait(("metrics", {"final": True}))
    pipeline._status_transport_stop.set()

    pipeline._run_status_transport_loop()

    assert calls == [("https://backend.example/system/metrics", {"final": True})]
    assert pipeline.status_queue.unfinished_tasks == 0
