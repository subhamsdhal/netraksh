"""
NETRAKSH — Demo Scenario API (local prototype only).

GET  /demo/scenario  — return current active scenario
POST /demo/scenario  — set active scenario

No authentication required — this endpoint exists exclusively for the
local SIH prototype demo.  It MUST NOT be included in any non-local
deployment (see docs/LIMITATIONS.md).

Scenario values (matching the frontend DemoSidebar):
  'normal'  — full-pipeline nominal operation
  'fog'     — simulated FOG_RAIN scene condition (natural image degradation)
  'failure' — simulated camera failure → Gate 1 FAILED → ABSTAIN
  'offline' — simulated network loss → sync client queues locally

The edge pipeline polls GET /demo/scenario every 5 s and reacts:
  * failure → CameraAdapter simulate_frozen=True → CameraHealthMonitor
              detects frozen stream → health_state=FAILED → Gate 1
              hard-override → decision_state=ABSTAIN
  * fog     → CameraAdapter applies Gaussian blur + contrast reduction
              so SceneConditionClassifier naturally classifies FOG_RAIN
              and S drops; R is not hardcoded
  * offline → SyncClient pauses its outbound POST loop; events continue
              to accumulate in the local SQLite queue (existing behaviour)
  * normal  → no modifications; all simulation flags cleared
"""

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from backend.database.session import get_db
import shutil
import os
import uuid
import subprocess
from backend.security.auth import get_current_user

router = APIRouter(prefix="/demo", tags=["demo"])

# ---------------------------------------------------------------------------
# In-memory scenario state — a plain dict so any import of this module
# shares the same object.  Resets to 'normal' on each server restart.
# ---------------------------------------------------------------------------
_state: dict = {
    "scenario": "normal",
    "video_source": "demo/videos/uploaded_demo.mp4",
    "video_preview": None,
    "video_session_id": str(uuid.uuid4()),
    "camera_sessions": {},
}

_VALID_SCENARIOS = frozenset({"normal", "fog", "failure", "offline", "paused"})


from backend.security.auth import get_current_user, require_edge_auth, get_edge_identity, require_operator_or_admin
from backend.config import settings
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import logging

logger = logging.getLogger(__name__)

async def require_demo_access(
    request: Request,
    db: Session = Depends(get_db)
):
    if settings.ENV != "development":
        raise HTTPException(status_code=404, detail="Not Found")

    """Allow either edge node (edge token) or dashboard (JWT operator/admin)"""
    # 1. Try edge token
    try:
        if get_edge_identity(request, db) is not None:
            return True
    except HTTPException:
        pass
        
    auth_header = request.headers.get("Authorization", "")
    expected = os.environ.get("EDGE_AUTH_TOKEN", "")
    if expected and auth_header == f"Bearer {expected}":
        return True
        
    # 2. Try JWT
    try:
        # get_current_user expects HTTPAuthorizationCredentials
        if not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Demo access requires authentication")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header.replace("Bearer ", ""))
        user = get_current_user(creds, db)
        if user.role in ("ADMIN", "OPERATOR"):
            return True
    except HTTPException:
        pass
        
    raise HTTPException(status_code=401, detail="Demo access requires authentication")


@router.get("/scenario", dependencies=[Depends(require_demo_access)])
async def get_scenario():
    """Return the currently active demo scenario and video source."""
    return {
        "scenario": _state["scenario"],
        "video_source": _state["video_source"],
        "video_session_id": _state["video_session_id"],
        "video_time": _state.get("video_time", 0.0),
        "video_time_updated_at": _state.get("video_time_updated_at", 0.0),
    }


@router.post("/scenario", dependencies=[Depends(require_demo_access)])
async def set_scenario(payload: dict):
    """
    Set the active demo scenario.  Accepts { "scenario": "<value>" }.
    Unknown values are silently ignored (scenario stays unchanged) so a
    stale frontend tab cannot break a running demo.
    """
    requested = payload.get("scenario", "normal")
    if requested in _VALID_SCENARIOS:
        _state["scenario"] = requested
    if "video_session_id" in payload:
        _state["video_session_id"] = payload["video_session_id"]
    if "video_time" in payload:
        _state["video_time"] = float(payload["video_time"])
        import time
        _state["video_time_updated_at"] = time.time()
    return {
        "scenario": _state["scenario"],
        "video_source": _state["video_source"],
        "video_session_id": _state["video_session_id"],
        "video_time": _state.get("video_time", 0.0),
        "video_time_updated_at": _state.get("video_time_updated_at", 0.0),
    }

from backend.security.auth import require_operator_or_admin

@router.post("/upload")
async def upload_video(file: UploadFile = File(...), current_user = Depends(require_operator_or_admin)):
    """
    Upload a new video for the edge pipeline to process.
    Requires ADMIN or OPERATOR role. Only accepts video files.
    """
    if not file.content_type.startswith("video/"):
        raise HTTPException(status_code=400, detail="Only video files are supported")

    # Ensure target directory exists
    target_dir = os.path.join(os.getcwd(), "demo", "videos")
    os.makedirs(target_dir, exist_ok=True)
    
    session_id = str(uuid.uuid4())

    # Save as uploaded_<uuid>.mp4 (or appropriate extension)
    ext = os.path.splitext(file.filename)[1]
    if not ext:
        ext = ".mp4"
    filename_base = f"uploaded_{session_id}"
    target_path = os.path.join(target_dir, f"{filename_base}{ext}")
    
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video file: {str(e)}")

    # Keep the original source for the edge pipeline.  Browser playback is a
    # separate concern: Chromium cannot decode the DivX-3/MJPEG codecs commonly
    # found in uploaded AVI demo files, so create a small H.264/AAC preview when
    # ffmpeg is available in the runtime.
    preview_url = None
    ffmpeg = shutil.which("ffmpeg")
    preview_filename = f"{filename_base}_preview.mp4"
    preview_path = os.path.join(target_dir, preview_filename)
    if ffmpeg:
        try:
            result = subprocess.run(
                [ffmpeg, "-y", "-i", target_path,
                 "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-movflags", "+faststart", preview_path],
                capture_output=True, text=True, timeout=120, check=False,
            )
            if result.returncode == 0 and os.path.exists(preview_path):
                preview_url = "/api/dashboard/video/current/media"
        except (OSError, subprocess.SubprocessError):
            preview_url = None

    # Update state so edge pipeline detects the new source
    # Convert to relative path for edge pipeline
    rel_path = f"demo/videos/{filename_base}{ext}"
    _state["video_source"] = rel_path
    _state["video_session_id"] = session_id
    
    return {
        "status": "success",
        "video_source": rel_path,
        "video_session_id": _state["video_session_id"],
        "preview_url": preview_url,
    }
