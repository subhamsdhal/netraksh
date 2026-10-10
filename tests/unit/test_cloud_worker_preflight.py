import logging

import httpx
import pytest

from edge import cloud_worker
from edge import demo_runner
from types import SimpleNamespace


def _response(status_code, payload=None):
    request = httpx.Request("GET", "https://backend.example.test")
    return httpx.Response(status_code, request=request, json=payload or {})


class _Client:
    def __init__(self, responses, calls):
        self.responses = iter(responses)
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def test_transient_backend_failure_retries_quickly_then_proceeds(monkeypatch):
    calls = []
    sleeps = []
    responses = [
        _response(503),
        _response(200, {"status": "ready", "database": "connected"}),
        _response(200, {"available": False}),
    ]
    monkeypatch.setenv("EDGE_BACKEND_PREFLIGHT_DEADLINE_SECONDS", "10")
    monkeypatch.setenv("EDGE_BACKEND_PREFLIGHT_RETRY_SECONDS", "1.5")
    monkeypatch.setattr(cloud_worker.httpx, "Client", lambda **_kwargs: _Client(responses, calls))
    monkeypatch.setattr(cloud_worker.time, "sleep", sleeps.append)

    cloud_worker._preflight("https://backend.example.test", "cam-border-01", "secret-token")

    assert [url.rsplit("/", 1)[-1] for url, _kwargs in calls] == ["ready", "ready", "internal-sync"]
    assert sleeps == [1.5]
    assert cloud_worker._state["phase"] == "READY"


