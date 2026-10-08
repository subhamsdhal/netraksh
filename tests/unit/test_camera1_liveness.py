"""The Camera 1 liveness probe must be bounded to a real active worker."""

import asyncio
from types import SimpleNamespace

import pytest

from backend.services import camera1_liveness as liveness


def _lease(**changes):
    fields = dict(
        phase="RUNNING", analysis_session_id="run-1", stream_id="source-1",
        analysis_generation=9, last_heartbeat_at=100.0,
    )
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_only_fresh_running_analysis_is_probed():
    assert liveness.lease_is_active(_lease(), now=110.0)
    assert not liveness.lease_is_active(None, now=110.0)
    assert not liveness.lease_is_active(_lease(phase="IDLE"), now=110.0)
    assert not liveness.lease_is_active(_lease(analysis_session_id=None), now=110.0)
    assert not liveness.lease_is_active(_lease(stream_id=None), now=110.0)
    assert not liveness.lease_is_active(_lease(last_heartbeat_at=70.0), now=110.0)


def test_database_lookup_is_camera1_only(monkeypatch):
    calls = []

    class FakeSession:
        def get(self, model, camera_id):
            calls.append(camera_id)
            return _lease()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(liveness, "SessionLocal", FakeSession)
    monkeypatch.setattr(liveness.time, "time", lambda: 110.0)
    assert liveness.camera1_has_active_worker()
    assert calls == ["cam-border-01", "closed"]


def test_idle_camera_never_receives_http_probe(monkeypatch):
    calls = []

    async def sleep_once(_seconds):
        calls.append("tick")
        if len(calls) > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(liveness.asyncio, "sleep", sleep_once)
    monkeypatch.setattr(liveness, "camera1_has_active_worker", lambda: False)
    monkeypatch.setenv("EDGE_WAKE_URL_CAM_BORDER_01", "https://camera1.example")

    class ForbiddenClient:
        def __init__(self, **_kwargs):
            pytest.fail("idle Camera 1 must not open a network client")

    monkeypatch.setattr(liveness.httpx, "AsyncClient", ForbiddenClient)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(liveness.monitor_camera1_active_analysis())
    assert calls == ["tick", "tick"]


def test_active_camera_probes_health_only(monkeypatch):
    calls = []

    async def sleep_once(_seconds):
        calls.append("tick")
        if calls.count("tick") > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(liveness.asyncio, "sleep", sleep_once)
    monkeypatch.setattr(liveness, "camera1_has_active_worker", lambda: True)
    monkeypatch.setenv("EDGE_WAKE_URL_CAM_BORDER_01", "https://camera1.example/")

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def get(self, url):
            calls.append(url)
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(liveness.httpx, "AsyncClient", FakeClient)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(liveness.monitor_camera1_active_analysis())
    assert calls == ["tick", "https://camera1.example/health", "tick"]
