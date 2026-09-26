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

import logging
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
    activate_session,
    get_valid_active_session,
    get_uploaded_session,
    signed_media_url,
    store_uploaded_session,
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

# Relative to repo root (where uvicorn is launched)
_VIDEOS_SUBDIR = Path("demo") / "videos"
_BUNDLED_SOURCE = "demo/videos/uploaded_demo.mp4"
_BUNDLED_CAMERA_IDS = frozenset({"cam-border-01", "cam-checkpoint-01"})


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
    return target if target and target.get("source_mode") == "bundled" else None


async def _wake_edge_service(camera_id: str | None) -> str:
    """Best-effort wake request for a free Render edge web service."""
    env_key = {
        "cam-border-01": "EDGE_WAKE_URL_CAM_BORDER_01",
        "cam-checkpoint-01": "EDGE_WAKE_URL_CAM_CHECKPOINT_01",
    }.get(str(camera_id or ""))
    wake_url = os.environ.get(env_key, "").strip() if env_key else ""
    if not wake_url:
        return "not_configured"
    try:
        timeout = httpx.Timeout(connect=2.0, read=5.0, write=2.0, pool=2.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.get(f"{wake_url.rstrip('/')}/wake")
            return "ready" if response.is_success else "waking"
    except httpx.HTTPError as exc:
        logger.info("[Dashboard] Edge wake request unavailable (%s)", type(exc).__name__)
        return "waking"


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
                "session_id": None,
                "camera_id": camera_id,
                "scenario": selected_bundled.get("scenario", "paused"),
                "processing_status": "idle",
            }
        durable = get_valid_active_session(camera_id)
        if durable:
            preview_key = durable.get("preview_object_key")
            source_key = durable.get("source_object_key")
            browser_key = preview_key or (source_key if durable.get("content_type") == "video/mp4" else None)
            if not browser_key:
                return {
                    "available": False,
                    "camera_id": camera_id,
                    "error": "no_browser_preview",
                    "source_name": durable.get("source_name"),
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
                "processing_status": "active",
            }
        if camera_id in _BUNDLED_CAMERA_IDS:
            bundled = _bundled_control(camera_id)
            return {
                "available": True,
                "source_mode": "bundled",
                "source_name": "BUNDLED CLOUD DEMO",
                "session_id": None,
                "camera_id": camera_id,
                "scenario": bundled.get("scenario", "paused"),
                "processing_status": "idle",
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
        durable = get_valid_active_session(camera_id)
        if durable:
            source_key = durable.get("source_object_key")
            return {
                "video_source": f"object://{source_key}",
                "source_mode": "durable",
                "download_url": signed_media_url(source_key) if source_key else None,
                "video_session_id": durable.get("session_id"),
                "scenario": durable.get("scenario", "paused"),
                "video_time": durable.get("video_time", 0.0),
                "video_time_updated_at": durable.get("video_time_updated_at", 0.0),
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
    if _durable_video_enabled() and camera_id:
        changes = {
            key: target[key]
            for key in ("scenario", "video_time", "video_time_updated_at")
            if key in target
        }
        if active_session is not None and requested_mode != "bundled" and (is_authoritative_control or session_matches):
            update_active_session(camera_id, changes)
    edge_status = "not_requested"
    # Browser playback reports its current time every two seconds.  Those
    # synchronization heartbeats (including pause/metadata events) must never
    # keep a sleeping free-tier worker awake.  Waking is an explicit operator
    # action, requested only by START / ANALYZE in the dashboard.
    if camera_id and is_explicit_start:
        edge_status = await _wake_edge_service(camera_id)
    return {"status": "success", "state": _demo_state, "edge_status": edge_status}


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
    """
    Upload a presentation video for the dashboard and edge pipeline.
    Requires OPERATOR or ADMIN role.

    ffmpeg behaviour:
      - If ffmpeg is installed: converts to H.264/AAC MP4 (yuv420p, faststart).
      - If ffmpeg is absent AND file is MP4: serves it directly.
      - If ffmpeg is absent AND file is non-MP4: saves for edge processing but
        returns ok_no_preview with a clear actionable message; browser cannot play.

    Returns:
      {
        "status": "ok" | "ok_no_preview",
        "preview_url": "/demo/videos/..." | null,
        "session_id": "<uuid>",
        "source_name": "<filename>",
        "ffmpeg_available": true | false,
        "message": "<human-readable status>"
      }
    """
    # --- Validate MIME type ---
    content_type = (file.content_type or "").lower()
    if not content_type.startswith(_ALLOWED_MIME_PREFIX):
        raise HTTPException(
            status_code=400,
            detail=f"Only video files are accepted (received Content-Type: {content_type or 'unknown'})",
        )

    # --- Validate extension ---
    original_name = file.filename or "upload"
    ext = Path(original_name).suffix.lower()
    if not ext:
        ext = ".mp4"
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported video extension '{ext}'. "
                f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}"
            ),
        )

    # --- Ensure target directory ---
    vdir = _videos_dir()
    vdir.mkdir(parents=True, exist_ok=True)

    # A worker can still have the previous source open while a new upload
    # arrives.  Reusing one fixed filename is therefore a Windows sharing
    # violation race.  Give every session its own server-controlled paths so
    # the active reader and the next writer never contend for the same file.
    new_session_id = str(uuid.uuid4())
    target_name = f"uploaded_{new_session_id}{ext}"
    target_path = vdir / target_name
    try:
        total = 0
        with open(target_path, "wb") as buf:
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
        with open(target_path, "rb") as probe:
            signature = probe.read(16)
        valid_signature = (ext in {".mp4", ".m4v", ".mov"} and b"ftyp" in signature) or (ext == ".avi" and signature[:4] == b"RIFF") or (ext in {".webm", ".mkv"} and signature[:4] == b"\x1a\x45\xdf\xa3")
        if not valid_signature:
            target_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Uploaded file does not match a supported video signature")
    except OSError as exc:
        logger.error(f"[Dashboard] Failed to save uploaded video: {exc}")
        raise HTTPException(status_code=500, detail=f"Failed to save video file: {exc}")

    logger.info(f"[Dashboard] Video saved: {target_path} ({target_path.stat().st_size} bytes)")

    # --- Attempt ffmpeg conversion to browser-compatible H.264 MP4 ---
    ffmpeg = _ffmpeg_bin()
    preview_name = f"uploaded_{new_session_id}_preview.mp4"
    preview_path = vdir / preview_name
    preview_url: str | None = None

    if ffmpeg:
        try:
            result = subprocess.run(
                [
                    ffmpeg, "-y",
                    "-i", str(target_path),
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-movflags", "+faststart",
                    str(preview_path),
                ],
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if result.returncode == 0 and preview_path.exists() and preview_path.stat().st_size > 0:
                preview_url = f"/api/dashboard/video/media/{new_session_id}"
                logger.info(f"[Dashboard] ffmpeg preview created: {preview_path}")
            else:
                logger.warning(
                    f"[Dashboard] ffmpeg exited {result.returncode}. "
                    f"stderr: {result.stderr[-400:]}"
                )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning(f"[Dashboard] ffmpeg conversion failed: {exc}")
    # If no ffmpeg conversion but original is already MP4, serve directly
    if not preview_url and ext == ".mp4":
        preview_url = f"/api/dashboard/video/media/{new_session_id}"
        logger.info("[Dashboard] Serving original MP4 directly (ffmpeg not installed)")

    if _durable_video_enabled():
        if not camera_id:
            target_path.unlink(missing_ok=True)
            preview_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="camera_id is required for durable video uploads")
        try:
            store_uploaded_session(
                camera_id=camera_id,
                session_id=new_session_id,
                source_path=target_path,
                preview_path=preview_path if preview_path.is_file() else None,
                source_name=target_path.name,
                content_type=content_type,
            )
        except Exception:
            logger.exception("[Dashboard] Durable video upload failed")
            raise HTTPException(status_code=502, detail="Durable video storage failed")
        finally:
            target_path.unlink(missing_ok=True)
            preview_path.unlink(missing_ok=True)
        if preview_url:
            preview_url = f"/api/dashboard/video/media/{new_session_id}?camera_id={camera_id}"

    # Do NOT update shared demo state here so edge runner does not start immediately.
    # The frontend will call /analyze to trigger playback.
    if camera_id:
        _demo_state.setdefault("uploaded_sources", {}).setdefault(camera_id, {})[new_session_id] = {
            "source_name": target_path.name,
            "preview_name": preview_name if preview_path.is_file() else None,
        }
    
    if preview_url:
        return {
            "status": "ok",
            "preview_url": preview_url,
            "session_id": new_session_id,
            "source_name": target_path.name,
            "camera_id": camera_id,
            "ffmpeg_available": bool(ffmpeg),
            "message": (
                "Video accepted. Edge processor will pick up the new source "
                "within 5 seconds and begin generating telemetry."
            ),
        }

    # Non-MP4 without ffmpeg — saved for edge, but no browser preview
    return {
        "status": "ok_no_preview",
        "preview_url": None,
        "session_id": new_session_id,
        "source_name": target_path.name,
        "camera_id": camera_id,
        "ffmpeg_available": False,
        "message": (
            f"Video saved for edge processing, but cannot be previewed in the browser "
            f"(ffmpeg is not installed and '{ext}' requires transcoding for Chromium). "
            "Upload an MP4 file for in-browser video playback."
        ),
    }

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
        return {"status": "ok", "message": "Analysis started"}

    target_path = _confined_media_path(req.source_name, name_only=True)
    if target_path.suffix.lower() not in _ALLOWED_EXTENSIONS or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found. Please upload again.")

    preview_path = None
    if req.preview_name:
        candidate = _confined_media_path(req.preview_name, name_only=True)
        if candidate.suffix.lower() != ".mp4" or not candidate.is_file():
            raise HTTPException(status_code=404, detail="Video preview file not found")
        preview_path = candidate

    if req.camera_id:
        registered = (
            _demo_state.get("uploaded_sources", {})
            .get(req.camera_id, {})
            .get(req.session_id)
        )
        if registered and registered.get("source_name") != req.source_name:
            raise HTTPException(status_code=409, detail="Video session is not associated with this camera/source")

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
