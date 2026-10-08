from pathlib import Path
import uuid

import httpx

from edge.demo_runner import (
    _apply_control_sync,
    _stored_file_source_clock,
    _control_seek_target,
    _is_resolvable_edge_source,
    _materialize_remote_source,
    _runtime_state_paths,
    _scenario,
)


def _set_local_session(source="demo/videos/vtest.avi"):
    _scenario.clear()
    _scenario.update({
        "current": "normal",
        "video_source": source,
        "video_session_id": None,
        "video_time": 0.0,
        "video_time_updated_at": 0.0,
        "should_restart": False,
        "initialized": False,
    })


def test_local_file_is_a_resolvable_edge_source():
    assert _is_resolvable_edge_source(str(Path(__file__))) is True


def test_control_plane_only_path_is_not_a_resolvable_edge_source():
    assert _is_resolvable_edge_source(
        "demo/videos/uploaded_78aef2e9-96fd-4647-8731-a5623273e5ac.mp4"
    ) is False


def test_supported_live_stream_remains_switchable():
    assert _is_resolvable_edge_source("rtsp://edge.example.test/camera") is True


def test_unavailable_source_rejects_its_seek_and_pause_state():
    _set_local_session()

    accepted = _apply_control_sync({
        "video_source": "demo/videos/uploaded_control_plane_only.mp4",
        "video_session_id": "remote-session",
        "video_time": 3246.0,
        "video_time_updated_at": 100.0,
        "scenario": "paused",
    })

    assert accepted is False
    assert _scenario["video_source"] == "demo/videos/vtest.avi"
    assert _scenario["video_session_id"] is None
    assert _scenario["video_time"] == 0.0
    assert _scenario["current"] == "normal"


def test_resolvable_source_switch_applies_its_session_seek():
    _set_local_session()
    replacement = Path(__file__)

    accepted = _apply_control_sync({
        "video_source": str(replacement),
        "video_session_id": "local-session",
        "video_time": 12.0,
        "video_time_updated_at": 100.0,
        "scenario": "paused",
    })

    assert accepted is True
    assert _scenario["video_source"] == str(replacement)
    assert _scenario["video_session_id"] == "local-session"
    assert _scenario["video_time"] == 12.0
    assert _scenario["current"] == "paused"


def test_control_sync_preserves_claimed_analysis_session_for_restart_fence():
    _set_local_session()
    replacement = Path(__file__)

    assert _apply_control_sync({
        "video_source": str(replacement),
        "video_session_id": "local-session",
        "scenario": "normal",
        "analysis_state": "ACTIVE",
        "analysis_generation": 7,
        "latest_analysis_session_id": "existing-analysis-session",
    }) is True

    assert _scenario["analysis_state"] == "ACTIVE"
    assert _scenario["analysis_generation"] == 7
    assert _scenario["latest_analysis_session_id"] == "existing-analysis-session"


def test_same_accepted_session_keeps_legitimate_browser_seek_functional():
    replacement = str(Path(__file__))
    _set_local_session(replacement)
    _scenario["video_session_id"] = "local-session"

    accepted = _apply_control_sync({
        "video_source": replacement,
        "video_session_id": "local-session",
        "video_time": 42.0,
        "video_time_updated_at": 200.0,
        "scenario": "normal",
    })

    assert accepted is True
    assert _scenario["video_source"] == replacement
    assert _scenario["video_session_id"] == "local-session"
    assert _scenario["video_time"] == 42.0
    assert _scenario["should_restart"] is False


def test_finite_source_accepts_a_valid_explicit_browser_seek():
    assert _control_seek_target(42.0, "LOCAL_FINITE_FILE", 79.5) == 42.0


def test_finite_source_rejects_stale_out_of_range_browser_position():
    assert _control_seek_target(575.0, "LOCAL_FINITE_FILE", 79.5) is None


def test_browser_position_is_not_wall_clock_extrapolated_after_its_last_update():
    # The browser's last explicit position is authoritative.  A quiet browser
    # must not make a fresh edge worker seek minutes ahead of a finite source.
    assert _control_seek_target(0.0, "LOCAL_FINITE_FILE", 79.5) == 0.0