def test_preflight_has_hard_deadline(monkeypatch):
    calls = []
    responses = [_response(503)]
    monotonic_values = iter([0.0, 2.0])
    monkeypatch.setenv("EDGE_BACKEND_PREFLIGHT_DEADLINE_SECONDS", "1")
    monkeypatch.setattr(cloud_worker.httpx, "Client", lambda **_kwargs: _Client(responses, calls))
    monkeypatch.setattr(cloud_worker.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(RuntimeError, match="deadline exceeded"):
        cloud_worker._preflight("https://backend.example.test", "cam-border-01", "secret-token")

    assert len(calls) == 1


def test_preflight_does_not_log_credentials(monkeypatch, caplog):
    token = "never-log-this-edge-token"
    calls = []
    responses = [
        _response(200, {"status": "ready", "database": "connected"}),
        _response(200, {"available": False}),
    ]
    monkeypatch.setattr(cloud_worker.httpx, "Client", lambda **_kwargs: _Client(responses, calls))

    with caplog.at_level(logging.DEBUG):
        cloud_worker._preflight("https://backend.example.test", "cam-border-01", token)

    assert token not in caplog.text
    assert calls[1][1]["headers"]["Authorization"] == f"Bearer {token}"


def test_preflight_does_not_retry_rejected_credentials(monkeypatch):
    calls = []
    sleeps = []
    responses = [
        _response(200, {"status": "ready", "database": "connected"}),
        _response(401),
    ]
    monkeypatch.setattr(cloud_worker.httpx, "Client", lambda **_kwargs: _Client(responses, calls))
    monkeypatch.setattr(cloud_worker.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError, match="authentication rejected"):
        cloud_worker._preflight("https://backend.example.test", "cam-border-01", "secret-token")

    assert len(calls) == 2
    assert sleeps == []


def test_idle_worker_heartbeat_payload_is_scoped_to_camera_2(monkeypatch):
    monkeypatch.setenv("CAMERA_ID", "cam-checkpoint-01")
    monkeypatch.setitem(cloud_worker._state, "boot_id", "22222222-2222-4222-8222-222222222222")
    monkeypatch.setitem(cloud_worker._state, "instance_id", "stage-camera-2-instance")
    monkeypatch.setitem(cloud_worker._state, "started_at", 1000.0)
    monkeypatch.setitem(cloud_worker._state, "analysis_phase", "IDLE")
    monkeypatch.setitem(cloud_worker._state, "pipeline", None)

    payload = cloud_worker._heartbeat_payload(cloud_worker._required("CAMERA_ID"))

    assert payload == {
        "camera_id": "cam-checkpoint-01",
        "boot_id": "22222222-2222-4222-8222-222222222222",
        "instance_id": "stage-camera-2-instance",
        "worker_started_at": 1000.0,
        "phase": "IDLE",
    }


def test_active_worker_heartbeat_payload_contains_exact_run_identity(monkeypatch):
    monkeypatch.setenv("CAMERA_ID", "cam-checkpoint-01")
    pipeline = SimpleNamespace(
        stream_id="22222222-2222-4222-8222-222222222222",
        source_stream_id="11111111-1111-4111-8111-111111111111",
        analysis_generation=7,
        _last_processed_frame_index=24,
        _last_video_time=0.8,
    )
    monkeypatch.setitem(cloud_worker._state, "pipeline", pipeline)
    monkeypatch.setitem(cloud_worker._state, "analysis_phase", "RUNNING")

    payload = cloud_worker._heartbeat_payload("cam-checkpoint-01")

    assert payload["camera_id"] == "cam-checkpoint-01"
    assert payload["phase"] == "RUNNING"
    assert payload["analysis_session_id"] == pipeline.stream_id
    assert payload["stream_id"] == pipeline.source_stream_id
    assert payload["analysis_generation"] == 7
    assert payload["last_frame_index"] == 24
    assert payload["last_video_time"] == 0.8


def test_idle_heartbeat_posts_camera_identity_and_logs_success_without_token(monkeypatch, caplog):
    calls = []
    token = "test-only-edge-secret-never-log"

    class Client(_Client):
        def __init__(self, **_kwargs):
            super().__init__([], calls)

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            request = httpx.Request("POST", url)
            return httpx.Response(200, request=request, json={"status": "ok"})

    class StopHeartbeat(Exception):
        pass

    monkeypatch.setenv("CAMERA_ID", "cam-checkpoint-01")
    monkeypatch.setenv("BACKEND_URL", "https://stage-backend.example.test/")
    monkeypatch.setenv("EDGE_AUTH_TOKEN", token)
    monkeypatch.setitem(cloud_worker._state, "pipeline", None)
    monkeypatch.setitem(cloud_worker._state, "analysis_phase", "IDLE")
    monkeypatch.setattr(cloud_worker.httpx, "Client", Client)
    monkeypatch.setattr(cloud_worker.time, "sleep", lambda _seconds: (_ for _ in ()).throw(StopHeartbeat()))

    with caplog.at_level(logging.INFO), pytest.raises(StopHeartbeat):
        cloud_worker._heartbeat_loop()

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://stage-backend.example.test/api/dashboard/video/internal-worker-heartbeat"
    assert kwargs["json"]["camera_id"] == "cam-checkpoint-01"
    assert kwargs["json"]["phase"] == "IDLE"
    assert kwargs["headers"]["Authorization"] == f"Bearer {token}"
    assert "heartbeat accepted camera_id=cam-checkpoint-01" in caplog.text
    assert token not in caplog.text


def test_cloud_worker_waits_without_creating_pipeline_until_explicit_session(monkeypatch):
    class StopPolling(Exception):
        pass

    scenario = {
        "current": "paused",
        "video_source": None,
        "video_session_id": None,
        "analysis_state": "READY",
        "analysis_generation": 0,
        "should_restart": False,
        "initialized": False,
    }
    pipeline_constructions = []
    run_states = []
    monkeypatch.setattr(demo_runner, "_scenario", scenario)
    monkeypatch.setattr(demo_runner, "_poll_scenario", lambda *_args: scenario.update(initialized=True))
    monkeypatch.setattr(demo_runner, "DemoAwareEdgePipeline", lambda config: pipeline_constructions.append(config))
    monkeypatch.setattr(demo_runner.time, "sleep", lambda _seconds: (_ for _ in ()).throw(StopPolling()))

    with pytest.raises(StopPolling):
        demo_runner.run_demo_pipeline(
            camera_id="cam-checkpoint-01",
            video_source="demo/videos/uploaded_demo.mp4",
            backend_url="https://stage-backend.example.test",
            require_explicit_session=True,
            on_run_state=lambda phase, pipeline: run_states.append((phase, pipeline)),
        )

    assert pipeline_constructions == []
    assert run_states == []
