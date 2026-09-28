"""
NETRAKSH — Dashboard Video API.

Provides authenticated video upload and preview for the Command Center dashboard.
Mounted unconditionally in all environments (not dev-only) because SIH
presentation video functionality is required regardless of ENV mode.

Only exposes the minimum surface needed for the dashboard video workflow:
  POST /api/dashboard/video/upload   — upload presentation video (OPERATOR+)
  GET  /api/dashboard/video/current  — structured current-video state

Scenario-switching and other demo-control endpoints remain restricted to
development via the demo router in main.py.

Surveillance media is deliberately not exposed through a public StaticFiles
mount.  Authenticated endpoints below stream the selected media and demo
telemetry.

Security:
  - All endpoints require OPERATOR or ADMIN role (via require_operator_or_admin)
  - File extension AND MIME type validated before saving
  - Server-controlled filenames — no user-supplied paths
  - No public or unauthenticated access
  - ffmpeg availability checked at runtime; clear actionable error when absent
"""
from __future__ import annotations

import asyncio
import logging
import asyncio
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Request
from fastapi.responses import FileResponse, RedirectResponse

from backend.config import settings
from backend.security.auth import require_edge_auth, require_operator_or_admin
from backend.services.video_storage import (
    activate_bundled_source,
    activate_session,
    get_active_session,
    get_valid_active_session,
    get_uploaded_session,
    signed_media_url,
    start_active_session,
    store_uploaded_session,
    complete_active_session,
    reconcile_inactive_control,
    update_active_session,
)

# Import the shared in-memory state from the demo module.  This is a plain
# module-level dict — the same object across all imports — so writing here
# is immediately visible to the edge runner's /demo/scenario poll (every 5s).
# The import is unconditional because demo.py is always importable (Python
# module loading is independent of whether the router is mounted in main.py).
try:
    from backend.api.demo import _state as _demo_state
except ImportError:
    # Fallback in case demo module is structurally unavailable
    import uuid as _uuid
    _demo_state: dict = {
        "scenario": "paused",
        "video_source": None,
        "video_preview": None,
        "video_session_id": None,
    }


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _reconciled_durable(camera_id: str):
    # Latest telemetry is a read-only proof input. Reconciliation never emits
    # telemetry, changes source identity, increments a generation, or wakes a worker.
    from backend.api.system import _latest_telemetry
    return reconcile_inactive_control(camera_id, _latest_telemetry.get(camera_id))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
    ".flv", ".wmv", ".mpeg", ".mpg", ".m4v",
    ".3gp", ".ogv", ".ts", ".mts", ".m2ts",
})

_ALLOWED_MIME_PREFIX = "video/"
_MAX_VIDEO_UPLOAD_BYTES = 200 * 1024 * 1024
_MAX_DURABLE_VIDEO_BYTES = 49_000_000

# Relative to repo root (where uvicorn is launched)
_VIDEOS_SUBDIR = Path("demo") / "videos"
_BUNDLED_SOURCE = "demo/videos/uploaded_demo.mp4"
_BUNDLED_CAMERA_IDS = frozenset({"cam-border-01", "cam-checkpoint-01"})

# ffprobe/ffmpeg and the synchronous S3 client are deliberately serialized on
# the free backend.  The semaphore bounds expensive normalization without
# blocking FastAPI's event loop, so health/readiness/WebSocket traffic remains
# responsive while a second upload waits its turn.
_NORMALIZATION_SEMAPHORE = asyncio.Semaphore(1)


def _videos_dir() -> Path:
    """Resolved absolute path to demo/videos/, always relative to CWD."""
    return Path(os.getcwd()) / _VIDEOS_SUBDIR


def _confined_media_path(reference: str, *, name_only: bool = False) -> Path:
    """Resolve a media reference and enforce confinement to demo/videos.

    ``name_only`` is used for client-supplied upload selections.  It rejects
    absolute paths, separators and traversal before resolution; state restored
    from older sessions may use the repository-relative ``demo/videos/...``
    form and is still confined by the resolved-path check.
    """
    root = _videos_dir().resolve()
    ref = Path(reference)
    if name_only and (ref.is_absolute() or ref.name != reference):
        raise HTTPException(status_code=400, detail="Invalid media filename")
    candidate = (ref if ref.is_absolute() else (root / ref if name_only else Path(os.getcwd()) / ref)).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Media path is outside the configured video directory")
    return candidate


def _ffmpeg_bin() -> str | None:
    """Return ffmpeg binary path if available on PATH, else None."""
    return shutil.which("ffmpeg")


def _ffprobe_bin() -> str | None:
    """Return ffprobe installed alongside the production ffmpeg package."""
    return shutil.which("ffprobe")


