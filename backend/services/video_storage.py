"""Durable object-storage state for dashboard video sessions.

The browser never receives object-store credentials.  The backend writes
immutable video objects and small JSON control records; authenticated edge
workers receive a short-lived download URL for the selected object.
"""
from __future__ import annotations

import json
import mimetypes
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
        "source_name": source_name,
        "source_object_key": source_key,
        "preview_object_key": preview_key,
        "content_type": content_type or mimetypes.guess_type(source_name)[0] or "application/octet-stream",
    }
    _put_json(session_metadata_key(camera_id, session_id), metadata)
    return metadata


def get_uploaded_session(camera_id: str, session_id: str) -> dict[str, Any] | None:
    return _get_json(session_metadata_key(camera_id, session_id))


def activate_session(camera_id: str, session_id: str) -> dict[str, Any]:
    metadata = get_uploaded_session(camera_id, session_id)
    if metadata is None:
        raise FileNotFoundError("Video session was not found in durable storage")
    control = {
        **metadata,
        "scenario": "paused",
        "video_time": 0.0,
        "video_time_updated_at": 0.0,
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
    _put_json(control_key(camera_id), current)
    return current


def signed_media_url(object_key: str, expires_in: int = 900) -> str | None:
    return get_evidence_storage().generate_signed_url(object_key, expires_in=expires_in)
