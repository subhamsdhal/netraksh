"""Durable object-storage state for dashboard video sessions.

The browser never receives object-store credentials.  The backend writes
immutable video objects and small JSON control records; authenticated edge
workers receive a short-lived download URL for the selected object.
"""
from __future__ import annotations

import json
import mimetypes
import time
from pathlib import Path
from typing import Any

from backend.services.evidence_storage import EvidenceNotFoundError, get_evidence_storage


def _safe_camera_id(camera_id: str) -> str:
    from backend.services.evidence_storage import validate_object_key_segment

    return validate_object_key_segment(camera_id, "camera_id")


def _safe_session_id(session_id: str) -> str:
    from backend.services.evidence_storage import validate_object_key_segment

    return validate_object_key_segment(session_id, "session_id", is_uuid=True)


def session_metadata_key(camera_id: str, session_id: str) -> str:
    return f"video-sessions/{_safe_camera_id(camera_id)}/{_safe_session_id(session_id)}.json"


def control_key(camera_id: str) -> str:
    return f"video-control/{_safe_camera_id(camera_id)}.json"


def preparation_job_key(camera_id: str, job_id: str) -> str:
    return f"video-preparation/{_safe_camera_id(camera_id)}/{_safe_session_id(job_id)}.json"


def preparation_control_key(camera_id: str) -> str:
    return f"video-preparation/{_safe_camera_id(camera_id)}/current.json"


def preparation_upload_key(camera_id: str, job_id: str, suffix: str) -> str:
    normalized_suffix = suffix.lower()
    if not normalized_suffix.startswith(".") or not normalized_suffix[1:].isalnum():
        raise ValueError("Invalid video suffix")
    return f"video-preparation/{_safe_camera_id(camera_id)}/{_safe_session_id(job_id)}/original{normalized_suffix}"


def media_key(camera_id: str, session_id: str, *, preview: bool, suffix: str) -> str:
    normalized_suffix = suffix.lower()
    if not normalized_suffix.startswith(".") or not normalized_suffix[1:].isalnum():
        raise ValueError("Invalid video suffix")
    name = "preview.mp4" if preview else f"source{normalized_suffix}"
    return f"video-sessions/{_safe_camera_id(camera_id)}/{_safe_session_id(session_id)}/{name}"


def _put_json(key: str, payload: dict[str, Any]) -> None:
    get_evidence_storage().put_object(
        key,
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"),
        "application/json",
    )


def _get_json(key: str) -> dict[str, Any] | None:
    try:
        raw = get_evidence_storage().get_object(key)
    except EvidenceNotFoundError:
        return None
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Stored video state is not an object")
    return value


def store_uploaded_session(
    *,
    camera_id: str,
    session_id: str,
    source_path: Path,
    preview_path: Path | None,
    source_name: str,
    content_type: str,
) -> dict[str, Any]:
    """Persist one immutable upload and its non-secret metadata."""
    storage = get_evidence_storage()
    source_key = media_key(camera_id, session_id, preview=False, suffix=source_path.suffix)
    storage.put_file(source_key, str(source_path), content_type)
    preview_key = None
    if preview_path and preview_path.is_file():
        preview_key = media_key(camera_id, session_id, preview=True, suffix=".mp4")
        storage.put_file(preview_key, str(preview_path), "video/mp4")
    metadata = {
        "session_id": _safe_session_id(session_id),
        "camera_id": _safe_camera_id(camera_id),
        "source_mode": "durable",
        "source_name": source_name,
        "source_object_key": source_key,
        "preview_object_key": preview_key,
        "content_type": content_type or mimetypes.guess_type(source_name)[0] or "application/octet-stream",
    }
    _put_json(session_metadata_key(camera_id, session_id), metadata)
    return metadata


def get_uploaded_session(camera_id: str, session_id: str) -> dict[str, Any] | None:
    return _get_json(session_metadata_key(camera_id, session_id))


def create_preparation_job(
    *,
    camera_id: str,
    job_id: str,
    source_path: Path,
    source_name: str,
    content_type: str,
) -> dict[str, Any]:
    """Persist the received original and an authoritative recoverable job."""
    suffix = source_path.suffix.lower()
    raw_key = preparation_upload_key(camera_id, job_id, suffix)
    now = time.time()
    job = {
        "preparation_job_id": _safe_session_id(job_id),
        "upload_intent_id": _safe_session_id(job_id),
        "session_id": _safe_session_id(job_id),
        "camera_id": _safe_camera_id(camera_id),
        "source_name": source_name,
        "content_type": content_type,
        "source_suffix": suffix,
        "raw_object_key": raw_key,
        "state": "UPLOADING",
        "created_at": now,
        "updated_at": now,
        "error": None,
    }
    _put_json(preparation_job_key(camera_id, job_id), job)
    _put_json(preparation_control_key(camera_id), {
        "camera_id": _safe_camera_id(camera_id),
        "preparation_job_id": _safe_session_id(job_id),
        "upload_intent_id": _safe_session_id(job_id),
        "updated_at": now,
    })
    get_evidence_storage().put_file(raw_key, str(source_path), content_type)
    return update_preparation_job(camera_id, job_id, {"state": "UPLOADED"})


