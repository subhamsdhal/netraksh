import asyncio

import pytest
from fastapi import HTTPException

from backend.api import dashboard


def test_media_name_is_confined_to_video_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "_videos_dir", lambda: tmp_path)
    allowed = tmp_path / "allowed.mp4"
    allowed.write_bytes(b"video")

    assert dashboard._confined_media_path("allowed.mp4", name_only=True) == allowed.resolve()

    with pytest.raises(HTTPException) as traversal:
        dashboard._confined_media_path("../outside.mp4", name_only=True)
    assert traversal.value.status_code == 400

    with pytest.raises(HTTPException) as absolute:
        dashboard._confined_media_path(str((tmp_path.parent / "outside.mp4").resolve()), name_only=True)
    assert absolute.value.status_code == 400


def test_analyze_rejects_encoded_or_plain_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "_videos_dir", lambda: tmp_path)
    for value in ("../outside.mp4", "..%2Foutside.mp4"):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                dashboard.analyze_dashboard_video(
                    dashboard.AnalyzeRequest(session_id="safe", source_name=value),
                    _user={},
                )
            )
        assert exc.value.status_code in (400, 404)


def test_demo_telemetry_route_requires_operator_or_admin():
    route = next(
        route for route in dashboard.router.routes
        if getattr(route, "path", "") == "/api/dashboard/video/demo-telemetry"
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    from backend.security.auth import require_operator_or_admin
    assert require_operator_or_admin in dependency_calls