def _probe_video(path: Path, ffprobe: str) -> dict:
    """Decode-probe a candidate and require at least one real video stream."""
    result = subprocess.run(
        [
            ffprobe, "-v", "error", "-show_entries",
            "format=format_name,duration:stream=codec_type,codec_name,width,height",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=400, detail="The uploaded file is not a decodable supported video")
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Unable to inspect the uploaded video") from exc
    if not any(stream.get("codec_type") == "video" for stream in payload.get("streams", [])):
        raise HTTPException(status_code=400, detail="The uploaded file does not contain a video stream")
    return payload


def _normalize_video(source: Path, destination: Path, ffmpeg: str) -> None:
    """Create the one browser/worker H.264 source used by the cloud pipeline."""
    result = subprocess.run(
        [
            ffmpeg, "-y", "-v", "error", "-i", str(source),
            "-map", "0:v:0",
            "-vf", "scale=w='min(960,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-threads", "1",
            "-pix_fmt", "yuv420p", "-an", "-movflags", "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0 or not destination.is_file() or destination.stat().st_size == 0:
        logger.warning("[Dashboard] ffmpeg normalization failed (exit=%s)", result.returncode)
        raise HTTPException(status_code=422, detail="Video normalization failed. Please use a shorter MP4, AVI, MOV, MKV, WebM, or M4V clip.")
    if destination.stat().st_size >= _MAX_DURABLE_VIDEO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Video is too large for the free cloud demo after normalization. Please use a shorter clip.",
        )


def _durable_video_enabled() -> bool:
    """Production uploads use the configured shared S3-compatible store."""
    return settings.OBJECT_STORAGE_PROVIDER == "s3"


def _bundled_control(camera_id: str | None) -> dict:
    """Return camera-scoped control for the immutable worker-bundled demo."""
    target = _demo_state.setdefault("camera_sessions", {}).setdefault(camera_id, {})
    if target.get("source_mode") != "bundled":
        target.clear()
        target.update({
            "source_mode": "bundled",
            "video_source": _BUNDLED_SOURCE,
            "video_session_id": None,
            "scenario": "paused",
            "video_time": 0.0,
            "video_time_updated_at": 0.0,
        })
    return target


def _selected_bundled_control(camera_id: str | None) -> dict | None:
    target = (_demo_state.get("camera_sessions") or {}).get(camera_id)
    if target and target.get("source_mode") == "bundled":
        return target
    if not camera_id or not _durable_video_enabled():
        return None
    stored = get_active_session(camera_id)
    if not stored or stored.get("source_mode") != "bundled":
        return None
    # Mirror the durable control record into process memory for legacy callers
    # and for the response shape returned by the control endpoint.
    target = _bundled_control(camera_id)
    target.update(stored)
    return target


_edge_wake_tasks: dict[str, asyncio.Task] = {}
_edge_prewarm_status: dict[str, dict] = {}
_PREWARM_CAMERA_IDS = ("cam-border-01", "cam-checkpoint-01")
_PREWARM_READY_TTL_SECONDS = 10 * 60
# Free Render instances can take several minutes to cold-start. Keep retries
# bounded. They are shared by explicit START and one dashboard prewarm, never
# by dashboard status polling.
_EDGE_WAKE_RETRY_DELAYS = (2, 3, 5, 8) + (10,) * 28  # ~298 seconds


def _edge_wake_url(camera_id: str | None) -> str:
    env_key = {
        "cam-border-01": "EDGE_WAKE_URL_CAM_BORDER_01",
        "cam-checkpoint-01": "EDGE_WAKE_URL_CAM_CHECKPOINT_01",
    }.get(str(camera_id or ""))
    return os.environ.get(env_key, "").strip() if env_key else ""


def _classify_edge_health(status_code: int, payload: object) -> str:
    """Classify an edge response without treating a listener as an AI worker.

    A Render listener can answer before its background worker reaches the
    durable-control preflight. READY therefore requires the documented health
    body, a true ``worker_alive`` flag, and no terminal error.
    """
    if not 200 <= status_code < 300:
        return "warming"
    if not isinstance(payload, dict):
        return "warming"
    if payload.get("worker_alive") is True and not payload.get("last_error"):
        return "ready"
    return "warming"


def _cache_prewarm_status(camera_id: str, status: str, *, error: str | None = None) -> dict:
    now = time.time()
    previous = _edge_prewarm_status.get(camera_id, {})
    record = {
        "camera_id": camera_id,
        "status": status,
        "requested_at": previous.get("requested_at", now),
        "ready_at": now if status == "ready" else previous.get("ready_at"),
        "last_checked_at": now,
        "error": error,
    }
    _edge_prewarm_status[camera_id] = record
    return record


def _cached_prewarm_status(camera_id: str, *, now: float | None = None) -> dict:
    """Return cache only. This function must never contact an edge service."""
    current = dict(_edge_prewarm_status.get(camera_id) or {
        "camera_id": camera_id,
        "status": "unknown",
        "requested_at": None,
        "ready_at": None,
        "last_checked_at": None,
        "error": None,
    })
    current_time = time.time() if now is None else now
    ready_at = current.get("ready_at")
    if current.get("status") == "ready" and (not ready_at or current_time - ready_at > _PREWARM_READY_TTL_SECONDS):
        current["status"] = "unknown"
        current["error"] = "readiness_expired"
    return current


async def _probe_edge_service(camera_id: str | None) -> str:
    """Probe/wake one free Render edge worker once.

    A sleeping Render service can legitimately answer the first request with a
    transient 502/503 while the container is being restored.  That response is
    therefore "waking", not a terminal failure.
    """
    wake_url = _edge_wake_url(camera_id)
    if not wake_url:
        return "not_configured"
    try:
        timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(f"{wake_url.rstrip('/')}/wake")
            try:
                payload = response.json()
            except (ValueError, json.JSONDecodeError):
                payload = None
            probe_status = _classify_edge_health(response.status_code, payload)
            if probe_status == "ready":
                return "ready"
            logger.info(
                "[Dashboard] Edge wake probe camera_id=%s status=%s; worker still warming",
                camera_id,
                response.status_code,
            )
            return "waking"
    except httpx.HTTPError as exc:
        logger.info(
            "[Dashboard] Edge wake probe camera_id=%s unavailable (%s); retrying",
            camera_id,
            type(exc).__name__,
        )
        return "waking"


async def _retry_edge_wake_until_ready(camera_id: str) -> None:
    """Retry a bounded wake until the sleeping free worker is actually ready.

    The loop is bounded and stops immediately on success.  Normal dashboard
    polling never calls this path, so this does not create a permanent keepalive
    that would defeat Render free-tier sleep.
    """
    try:
        for attempt, delay in enumerate(_EDGE_WAKE_RETRY_DELAYS, start=1):
            await asyncio.sleep(delay)
            status = await _probe_edge_service(camera_id)
            if camera_id in _edge_prewarm_status:
                _cache_prewarm_status(camera_id, status)
            if status == "ready":
                logger.info(
                    "[Dashboard] Edge worker ready camera_id=%s after wake retry=%s",
                    camera_id,
                    attempt,
                )
                return
            if status == "not_configured":
                return
        logger.warning(
            "[Dashboard] Edge worker did not become ready within bounded wake window camera_id=%s",
            camera_id,
        )
        if camera_id in _edge_prewarm_status:
            _cache_prewarm_status(camera_id, "timeout", error="bounded_wake_timeout")
    finally:
        current = asyncio.current_task()
        if _edge_wake_tasks.get(camera_id) is current:
            _edge_wake_tasks.pop(camera_id, None)


async def _wake_edge_service(camera_id: str | None) -> str:
    """Wake a free Render worker and keep retrying transient cold-start failures."""
    status = await _probe_edge_service(camera_id)
    camera_key = str(camera_id or "")
    if status == "waking" and camera_key:
        existing = _edge_wake_tasks.get(camera_key)
        if existing is None or existing.done():
            _edge_wake_tasks[camera_key] = asyncio.create_task(
                _retry_edge_wake_until_ready(camera_key)
            )
    return status


def _eligible_durable_source(camera_id: str) -> bool:
    """Read durable control only; prewarm is forbidden from mutating it."""
    if camera_id not in _PREWARM_CAMERA_IDS:
        return False
    current = get_valid_active_session(camera_id)
    return bool(
        current
        and current.get("source_mode") == "durable"
        and current.get("session_id")
        and current.get("source_object_key")
    )


async def _prewarm_one(camera_id: str) -> dict:
    _cache_prewarm_status(camera_id, "warming")
    status = await _wake_edge_service(camera_id)
    return _cache_prewarm_status(camera_id, status)


def _prewarm_response() -> dict:
    cameras = {camera_id: _cached_prewarm_status(camera_id) for camera_id in _PREWARM_CAMERA_IDS}
    eligible = [camera_id for camera_id, item in cameras.items() if item["status"] != "not_configured"]
    return {
        "eligible": len(eligible),
        "warming": sum(item["status"] == "warming" for item in cameras.values()),
        "ready": sum(item["status"] == "ready" for item in cameras.values()),
        "terminal": sum(item["status"] in {"timeout", "unavailable"} for item in cameras.values()),
        "cameras": cameras,
    }


@router.post("/edge/prewarm")
async def prewarm_edge_workers(_user=Depends(require_operator_or_admin)):
    """Begin one bounded, deduplicated wake for configured durable sources.

    This route deliberately does not invoke any video-control operation. It
    reads durable records, then probes the two independent Render workers in
    parallel. Paused, ready, and completed sources remain in those states.
    """
    eligible = [camera_id for camera_id in _PREWARM_CAMERA_IDS if _eligible_durable_source(camera_id)]
    ineligible = set(_PREWARM_CAMERA_IDS) - set(eligible)
    for camera_id in ineligible:
        _cache_prewarm_status(camera_id, "not_configured")
    if eligible:
        await asyncio.gather(*(_prewarm_one(camera_id) for camera_id in eligible))
    return _prewarm_response()


@router.get("/edge/prewarm/status")
async def get_edge_prewarm_status(_user=Depends(require_operator_or_admin)):
    """Read the bounded in-process readiness cache; never wake an edge worker."""
    return _prewarm_response()


def _session_media_path(session_id: str) -> Path | None:
    """Resolve the browser preview belonging to exactly one upload session."""
    try:
        normalized = str(uuid.UUID(session_id))
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid video session ID")
    vdir = _videos_dir().resolve()
    preview = vdir / f"uploaded_{normalized}_preview.mp4"
    if preview.is_file() and preview.stat().st_size > 0:
        return preview
    candidates = [
        path for path in vdir.glob(f"uploaded_{normalized}.*")
        if path.suffix.lower() in _ALLOWED_EXTENSIONS and not path.name.endswith("_preview.mp4")
    ]
    return candidates[0] if len(candidates) == 1 and candidates[0].is_file() else None


# ---------------------------------------------------------------------------
# GET /api/dashboard/video/current
# ---------------------------------------------------------------------------

@router.get("/video/current")
async def get_current_video(request: Request, _user=Depends(require_operator_or_admin)):
    """
    Return the structured state of the currently active dashboard video.

    The frontend should call this on mount to discover any pre-existing video
    from a previous session, instead of guessing filenames.

    Returns one of:
      { "available": false }
      { "available": false, "error": "no_browser_preview", "hint": "...", "source_name": "..." }
      {
        "available": true,
        "preview_url": "/api/dashboard/video/current/media",
        "source_name": "uploaded_demo_preview.mp4",
        "session_id": "<uuid>",
        "processing_status": "active"
      }
    """
    camera_id = request.query_params.get("camera_id")
    if _durable_video_enabled() and camera_id:
        selected_bundled = _selected_bundled_control(camera_id)
        if selected_bundled is not None:
            return {
                "available": True,
                "source_mode": "bundled",
                "source_name": "BUNDLED CLOUD DEMO",
                "preview_url": "/api/dashboard/video/current/media",
                "session_id": None,
                "camera_id": camera_id,
                "scenario": selected_bundled.get("scenario", "paused"),
                "processing_status": "active" if selected_bundled.get("scenario") == "normal" else "idle",
            }
        durable = _reconciled_durable(camera_id)
        if durable:
            preview_key = durable.get("preview_object_key")
            source_key = durable.get("source_object_key")
            browser_key = preview_key or (source_key if durable.get("content_type") == "video/mp4" else None)
            if not browser_key:
                return {
                    # A source is still authoritative even when a browser
                    # preview cannot be made.  Returning false here made a
                    # cold restore falsely advertise an empty camera slot.
                    "available": True,
                    "source_mode": "durable",
                    "camera_id": camera_id,
                    "error": "no_browser_preview",
                    "source_name": durable.get("source_name"),
                    "session_id": durable.get("session_id"),
                    "scenario": durable.get("scenario", "paused"),
                    "analysis_state": durable.get("analysis_state", "READY"),
                    "analysis_generation": durable.get("analysis_generation", 0),
                    "latest_analysis_session_id": durable.get("latest_analysis_session_id"),
                    "completion_time": durable.get("completion_time"),
                }
            session_id = durable.get("session_id")
            return {
                "available": True,
                "source_mode": "durable",
                "preview_url": f"/api/dashboard/video/media/{session_id}?camera_id={camera_id}",
                "source_name": durable.get("source_name"),
                "session_id": session_id,
                "camera_id": camera_id,
                "scenario": durable.get("scenario", "paused"),
                "processing_status": durable.get("analysis_state", "READY").lower(),
                "analysis_state": durable.get("analysis_state", "READY"),
                "analysis_generation": durable.get("analysis_generation", 0),
                "video_time": durable.get("video_time", 0.0),
                "video_time_updated_at": durable.get("video_time_updated_at", 0.0),
                "completion_time": durable.get("completion_time"),
                "latest_analysis_session_id": durable.get("latest_analysis_session_id"),
            }
        if camera_id in _BUNDLED_CAMERA_IDS:
            bundled = _bundled_control(camera_id)
            return {
                "available": True,
                "source_mode": "bundled",
                "source_name": "BUNDLED CLOUD DEMO",
                "preview_url": "/api/dashboard/video/current/media",
                "session_id": None,
                "camera_id": camera_id,
                "scenario": bundled.get("scenario", "paused"),
                "processing_status": "active" if bundled.get("scenario") == "normal" else "idle",
            }
    scoped = (_demo_state.get("camera_sessions") or {}).get(camera_id, {}) if camera_id else {}
    source: str | None = scoped.get("video_source") if camera_id else _demo_state.get("video_source")
    session_id: str | None = scoped.get("video_session_id") if camera_id else _demo_state.get("video_session_id")
    scenario: str = scoped.get("scenario", _demo_state.get("scenario", "paused"))

    if not source:
        return {"available": False, "camera_id": camera_id}

    vdir = _videos_dir()
    source_path = Path(source)
    try:
        abs_source = _confined_media_path(source)
    except HTTPException:
        logger.warning("Rejected out-of-directory dashboard media state")
        return {"available": False, "error": "invalid_media_path"}

    # Priority 1: explicit ffmpeg-converted preview for this upload session.
    # Older sessions used one global preview filename, so retain that path only
    # for the legacy global source.
    preview_source = scoped.get("video_preview", _demo_state.get("video_preview"))
    if preview_source:
        try:
            preview_path = _confined_media_path(preview_source)
        except HTTPException:
            preview_path = None
    elif source_path.name.startswith("uploaded_demo"):
        preview_path = vdir / "uploaded_demo_preview.mp4"
    else:
        preview_path = None
    if preview_path and preview_path.exists() and preview_path.stat().st_size > 0:
        return {
            "available": True,
            "preview_url": f"/api/dashboard/video/media/{session_id}",
            "source_name": preview_path.name,
            "session_id": session_id,
            "camera_id": camera_id,
            "scenario": scenario,
            "processing_status": "active",
        }

    # Priority 2: original file is already MP4
    if abs_source.exists() and abs_source.suffix.lower() == ".mp4":
        return {
            "available": True,
            "preview_url": (
                "/api/dashboard/video/current/media"
                if abs_source.name == "uploaded_demo.mp4"
                else f"/api/dashboard/video/media/{session_id}"
            ),
            "source_name": abs_source.name,
            "session_id": session_id,
            "camera_id": camera_id,
            "scenario": scenario,
            "processing_status": "active",
        }

    # Non-MP4 file with no preview available
    if abs_source.exists():
        return {
            "available": False,
            "error": "no_browser_preview",
            "source_name": abs_source.name,
            "hint": (
                "ffmpeg is not installed — upload an MP4 file for in-browser playback. "
                "The file is still queued for edge processing."
            ),
        }

    return {"available": False}


# ---------------------------------------------------------------------------
# GET /api/dashboard/video/internal-sync
# ---------------------------------------------------------------------------

@router.get("/video/internal-sync")
async def get_internal_sync(request: Request, _edge=Depends(require_edge_auth)):
    """
    Edge-authenticated control endpoint for workers to poll the current logical
    video source and session. Object-backed sources include a short-lived
    download URL; credentials are never returned.
    """
    camera_id = request.query_params.get("camera_id")
    if _durable_video_enabled() and camera_id:
        selected_bundled = _selected_bundled_control(camera_id)
        if selected_bundled is not None:
            return {
                "source_mode": "bundled",
                "video_source": _BUNDLED_SOURCE,
                "video_session_id": None,
                "scenario": selected_bundled.get("scenario", "paused"),
                "video_time": selected_bundled.get("video_time", 0.0),
                "video_time_updated_at": selected_bundled.get("video_time_updated_at", 0.0),
                "camera_id": camera_id,
            }
        durable = _reconciled_durable(camera_id)
        if durable:
            source_key = durable.get("source_object_key")
            return {
                "video_source": f"object://{source_key}",
                "source_mode": "durable",
                "download_url": signed_media_url(source_key) if source_key else None,
                "video_session_id": durable.get("session_id"),
                "source_name": durable.get("source_name"),
                "scenario": durable.get("scenario", "paused"),
                "analysis_state": durable.get("analysis_state", "READY"),
                "analysis_generation": durable.get("analysis_generation", 0),
                "video_time": durable.get("video_time", 0.0),
                "video_time_updated_at": durable.get("video_time_updated_at", 0.0),
                "completion_time": durable.get("completion_time"),
                "camera_id": camera_id,
            }
        if camera_id in _BUNDLED_CAMERA_IDS:
            bundled = _bundled_control(camera_id)
            return {
                "source_mode": "bundled",
                "video_source": _BUNDLED_SOURCE,
                "video_session_id": None,
                "scenario": bundled.get("scenario", "paused"),
                "video_time": bundled.get("video_time", 0.0),
                "video_time_updated_at": bundled.get("video_time_updated_at", 0.0),
                "camera_id": camera_id,
            }
    scoped = (_demo_state.get("camera_sessions") or {}).get(camera_id, {}) if camera_id else {}
    return {
        "video_source": scoped.get("video_source", _demo_state.get("video_source")),
        "video_session_id": scoped.get("video_session_id", _demo_state.get("video_session_id")),
        "scenario": scoped.get("scenario", _demo_state.get("scenario", "normal")),
        "video_time": scoped.get("video_time", _demo_state.get("video_time", 0.0)),
        "video_time_updated_at": scoped.get("video_time_updated_at", _demo_state.get("video_time_updated_at", 0.0)),
        "camera_id": camera_id,
    }


@router.post("/video/scenario")
async def post_video_scenario(
    payload: dict,
    _user=Depends(require_operator_or_admin)
):
    """
    Authenticated endpoint for the frontend to control the demo scenario
    (e.g., play/pause) and update the session ID or video time.
    """
    requested = payload.get("scenario")
    camera_id = payload.get("camera_id")
    requested_mode = payload.get("source_mode")
    control_action = payload.get("control_action")
    is_explicit_start = requested == "normal" and payload.get("wake_edge") is True
    is_explicit_stop = requested in {"paused", "stopped"} and control_action == "stop"
    is_authoritative_control = is_explicit_start or is_explicit_stop
    if requested_mode not in {None, "bundled", "durable"}:
        raise HTTPException(status_code=400, detail="Invalid video source mode")
    if control_action not in {None, "stop"}:
        raise HTTPException(status_code=400, detail="Invalid camera control action")
    active_session = None
    if _durable_video_enabled() and camera_id:
        active_session = get_valid_active_session(camera_id)
        requested_session_id = payload.get("video_session_id")
        # A browser can retain a legacy local-storage slot after its upload
        # was never persisted to object storage.  Do not let that obsolete
        # identifier pause or seek the configured cloud replay.  A real,
        # activated durable session remains fully controllable as before.
        if is_authoritative_control and requested_mode == "bundled" and requested_session_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Bundled video source must not include a durable session ID",
            )
        # The bundled clip is a fallback, not an implicit replacement for a
        # stored user upload. A stale browser/restore race must never destroy
        # the durable control pointer. An intentional operator reset must opt
        # in explicitly with replace_source=true.
        if (
            is_authoritative_control
            and requested_mode == "bundled"
            and active_session is not None
            and payload.get("replace_source") is not True
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A durable upload is active for this camera; bundled fallback cannot replace it implicitly",
            )
        if is_authoritative_control and requested_mode == "durable" and (
            not requested_session_id
            or active_session is None
            or requested_session_id != active_session.get("session_id")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Video session is not the active durable source for this camera",
            )
        if is_authoritative_control and requested_mode is None and requested_session_id and (
            active_session is None
            or requested_session_id != active_session.get("session_id")
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Video session is not the active durable source for this camera",
            )
    if is_authoritative_control and requested_mode == "bundled" and camera_id:
        target = _bundled_control(camera_id)
    else:
        target = _demo_state.setdefault("camera_sessions", {}).setdefault(camera_id, {}) if camera_id else _demo_state
    if is_authoritative_control:
        target["scenario"] = requested
    if is_authoritative_control and requested_mode == "bundled":
        target["source_mode"] = "bundled"
        target["video_source"] = _BUNDLED_SOURCE
        target["video_session_id"] = None
    elif is_authoritative_control and "video_session_id" in payload:
        target["video_session_id"] = payload["video_session_id"]
    session_matches = (
        active_session is not None
        and payload.get("video_session_id") == active_session.get("session_id")
    )
    if "video_time" in payload and (is_authoritative_control or session_matches):
        target["video_time"] = float(payload["video_time"])
        import time
        target["video_time_updated_at"] = time.time()
    if _durable_video_enabled() and camera_id and is_authoritative_control and requested_mode == "bundled":
        stored = activate_bundled_source(
            camera_id,
            scenario=target["scenario"],
            video_source=_BUNDLED_SOURCE,
            video_time=target.get("video_time", 0.0),
            video_time_updated_at=target.get("video_time_updated_at", 0.0),
        )
        target.update(stored)
    if _durable_video_enabled() and camera_id:
        changes = {
            key: target[key]
            for key in ("scenario", "video_time", "video_time_updated_at")
            if key in target
        }
        if active_session is not None and requested_mode != "bundled" and (is_authoritative_control or session_matches):
            if is_explicit_start:
                try:
                    active_session, created_generation = start_active_session(camera_id, payload.get("video_session_id"))
                except FileNotFoundError as exc:
                    raise HTTPException(status_code=409, detail=str(exc)) from exc
                target.update(active_session)
                edge_status = await _wake_edge_service(camera_id)
                logger.info(
                    "[Dashboard] Camera control camera_id=%s source_mode=%s action=start scenario=%s wake=%s edge_status=%s",
                    camera_id,
                    requested_mode,
                    active_session.get("scenario"),
                    True,
                    edge_status,
                )
                return {
                    "status": "success",
                    "state": _demo_state,
                    "edge_status": edge_status,
                    "analysis_state": active_session.get("analysis_state"),
                    "analysis_generation": active_session.get("analysis_generation"),
                    "scenario": active_session.get("scenario"),
                    "replay_started": created_generation,
                    "control_repaired": active_session.get("control_repaired", False),
                }
            updated_session = update_active_session(camera_id, changes)
            if is_explicit_stop and updated_session is not None:
                target.update(updated_session)
                return {
                    "status": "success",
                    "state": _demo_state,
                    "edge_status": "not_requested",
                    "analysis_state": updated_session.get("analysis_state"),
                    "analysis_generation": updated_session.get("analysis_generation"),
                    "scenario": updated_session.get("scenario"),
                }
    edge_status = "not_requested"
    # Browser playback reports its current time every two seconds.  Those
    # synchronization heartbeats (including pause/metadata events) must never
    # keep a sleeping free-tier worker awake.  Waking is an explicit operator
    # action, requested only by START / ANALYZE in the dashboard.
    if camera_id and is_explicit_start:
        edge_status = await _wake_edge_service(camera_id)
    if is_authoritative_control:
        logger.info(
            "[Dashboard] Camera control camera_id=%s source_mode=%s action=%s scenario=%s wake=%s edge_status=%s",
            camera_id,
            requested_mode,
            "start" if is_explicit_start else "stop",
            requested,
            is_explicit_start,
            edge_status,
        )
    return {"status": "success", "state": _demo_state, "edge_status": edge_status}


@router.post("/video/internal-complete")
async def complete_dashboard_video(payload: dict, _edge=Depends(require_edge_auth)):
    """Edge-only, idempotent EOF callback for one durable analysis generation."""
    camera_id = str(payload.get("camera_id") or "")
    session_id = str(payload.get("video_session_id") or "")
    try:
        generation = int(payload.get("analysis_generation"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="analysis_generation is required")
    if not camera_id or not session_id:
        raise HTTPException(status_code=400, detail="camera_id and video_session_id are required")
    changes = {
        "latest_analysis_session_id": payload.get("analysis_session_id"),
        "final_frame_index": payload.get("final_frame_index"),
        "video_time": float(payload.get("final_video_time") or 0.0),
        "video_time_updated_at": time.time(),
    }
    completed = complete_active_session(camera_id, session_id, generation, changes)
    if completed is None:
        raise HTTPException(status_code=409, detail="Completion does not match active durable generation")
    return {"status": "completed", "analysis_state": "COMPLETED", "analysis_generation": completed.get("analysis_generation")}


# ---------------------------------------------------------------------------
# GET /api/dashboard/video/current/media
# ---------------------------------------------------------------------------

@router.get("/video/current/media")
async def get_current_video_media(_user=Depends(require_operator_or_admin)):
    """
    Securely serve the current dashboard video media using an authenticated endpoint.
    """
    source: str | None = _demo_state.get("video_source")
    if not source:
        raise HTTPException(status_code=404, detail="No video available")

    vdir = _videos_dir()
    source_path = Path(source)
    abs_source = _confined_media_path(source)

    # Priority 1: explicit ffmpeg-converted preview for this upload session.
    preview_source = _demo_state.get("video_preview")
    if preview_source:
        preview_path = _confined_media_path(preview_source)
    elif source_path.name.startswith("uploaded_demo"):
        preview_path = vdir / "uploaded_demo_preview.mp4"
    else:
        preview_path = None
    if preview_path and preview_path.exists() and preview_path.stat().st_size > 0:
        return FileResponse(preview_path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

    # Priority 2: original file is already MP4
    if abs_source.exists() and abs_source.suffix.lower() == ".mp4":
        return FileResponse(abs_source, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})

    raise HTTPException(status_code=404, detail="Media file not found")


@router.get("/video/media/{session_id}")
async def get_video_media_by_session(
    session_id: str,
    request: Request,
    _user=Depends(require_operator_or_admin),
):
    """Serve one immutable upload session without consulting global state."""
    camera_id = request.query_params.get("camera_id")
    if _durable_video_enabled() and camera_id:
        durable = get_uploaded_session(camera_id, session_id)
        if not durable:
            raise HTTPException(status_code=404, detail="Video session media not found")
        object_key = durable.get("preview_object_key")
        if not object_key and durable.get("content_type") == "video/mp4":
            object_key = durable.get("source_object_key")
        url = signed_media_url(object_key) if object_key else None
        if not url:
            raise HTTPException(status_code=415, detail="This video has no browser-compatible MP4 preview")
        return RedirectResponse(url=url, status_code=307)
    media_path = _session_media_path(session_id)
    if not media_path:
        raise HTTPException(status_code=404, detail="Video session media not found")
    if media_path.suffix.lower() != ".mp4":
        raise HTTPException(status_code=415, detail="This video has no browser-compatible MP4 preview")
    return FileResponse(media_path, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})


@router.get("/video/demo-telemetry")
async def get_demo_telemetry(_user=Depends(require_operator_or_admin)):
    """Serve the deterministic demo overlay cache without public file access."""
    telemetry_path = _videos_dir().resolve() / "vtest_telemetry.json"
    if not telemetry_path.is_file():
        raise HTTPException(status_code=404, detail="Demo telemetry is not available")
    return FileResponse(telemetry_path, media_type="application/json")



# ---------------------------------------------------------------------------
# POST /api/dashboard/video/upload
# ---------------------------------------------------------------------------

@router.post("/video/upload", status_code=status.HTTP_200_OK)
async def upload_dashboard_video(
    file: UploadFile = File(...),
    camera_id: str | None = Form(None),
    _user=Depends(require_operator_or_admin),
):
    """Validate and normalize one upload for both browser and edge analysis."""
    content_type = (file.content_type or "").lower()
    # Browsers on Windows sometimes omit the MIME type.  The extension, magic
    # bytes and ffprobe are authoritative; a declared non-video type is not.
    if content_type and not content_type.startswith(_ALLOWED_MIME_PREFIX):
        raise HTTPException(
            status_code=400,
            detail=f"Only video files are accepted (received Content-Type: {content_type or 'unknown'})",
        )

    original_name = "".join(
        character for character in Path(file.filename or "upload").name
        if character.isprintable()
    ).strip()[:255] or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported video extension '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )
    if _durable_video_enabled() and not camera_id:
        raise HTTPException(status_code=400, detail="camera_id is required for durable video uploads")

    vdir = _videos_dir()
    vdir.mkdir(parents=True, exist_ok=True)
    new_session_id = str(uuid.uuid4())
    incoming_path = vdir / f"incoming_{new_session_id}{ext}"
    normalized_name = f"uploaded_{new_session_id}.mp4"
    normalized_path = vdir / normalized_name
    durable = _durable_video_enabled()
    ffmpeg = _ffmpeg_bin()
    ffprobe = _ffprobe_bin()

    try:
        total = 0
        with open(incoming_path, "wb") as buf:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_VIDEO_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Video upload exceeds the 200 MiB limit")
                buf.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="Video upload is empty")
        with open(incoming_path, "rb") as probe:
            signature = probe.read(16)
        valid_signature = (
            (ext in {".mp4", ".m4v", ".mov"} and b"ftyp" in signature)
            or (ext == ".avi" and signature[:4] == b"RIFF")
            or (ext in {".webm", ".mkv"} and signature[:4] == b"\x1a\x45\xdf\xa3")
            or ext in {".flv", ".wmv", ".mpeg", ".mpg", ".3gp", ".ogv", ".ts", ".mts", ".m2ts"}
        )
        if not valid_signature:
            raise HTTPException(status_code=400, detail="Uploaded file does not match a supported video signature")

        if durable and (not ffmpeg or not ffprobe):
            raise HTTPException(status_code=503, detail="Cloud video normalization is temporarily unavailable")

        async with _NORMALIZATION_SEMAPHORE:
            if ffprobe:
                await asyncio.to_thread(_probe_video, incoming_path, ffprobe)

            if ffmpeg:
                await asyncio.to_thread(_normalize_video, incoming_path, normalized_path, ffmpeg)
            elif ext == ".mp4":
                # Development-only compatibility. Production durable uploads must
                # pass through ffmpeg so browser playback and inference cannot split.
                await asyncio.to_thread(shutil.copyfile, incoming_path, normalized_path)
            else:
                raise HTTPException(status_code=503, detail="ffmpeg is required to normalize this video format")

        normalized_size = normalized_path.stat().st_size
        if durable:
            await asyncio.to_thread(
                store_uploaded_session,
                camera_id=camera_id,
                session_id=new_session_id,
                source_path=normalized_path,
                preview_path=None,
                source_name=original_name,
                content_type="video/mp4",
            )
            preview_url = f"/api/dashboard/video/media/{new_session_id}?camera_id={camera_id}"
        else:
            preview_url = f"/api/dashboard/video/media/{new_session_id}"

        if camera_id:
            _demo_state.setdefault("uploaded_sources", {}).setdefault(camera_id, {})[new_session_id] = {
                "source_name": normalized_name,
                "original_name": original_name,
                "preview_name": None,
            }

        logger.info(
            "[Dashboard] Normalized upload accepted camera_id=%s session=%s bytes=%s",
            camera_id,
            new_session_id[:8],
            normalized_size,
        )
        return {
            "status": "ok",
            "preview_url": preview_url,
            "session_id": new_session_id,
            "source_name": original_name,
            "normalized_name": normalized_name,
            "camera_id": camera_id,
            "ffmpeg_available": bool(ffmpeg),
            "normalized_size_bytes": normalized_size,
            "message": "Video normalized and stored. Press START to wake analysis for this camera.",
        }
    except HTTPException:
        raise
    except OSError as exc:
        logger.exception("[Dashboard] Failed to store uploaded video")
        raise HTTPException(status_code=500, detail="Failed to store the uploaded video") from exc
    except Exception as exc:
        logger.exception("[Dashboard] Durable video upload failed")
        raise HTTPException(status_code=502, detail="Durable video storage failed") from exc
    finally:
        # Durable uploads live only in object storage.  Never let Render's
        # ephemeral disk become a second, divergent source of truth.
        incoming_path.unlink(missing_ok=True)
        if durable:
            normalized_path.unlink(missing_ok=True)