def get_preparation_job(camera_id: str, job_id: str) -> dict[str, Any] | None:
    return _get_json(preparation_job_key(camera_id, job_id))


def get_current_preparation_job(camera_id: str) -> dict[str, Any] | None:
    current = _get_json(preparation_control_key(camera_id))
    if not current or not current.get("preparation_job_id"):
        return None
    return get_preparation_job(camera_id, current["preparation_job_id"])


def update_preparation_job(camera_id: str, job_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    job = get_preparation_job(camera_id, job_id)
    if job is None:
        raise FileNotFoundError("Video preparation job was not found")
    job.update(changes)
    job["updated_at"] = time.time()
    _put_json(preparation_job_key(camera_id, job_id), job)
    return job


def preparation_is_current(camera_id: str, job_id: str) -> bool:
    current = _get_json(preparation_control_key(camera_id)) or {}
    return current.get("preparation_job_id") == _safe_session_id(job_id)


def retry_preparation_job(camera_id: str, job_id: str) -> dict[str, Any]:
    """Requeue the current failed job without changing its upload identity."""
    job = get_preparation_job(camera_id, job_id)
    if job is None:
        raise FileNotFoundError("Video preparation job was not found")
    if not preparation_is_current(camera_id, job_id):
        raise ValueError("Only the current video preparation job can be retried")
    if str(job.get("state", "")).upper() != "FAILED":
        raise ValueError("Only a failed video preparation job can be retried")
    raw_key = job.get("raw_object_key")
    if not raw_key or not get_evidence_storage().object_exists(raw_key):
        raise FileNotFoundError("The received upload is no longer available for retry")
    return update_preparation_job(camera_id, job_id, {
        "state": "UPLOADED",
        "error": None,
        "retry_count": int(job.get("retry_count") or 0) + 1,
    })


def download_preparation_upload(camera_id: str, job_id: str, destination: Path) -> dict[str, Any]:
    job = get_preparation_job(camera_id, job_id)
    if job is None or not job.get("raw_object_key"):
        raise FileNotFoundError("Video preparation upload was not found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    get_evidence_storage().get_file(job["raw_object_key"], str(destination))
    return job


def delete_preparation_upload(camera_id: str, job_id: str) -> None:
    job = get_preparation_job(camera_id, job_id)
    if job and job.get("raw_object_key"):
        get_evidence_storage().delete_object(job["raw_object_key"])


def activate_session(camera_id: str, session_id: str) -> dict[str, Any]:
    metadata = get_uploaded_session(camera_id, session_id)
    if metadata is None:
        raise FileNotFoundError("Video session was not found in durable storage")
    previous = _get_json(control_key(camera_id)) or {}
    source_generation = (
        int(previous.get("source_generation") or 1)
        if previous.get("session_id") == session_id
        else int(previous.get("source_generation") or 0) + 1
    )
    control = {
        **metadata,
        "upload_intent_id": session_id,
        "source_generation": source_generation,
        "source_mode": "durable",
        "scenario": "paused",
        "video_time": 0.0,
        "video_time_updated_at": 0.0,
        "analysis_state": "READY",
        "analysis_generation": 0,
        "state_updated_at": time.time(),
        "completion_time": None,
        "latest_analysis_session_id": None,
        "final_frame_index": None,
    }
    _put_json(control_key(camera_id), control)
    return control


def activate_bundled_source(
    camera_id: str,
    *,
    scenario: str,
    video_source: str,
    video_time: float = 0.0,
    video_time_updated_at: float = 0.0,
) -> dict[str, Any]:
    """Persist camera-scoped control for media bundled in the edge image.

    This record deliberately has no session ID or object key.  It is control
    plane state only; the bundled video is never uploaded to object storage.
    """
    control = {
        "camera_id": _safe_camera_id(camera_id),
        "source_mode": "bundled",
        "video_source": video_source,
        "video_session_id": None,
        "scenario": scenario,
        "video_time": float(video_time),
        "video_time_updated_at": float(video_time_updated_at),
    }
    _put_json(control_key(camera_id), control)
    return control


def get_active_session(camera_id: str) -> dict[str, Any] | None:
    return _get_json(control_key(camera_id))


def get_valid_active_session(camera_id: str) -> dict[str, Any] | None:
    """Return an active durable session only when all referenced objects exist.

    A control record can outlive its metadata or media object.  That stale
    record is not a durable source and must not prevent the camera from using
    its worker-bundled demo fallback.
    """
    current = get_active_session(camera_id)
    if not current:
        return None
    session_id = current.get("session_id")
    source_key = current.get("source_object_key")
    if not session_id or not source_key:
        return None
    metadata = get_uploaded_session(camera_id, session_id)
    if not metadata or metadata.get("source_object_key") != source_key:
        return None
    if not get_evidence_storage().object_exists(source_key):
        return None
    return current


def update_active_session(camera_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    current = get_active_session(camera_id)
    if current is None:
        return None
    current.update(changes)
    # An explicit operator STOP is a durable lifecycle transition, not just a
    # browser playback heartbeat.  Persist it so restore cannot resurrect a
    # stale WAKING state after a failed/cold worker run.
    if changes.get("scenario") in {"paused", "stopped"}:
        current.update({
            "analysis_state": "PAUSED",
            "state_updated_at": time.time(),
        })
    _put_json(control_key(camera_id), current)
    return current


def reconcile_inactive_control(camera_id: str, telemetry: dict[str, Any] | None = None, *, now: float | None = None) -> dict[str, Any] | None:
    """Repair only a stale paused durable lifecycle without waking a worker."""
    current = get_valid_active_session(camera_id)
    if current is None:
        return None
    lifecycle = str(current.get("analysis_state") or "READY").upper()
    scenario = str(current.get("scenario") or "paused").lower()
    if scenario not in {"paused", "stopped"} or lifecycle not in {"WAKING", "ACTIVE"}:
        return current
    observed = telemetry or {}
    timestamp = float(observed.get("processed_timestamp") or observed.get("timestamp") or 0)
    current_time = time.time() if now is None else now
    same_generation = int(observed.get("analysis_generation") or -1) == int(current.get("analysis_generation") or 0)
    same_source = observed.get("stream_id") == current.get("session_id")
    actively_processing = str(observed.get("analysis_state") or "").upper() == "PROCESSING"
    if same_generation and same_source and actively_processing and current_time - timestamp < 30:
        return current
    current.update({"analysis_state": "PAUSED", "state_updated_at": current_time})
    _put_json(control_key(camera_id), current)
    return current


def start_active_session(
    camera_id: str,
    session_id: str,
    *,
    request_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Atomically begin one durable analysis generation, or return its in-flight run."""
    current = get_valid_active_session(camera_id)
    if current is None or current.get("session_id") != session_id:
        raise FileNotFoundError("Video session is not the active durable source")
    # A deliberate reanalysis request may be retried after a lost response.
    # Persist its identity with the control record so the same click can never
    # advance the source to another generation, even after the first run ends.
    if request_id and current.get("last_start_request_id") == request_id:
        return current, False
    lifecycle = str(current.get("analysis_state") or "READY").upper()
    scenario = str(current.get("scenario") or "paused").lower()
    # An in-flight generation is idempotent only when its control fields agree.
    # A previous failed/cold worker can leave WAKING/ACTIVE beside a paused
    # scenario; normalize that same generation instead of creating a duplicate.
    if lifecycle in {"WAKING", "ACTIVE"}:
        if scenario == "normal":
            return {**current, "control_repaired": False}, False
        now = time.time()
        current.update({
            "scenario": "normal",
            "video_time": 0.0,
            "video_time_updated_at": now,
            "state_updated_at": now,
        })
        _put_json(control_key(camera_id), current)
        return {**current, "control_repaired": True}, False
    now = time.time()
    current.update({
        "scenario": "normal",
        "analysis_state": "WAKING",
        "analysis_generation": int(current.get("analysis_generation") or 0) + 1,
        "video_time": 0.0,
        "video_time_updated_at": now,
        "state_updated_at": now,
        "completion_time": None,
        "latest_analysis_session_id": None,
        "final_frame_index": None,
    })
    if request_id:
        current["last_start_request_id"] = request_id
    _put_json(control_key(camera_id), current)
    return {**current, "control_repaired": False}, True


def promote_active_session(
    camera_id: str,
    session_id: str,
    generation: int,
    analysis_session_id: str,
) -> dict[str, Any] | None:
    """Promote only a matching, real durable generation after first telemetry."""
    current = get_valid_active_session(camera_id)
    if (
        current is None
        or current.get("session_id") != session_id
        or int(current.get("analysis_generation") or 0) != int(generation)
        or current.get("scenario") != "normal"
        or current.get("analysis_state") != "WAKING"
    ):
        return None
    current.update({
        "analysis_state": "ACTIVE",
        "latest_analysis_session_id": analysis_session_id,
        "state_updated_at": time.time(),
    })
    _put_json(control_key(camera_id), current)
    return current


def complete_active_session(camera_id: str, session_id: str, generation: int, changes: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a successful finite-run terminal state without rewriting history."""
    current = get_valid_active_session(camera_id)
    if current is None or current.get("session_id") != session_id:
        return None
    if int(current.get("analysis_generation") or 0) != int(generation):
        return None
    if current.get("analysis_state") == "COMPLETED":
        return current
    current.update({
        "scenario": "paused",
        "analysis_state": "COMPLETED",
        "state_updated_at": time.time(),
        "completion_time": time.time(),
        **changes,
    })
    _put_json(control_key(camera_id), current)
    return current


def signed_media_url(object_key: str, expires_in: int = 900) -> str | None:
    return get_evidence_storage().generate_signed_url(object_key, expires_in=expires_in)
