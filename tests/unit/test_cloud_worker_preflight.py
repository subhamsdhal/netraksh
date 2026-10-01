import logging

import httpx
import pytest

from edge import cloud_worker


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
