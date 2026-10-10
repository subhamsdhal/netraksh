"""Small, camera-scoped PostgreSQL video objects for the two approved clips."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterator

from sqlalchemy import func, select, text

from backend.database.session import SessionLocal
from backend.models.orm import Camera, VideoControlRecord, VideoMediaObject
from backend.services.evidence_storage import EvidenceNotFoundError


CAMERAS = frozenset({"cam-border-01", "cam-checkpoint-01"})
APPROVED_ORIGINAL_SHA256 = {
    "cam-border-01": "de49c9ec97d7d1e66535d479e6da8901a0917afedc2f4d1e501cb9bba96a3357",
    "cam-checkpoint-01": "99f9a045d8eaa331e618b44a252e982819a25c9d9f6f748f9f60de5f9b863a6c",
}
MAX_OBJECT_BYTES = 49_000_000
MAX_TOTAL_BYTES = 200_000_000
READ_CHUNK_BYTES = 512 * 1024


def _identity(key: str) -> tuple[str, str]:
    parts = key.split("/")
    if len(parts) != 4 or parts[0] not in {"video-preparation", "video-sessions"}:
        raise ValueError("Invalid PostgreSQL video object key")
    camera_id, session_id = parts[1:3]
    if camera_id not in CAMERAS:
        raise ValueError("Camera is outside the approved PostgreSQL media scope")
    try:
        from uuid import UUID
        session_id = str(UUID(session_id))
    except ValueError as exc:
        raise ValueError("Invalid video session ID") from exc
    if parts[3] not in {"original.mp4", "source.mp4", "preview.mp4"}:
        raise ValueError("Only MP4 camera media may be stored in PostgreSQL")
    return camera_id, session_id


def _control_key(key: str) -> None:
    if not key.endswith(".json") or not key.startswith(("video-preparation/", "video-sessions/", "video-control/")):
        raise ValueError("Invalid video control key")
    parts = key.split("/")
    camera_id = parts[1].removesuffix(".json") if len(parts) > 1 else ""
    if camera_id not in CAMERAS:
        raise ValueError("Video control camera is not approved")


class PostgresVideoStorage:
    def put_object(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        if object_key.endswith(".json"):
            _control_key(object_key)
            payload = json.loads(data)
            if not isinstance(payload, dict):
                raise ValueError("Video control payload must be an object")
            with SessionLocal.begin() as db:
                record = db.get(VideoControlRecord, object_key)
                if record is None:
                    db.add(VideoControlRecord(object_key=object_key, payload=payload))
                else:
                    record.payload = payload
                    record.updated_at = func.now()
            return
        camera_id, session_id = _identity(object_key)
        if content_type != "video/mp4" or not 0 < len(data) <= MAX_OBJECT_BYTES:
            raise ValueError("PostgreSQL video requires a nonempty MP4 below 49 MB")
        if b"ftyp" not in data[:16]:
            raise ValueError("Video lacks an MP4 signature")
        digest = hashlib.sha256(data).hexdigest()
        if object_key.endswith("/original.mp4") and digest != APPROVED_ORIGINAL_SHA256[camera_id]:
            raise ValueError("Uploaded original does not match the approved camera source checksum")
        with SessionLocal.begin() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(72419011)"))
            camera = db.get(Camera, camera_id, with_for_update=True)
            if not camera:
                raise ValueError("Camera is not registered")
            existing = db.get(VideoMediaObject, object_key)
            if existing is not None:
                if existing.sha256 != digest or existing.byte_size != len(data):
                    raise ValueError("Video object already exists with different bytes")
                return
            used = db.scalar(select(func.coalesce(func.sum(VideoMediaObject.byte_size), 0))) or 0
            if used + len(data) > MAX_TOTAL_BYTES:
                raise ValueError("Approved PostgreSQL video quota exceeded")
            db.add(VideoMediaObject(
                object_key=object_key, camera_id=camera_id, session_id=session_id,
                original_filename="original.mp4" if "/original.mp4" in object_key else "source.mp4",
                content_type=content_type, byte_size=len(data), sha256=digest,
                ready=True, data=data,
            ))

    def put_file(self, object_key: str, file_path: str, content_type: str = "application/octet-stream") -> None:
        path = Path(file_path)
        if not 0 < path.stat().st_size <= MAX_OBJECT_BYTES:
            raise ValueError("Video exceeds the PostgreSQL media object limit")
        self.put_object(object_key, path.read_bytes(), content_type)

    def get_object(self, object_key: str) -> bytes:
        if object_key.endswith(".json"):
            _control_key(object_key)
            with SessionLocal() as db:
                record = db.get(VideoControlRecord, object_key)
                if record is None:
                    raise EvidenceNotFoundError("Video control record not found")
                return json.dumps(record.payload).encode("utf-8")
        _identity(object_key)
        with SessionLocal() as db:
            record = db.get(VideoMediaObject, object_key)
            if record is None or not record.ready:
                raise EvidenceNotFoundError("Video media not found")
            return record.data

    def get_file(self, object_key: str, file_path: str) -> None:
        with open(file_path, "wb") as destination:
            for chunk in iter_media_chunks(object_key):
                destination.write(chunk)

    def object_exists(self, object_key: str) -> bool:
        try:
            if object_key.endswith(".json"):
                _control_key(object_key)
                with SessionLocal() as db:
                    return db.get(VideoControlRecord, object_key) is not None
            _identity(object_key)
            with SessionLocal() as db:
                return bool(db.scalar(select(VideoMediaObject.ready).where(VideoMediaObject.object_key == object_key)))
        except ValueError:
            return False

    def delete_object(self, object_key: str) -> None:
        # Original bytes are retained for audit and exact-source recovery.
        _identity(object_key)
        if not object_key.endswith("/original.mp4"):
            raise ValueError("Only preparation originals may be retired")

    def generate_signed_url(self, object_key: str, expires_in: int = 900) -> None:
        # Browser and worker use their own authenticated backend routes.
        return None


def media_info(object_key: str) -> dict | None:
    _identity(object_key)
    with SessionLocal() as db:
        row = db.execute(select(
            VideoMediaObject.camera_id, VideoMediaObject.session_id,
            VideoMediaObject.byte_size, VideoMediaObject.sha256,
            VideoMediaObject.content_type, VideoMediaObject.ready,
        ).where(VideoMediaObject.object_key == object_key)).first()
        if row is None:
            return None
        return dict(row._mapping)


def record_prepared_metadata(
    camera_id: str, session_id: str, *, original_filename: str,
    duration_seconds: float | None, fps: float | None, source_generation: int,
) -> None:
    source_key = f"video-sessions/{camera_id}/{session_id}/source.mp4"
    original_key = f"video-preparation/{camera_id}/{session_id}/original.mp4"
    with SessionLocal.begin() as db:
        source = db.get(VideoMediaObject, source_key)
        original = db.get(VideoMediaObject, original_key)
        if source is None or original is None:
            raise EvidenceNotFoundError("Original and prepared camera media must both be stored")
        source.original_filename = original_filename
        source.duration_seconds = duration_seconds
        source.fps = fps
        source.source_generation = source_generation
        original.original_filename = original_filename
        original.duration_seconds = duration_seconds
        original.fps = fps
        original.source_generation = source_generation
        original.prepared_source_key = source_key


def read_media_range(object_key: str, start: int, length: int) -> bytes:
    _identity(object_key)
    if start < 0 or not 0 < length <= READ_CHUNK_BYTES:
        raise ValueError("Media read is outside the bounded range")
    with SessionLocal() as db:
        # PostgreSQL substring is 1-based and extracts only the requested BYTEA span.
        result = db.execute(text(
            "SELECT substring(data from :offset for :length) FROM video_media_objects "
            "WHERE object_key=:key AND ready=true"
        ), {"offset": start + 1, "length": length, "key": object_key}).scalar_one_or_none()
        if result is None:
            raise EvidenceNotFoundError("Video media not found")
        return bytes(result)


def iter_media_chunks(object_key: str, start: int = 0, end: int | None = None) -> Iterator[bytes]:
    info = media_info(object_key)
    if not info or not info["ready"]:
        raise EvidenceNotFoundError("Video media not found")
    stop = info["byte_size"] if end is None else min(end + 1, info["byte_size"])
    while start < stop:
        chunk = read_media_range(object_key, start, min(READ_CHUNK_BYTES, stop - start))
        if not chunk:
            raise IOError("Stored video ended before its verified byte size")
        yield chunk
        start += len(chunk)
