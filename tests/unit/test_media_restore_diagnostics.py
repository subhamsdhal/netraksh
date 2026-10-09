import json
from datetime import datetime, timezone

import pytest

from backend.api import dashboard


class _RangeResponse:
    status_code = 206
    headers = {
        "content-type": "video/mp4",
        "content-length": "2",
        "accept-ranges": "bytes",
        "content-range": "bytes 0-1/2048",
        "access-control-allow-origin": "https://netraksh.vercel.app",
    }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def aiter_raw(self):
        return self

    async def __anext__(self):
        if getattr(self, "_consumed", False):
            raise StopAsyncIteration
        self._consumed = True
        return b"mp"


class _RangeClient:
    def __init__(self, **kwargs):
        assert kwargs["follow_redirects"] is True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def stream(self, method, url, headers):
        assert method == "GET"
        assert url.startswith("https://storage.example/")
        assert headers == {
            "Range": "bytes=0-1",
            "Origin": "https://netraksh.vercel.app",
        }
        return _RangeResponse()


@pytest.mark.asyncio
async def test_camera1_media_diagnostic_reports_sanitized_head_range_and_cors(monkeypatch):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    signed_url = (
        "https://storage.example/private/object"
        f"?X-Amz-Date={timestamp}&X-Amz-Expires=900&X-Amz-Signature=private"
    )

    class _Storage:
        def head_object(self, object_key):
            assert object_key == "video-sessions/cam-border-01/private-preview.mp4"
            return {"ContentType": "video/mp4", "ContentLength": 2048, "AcceptRanges": "bytes"}

    monkeypatch.setattr(dashboard.settings, "OBJECT_STORAGE_PROVIDER", "s3")
    monkeypatch.setattr(
        dashboard,
        "get_uploaded_session",
        lambda camera_id, session_id: {
            "camera_id": camera_id,
            "session_id": session_id,
            "preview_object_key": "video-sessions/cam-border-01/private-preview.mp4",
            "content_type": "video/mp4",
        },
    )
    monkeypatch.setattr(dashboard, "get_evidence_storage", lambda: _Storage())
    monkeypatch.setattr(dashboard, "signed_media_url", lambda *_args, **_kwargs: signed_url)
    monkeypatch.setattr(dashboard.httpx, "AsyncClient", _RangeClient)

    async def _run_inline(function, *args):
        return function(*args)

    monkeypatch.setattr(dashboard.asyncio, "to_thread", _run_inline)

    result = await dashboard.diagnose_camera1_completed_run_media(_admin={"role": "ADMIN"})
    serialized = json.dumps(result)

    assert result["media_object_exists"] is True
    assert result["head_status"] == "available"
    assert result["head_content_type"] == "video/mp4"
    assert result["head_content_length"] == 2048
    assert result["range_status"] == 206
    assert result["range_content_range"] == "bytes 0-1/2048"
    assert result["cors_allow_origin"] == "https://netraksh.vercel.app"
    assert result["signed_url_generated"] is True
    assert "storage.example" in result["storage_host"]
    assert "X-Amz-Signature" not in serialized
    assert "private-preview.mp4" not in serialized


def test_camera1_media_diagnostic_is_admin_only():
    route = next(
        route for route in dashboard.router.routes
        if getattr(route, "path", "") == "/api/dashboard/admin/media-diagnostics/camera1-completed-run"
    )
    assert any(dependency.call is dashboard.require_admin for dependency in route.dependant.dependencies)