def test_stored_camera_analyses_use_decoder_clock_not_browser_preview():
    assert _stored_file_source_clock("cam-border-01", "stored-video-session")
    assert _stored_file_source_clock("cam-checkpoint-01", "stored-video-session")
    assert not _stored_file_source_clock("cam-border-01", None)
    assert not _stored_file_source_clock("cam-checkpoint-01", None)
    assert not _stored_file_source_clock("another-camera", "stored-video-session")


def test_backend_scoped_paths_do_not_reuse_legacy_or_other_backend_queues():
    production = _runtime_state_paths("cam-border-01", "https://api.example.test")
    development = _runtime_state_paths("cam-border-01", "http://127.0.0.1:8443")

    assert production["sync_db_path"] != development["sync_db_path"]
    assert production["sync_db_path"] != "edge/data/sync_cam-border-01.db"
    assert production["chain_db_path"] != development["chain_db_path"]


def test_cloud_runtime_paths_use_the_persistent_mount(monkeypatch, tmp_path):
    monkeypatch.setenv("EDGE_RUNTIME_DIR", str(tmp_path))
    paths = _runtime_state_paths("cam-border-01", "https://api.example.test")
    assert all(str(value).startswith(str(tmp_path)) for value in paths.values())


def test_replayed_durable_source_receives_an_independent_chain_and_outbox(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGE_RUNTIME_DIR", str(tmp_path))
    first = _runtime_state_paths("cam-border-01", "https://api.example.test", "analysis-run-a")
    replay = _runtime_state_paths("cam-border-01", "https://api.example.test", "analysis-run-b")
    assert first["chain_db_path"] != replay["chain_db_path"]
    assert first["sync_db_path"] != replay["sync_db_path"]


def test_signed_source_is_cached_by_session_without_logging_url(monkeypatch, tmp_path, caplog):
    session_id = str(uuid.uuid4())
    monkeypatch.setenv("EDGE_SOURCE_CACHE_DIR", str(tmp_path))

    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def raise_for_status(self): return None
        def iter_bytes(self, _size): yield b"video-bytes"

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: Stream())
    hydrated = _materialize_remote_source({
        "video_source": "object://video-sessions/cam-border-01/source.mp4",
        "download_url": "https://storage.example.test/source.mp4?secret-signature",
        "video_session_id": session_id,
    }, "cam-border-01")

    cached = Path(hydrated["video_source"])
    assert cached.read_bytes() == b"video-bytes"
    assert "secret-signature" not in caplog.text


def test_failed_durable_download_pauses_instead_of_running_bundled_fallback(monkeypatch, tmp_path):
    session_id = str(uuid.uuid4())
    monkeypatch.setenv("EDGE_SOURCE_CACHE_DIR", str(tmp_path))

    class FailedStream:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def raise_for_status(self): raise httpx.HTTPError("unavailable")

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: FailedStream())
    _set_local_session("demo/videos/uploaded_demo.mp4")
    hydrated = _materialize_remote_source({
        "source_mode": "durable",
        "video_source": "object://video-sessions/cam-border-01/source.mp4",
        "download_url": "https://storage.example.test/source.mp4?secret-signature",
        "video_session_id": session_id,
        "scenario": "normal",
    }, "cam-border-01")

    assert _apply_control_sync(hydrated) is False
    assert _scenario["current"] == "paused"
    assert _scenario["video_session_id"] == session_id
    assert _scenario["video_source"] == "demo/videos/uploaded_demo.mp4"


def test_bundled_control_uses_the_worker_local_source_without_a_session(monkeypatch):
    monkeypatch.setattr(Path, "is_file", lambda self: str(self).replace("\\", "/") == "demo/videos/uploaded_demo.mp4")
    hydrated = _materialize_remote_source({
        "source_mode": "bundled",
        "video_source": "object://stale/source.mp4",
        "download_url": "https://storage.example.test/stale?signature",
        "video_session_id": "stale-session",
        "scenario": "normal",
    }, "cam-checkpoint-01")

    assert hydrated["video_source"] == "demo/videos/uploaded_demo.mp4"
    assert hydrated["video_session_id"] is None
    assert "download_url" not in hydrated
    _set_local_session()
    _scenario["video_session_id"] = "old-session"
    assert _apply_control_sync(hydrated) is True
    assert _scenario["video_session_id"] is None
    assert _scenario["current"] == "normal"
