import asyncio
import copy

from backend.api import dashboard


CAMERAS = ("cam-border-01", "cam-checkpoint-01")


def _durable(camera_id):
    return {
        "camera_id": camera_id,
        "source_mode": "durable",
        "session_id": f"{camera_id}-stream",
        "source_object_key": f"media/{camera_id}.mp4",
        "scenario": "paused",
        "analysis_generation": 7,
        "latest_analysis_session_id": "existing-analysis",
    }


def _reset_cache():
    dashboard._edge_prewarm_status.clear()
    dashboard._edge_wake_tasks.clear()


def test_prewarm_wakes_two_configured_workers_concurrently_without_control_mutation(monkeypatch):
    _reset_cache()
    records = {camera_id: _durable(camera_id) for camera_id in CAMERAS}
    entered = set()
    release = asyncio.Event()

    monkeypatch.setattr(dashboard, "_edge_wake_url", lambda camera_id: f"https://{camera_id}.example.test")

    async def wake(camera_id):
        entered.add(camera_id)
        if len(entered) == 2:
            release.set()
        await release.wait()
        return "ready"

    monkeypatch.setattr(dashboard, "_wake_edge_service", wake)
    result = asyncio.run(dashboard.prewarm_edge_workers(_user={}))

    assert entered == set(CAMERAS)
    assert result["eligible"] == 2
    assert result["ready"] == 2
    assert records == {camera_id: _durable(camera_id) for camera_id in CAMERAS}


def test_prewarm_skips_only_unconfigured_worker(monkeypatch):
    _reset_cache()
    calls = []
    monkeypatch.setattr(
        dashboard,
        "_edge_wake_url",
        lambda camera_id: "https://edge.example.test" if camera_id == CAMERAS[0] else "",
    )

    async def wake(camera_id):
        calls.append(camera_id)
        return "ready"

    monkeypatch.setattr(dashboard, "_wake_edge_service", wake)
    result = asyncio.run(dashboard.prewarm_edge_workers(_user={}))

    assert calls == [CAMERAS[0]]
    assert result["eligible"] == 1
    assert result["cameras"][CAMERAS[1]]["status"] == "not_configured"


def test_prewarm_requires_no_durable_source_and_preserves_control_state(monkeypatch):
    _reset_cache()
    original_state = copy.deepcopy(dashboard._demo_state)
    monkeypatch.setattr(dashboard, "_edge_wake_url", lambda camera_id: f"https://{camera_id}.example.test")
    monkeypatch.setattr(dashboard, "get_valid_active_session", lambda _camera_id: None)

    def forbidden_mutation(*_args, **_kwargs):
        raise AssertionError("prewarm must not create or mutate a video/analysis session")

    monkeypatch.setattr(dashboard, "start_active_session", forbidden_mutation)
    monkeypatch.setattr(dashboard, "activate_session", forbidden_mutation)
    monkeypatch.setattr(dashboard, "update_active_session", forbidden_mutation)

    async def wake(_camera_id):
        return "ready"

    monkeypatch.setattr(dashboard, "_wake_edge_service", wake)
    result = asyncio.run(dashboard.prewarm_edge_workers(_user={}))

    assert result["eligible"] == 2
    assert result["ready"] == 2
    assert dashboard._demo_state == original_state


def test_health_requires_worker_alive_and_no_error():
    assert dashboard._classify_edge_health(502, {}) == "warming"
    assert dashboard._classify_edge_health(200, {}) == "warming"
    assert dashboard._classify_edge_health(200, {"worker_alive": False, "last_error": None}) == "warming"
    assert dashboard._classify_edge_health(200, {"worker_alive": True, "last_error": "RuntimeError"}) == "warming"
    assert dashboard._classify_edge_health(200, {"worker_alive": True, "last_error": None}) == "ready"


def test_status_reads_cache_without_contacting_edge(monkeypatch):
    _reset_cache()
    dashboard._cache_prewarm_status(CAMERAS[0], "ready")
    dashboard._cache_prewarm_status(CAMERAS[1], "warming")

    async def forbidden_probe(_camera_id):
        raise AssertionError("status endpoint must not contact an edge service")

    monkeypatch.setattr(dashboard, "_probe_edge_service", forbidden_probe)
    result = asyncio.run(dashboard.get_edge_prewarm_status(_user={}))
    assert result["ready"] == 1
    assert result["warming"] == 1


def test_ready_status_expires_without_keepalive():
    _reset_cache()
    dashboard._edge_prewarm_status[CAMERAS[0]] = {
        "camera_id": CAMERAS[0], "status": "ready", "requested_at": 1,
        "ready_at": 1, "last_checked_at": 1, "error": None,
    }
    expired = dashboard._cached_prewarm_status(
        CAMERAS[0], now=1 + dashboard._PREWARM_READY_TTL_SECONDS + 1,
    )
    assert expired["status"] == "unknown"
    assert expired["error"] == "readiness_expired"


def test_bounded_prewarm_retry_becomes_explicit_terminal_timeout(monkeypatch):
    _reset_cache()
    dashboard._cache_prewarm_status(CAMERAS[0], "warming")
    monkeypatch.setattr(dashboard, "_EDGE_WAKE_RETRY_DELAYS", (0,))

    async def still_warming(_camera_id):
        return "waking"

    monkeypatch.setattr(dashboard, "_probe_edge_service", still_warming)
    asyncio.run(dashboard._retry_edge_wake_until_ready(CAMERAS[0]))
    response = dashboard._prewarm_response()
    assert response["terminal"] == 1
    assert response["cameras"][CAMERAS[0]]["status"] == "timeout"