# ---------------------------------------------------------------------------
# POST /api/dashboard/video/analyze
# ---------------------------------------------------------------------------
from pydantic import BaseModel

class AnalyzeRequest(BaseModel):
    session_id: str
    source_name: str
    preview_name: str | None = None
    camera_id: str | None = None

@router.post("/video/analyze", status_code=status.HTTP_200_OK)
async def analyze_dashboard_video(
    req: AnalyzeRequest,
    _user=Depends(require_operator_or_admin),
):
    """
    Trigger the Edge processor to begin analysis of an uploaded video.
    This separates upload (buffering/transcoding) from actual playback/analysis,
    allowing the frontend to stay paused until the user hits Play.
    """
    if _durable_video_enabled():
        if not req.camera_id:
            raise HTTPException(status_code=400, detail="camera_id is required")
        durable = get_uploaded_session(req.camera_id, req.session_id)
        if not durable:
            raise HTTPException(status_code=404, detail="Video session was not found in durable storage")
        if durable.get("source_name") != req.source_name:
            raise HTTPException(status_code=409, detail="Video session is not associated with this camera/source")
        activate_session(req.camera_id, req.session_id)
        return {"status": "ok", "message": "Video ready. Press START to wake analysis."}

    registered = None
    if req.camera_id:
        registered = (
            _demo_state.get("uploaded_sources", {})
            .get(req.camera_id, {})
            .get(req.session_id)
        )
    registered_source = registered.get("source_name") if registered else req.source_name
    if registered and registered.get("original_name") not in {None, req.source_name}:
        raise HTTPException(status_code=409, detail="Video session is not associated with this camera/source")

    target_path = _confined_media_path(registered_source, name_only=True)
    if target_path.suffix.lower() not in _ALLOWED_EXTENSIONS or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found. Please upload again.")

    preview_path = None
    if req.preview_name:
        candidate = _confined_media_path(req.preview_name, name_only=True)
        if candidate.suffix.lower() != ".mp4" or not candidate.is_file():
            raise HTTPException(status_code=404, detail="Video preview file not found")
        preview_path = candidate

    _demo_state["video_source"] = str(Path("demo") / "videos" / target_path.name)
    _demo_state["video_preview"] = (
        str(Path("demo") / "videos" / preview_path.name)
        if preview_path
        else None
    )
    _demo_state["video_session_id"] = req.session_id
    if req.camera_id:
        _demo_state.setdefault("camera_sessions", {})[req.camera_id] = {
            "video_source": _demo_state["video_source"],
            "video_preview": _demo_state["video_preview"],
            "video_session_id": req.session_id,
            "scenario": "paused",
            "video_time": 0.0,
            "video_time_updated_at": time.time(),
        }

    logger.info(
        f"[Dashboard] Analysis triggered: source={_demo_state['video_source']} "
        f"session={req.session_id}"
    )

    return {"status": "ok", "message": "Analysis started"}
