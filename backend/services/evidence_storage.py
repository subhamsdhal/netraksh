"""
NETRAKSH — Evidence Storage Abstraction (Phase 4 WP-3.3)
Provides a provider-neutral interface for retrieving and storing evidence images,
decoupling the API from the local filesystem to support object storage (S3).

Boto3 is imported lazily inside S3Storage so that this module can be imported
on deployments that only use the local filesystem and have not installed boto3.
"""
import os
import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

_MISSING_CODES = {"NoSuchKey", "NotFound", "404"}
_SENSITIVE_ERROR_TEXT = re.compile(
    r"authorization|access.?key|secret|credential|token|signature|presign|https?://|x-amz",
    re.IGNORECASE,
)


def _s3_error_details(exc: Exception) -> tuple[int | None, str, str]:
    response = getattr(exc, "response", {}) or {}
    metadata = response.get("ResponseMetadata", {}) or {}
    status = metadata.get("HTTPStatusCode")
    error = response.get("Error", {}) or {}
    code = str(error.get("Code", ""))
    message = str(error.get("Message", ""))
    if not message or _SENSITIVE_ERROR_TEXT.search(message):
        message = "<redacted>" if message else ""
    return status, code, message


def _log_s3_failure(operation: str, exc: Exception) -> tuple[int | None, str]:
    status, code, message = _s3_error_details(exc)
    log = logger.debug if _is_missing_s3_error(status, code) else logger.warning
    log(
        "S3 %s failed status=%s code=%s message=%s",
        operation,
        status if status is not None else "unknown",
        code or "<blank>",
        message or "<blank>",
    )
    return status, code


def _is_missing_s3_error(status: int | None, code: str) -> bool:
    return status == 404 or code in _MISSING_CODES

class EvidenceNotFoundError(Exception):
    pass

class PathTraversalError(Exception):
    pass

class StorageUploadError(Exception):
    pass

import uuid

def validate_object_key_segment(segment: str, field_name: str = "segment", is_uuid: bool = False) -> str:
    """
    Validates a single path segment (e.g., camera_id, event_id) for use in an
    object storage key.

    Accepted format: [A-Za-z0-9_-]+  (letters, digits, underscore, hyphen)
    This deliberately excludes:
      - slashes / backslashes  (path separator injection)
      - periods (blocks ".." traversal and avoids collision between "cam.id"
        and "cam" + ".id")
      - NUL bytes, control characters (0x00–0x1F)
      - leading/trailing whitespace
      - empty strings

    Rejection over normalization: no unsafe input is silently accepted or
    transformed into a different accepted value. This prevents identifier
    collisions caused by lossy normalisation.

    If is_uuid=True the segment is strictly parsed and canonicalized to a
    lowercase hyphenated UUID string, which always satisfies the above rule.
    """
    if not segment:
        raise ValueError(f"Invalid {field_name}: cannot be empty.")

    if is_uuid:
        try:
            return str(uuid.UUID(str(segment)))
        except ValueError:
            raise ValueError(f"Invalid {field_name}: must be a valid UUID.")

    if not isinstance(segment, str):
        segment = str(segment)

    # --- control characters (0x00–0x1F) — checked FIRST before strip()
    #     because str.strip() also removes some control chars (e.g. \x1f).
    #     Checking here ensures cam\x1f raises "control characters" not
    #     "whitespace".
    for char in segment:
        if ord(char) < 32:
            raise ValueError(f"Invalid {field_name}: contains control characters.")

    # --- whitespace check (space 0x20) ---
    stripped = segment.strip()
    if stripped != segment:
        raise ValueError(f"Invalid {field_name}: contains unsafe leading or trailing whitespace.")

    # --- path traversal check BEFORE slash check so that "../cam" hits
    #     the traversal message rather than the generic "unsafe character" ---
    if segment == ".." or segment.startswith("../") or segment.startswith("..\\") \
            or "/.." in segment or "\\.." in segment or ".." in segment:
        raise ValueError(f"Invalid {field_name}: contains path traversal structure '..'.")

    # --- control characters (0x00–0x1F) including NUL ---
    for char in segment:
        if ord(char) < 32:
            raise ValueError(f"Invalid {field_name}: contains control characters.")

    # --- slash, backslash ---
    for char in ('/', '\\'):
        if char in segment:
            raise ValueError(f"Invalid {field_name}: contains unsafe character {repr(char)}.")

    # --- strict allow-list: [A-Za-z0-9_-] only ---
    # Periods, colons, spaces, braces, etc. are intentionally excluded.
    # Camera IDs and event IDs in NETRAKSH use only letters, digits,
    # underscores, and hyphens (confirmed by inventory of all fixtures,
    # demo seeds, and schema defaults).
    import re
    if not re.fullmatch(r'[A-Za-z0-9_\-]+', segment):
        raise ValueError(
            f"Invalid {field_name}: contains characters outside the allowed set "
            f"[A-Za-z0-9_-]."
        )

    return segment


class EvidenceStorageBackend(ABC):
    @abstractmethod
    def put_object(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Upload evidence bytes to storage."""
        pass

    @abstractmethod
    def get_object(self, object_key: str) -> bytes:
        """Read the evidence bytes for a given object key."""
        pass

    @abstractmethod
    def head_object(self, object_key: str) -> dict:
        """Get object metadata. Raises EvidenceNotFoundError if it doesn't exist."""
        pass

    @abstractmethod
    def object_exists(self, object_key: str) -> bool:
        """Check if an object exists."""
        pass

    @abstractmethod
    def delete_object(self, object_key: str) -> None:
        """Delete an object."""
        pass

    @abstractmethod
    def generate_signed_url(self, object_key: str, expires_in: int = 3600) -> Optional[str]:
        """Generate a time-limited signed URL for direct client access, if supported."""
        pass

    def read_evidence_bytes(self, ref: str) -> bytes:
        """Backward compatibility alias for get_object."""
        return self.get_object(ref)

    def put_file(self, object_key: str, file_path: str, content_type: str = "application/octet-stream") -> None:
        """Upload a file without requiring callers to retain its bytes."""
        with open(file_path, "rb") as source:
            self.put_object(object_key, source.read(), content_type)


class LocalFilesystemStorage(EvidenceStorageBackend):
    def __init__(self, clips_dir: str):
        self.clips_dir = os.path.abspath(clips_dir)
        os.makedirs(self.clips_dir, exist_ok=True)

    def _get_safe_path(self, object_key: str) -> str:
        """
        Returns a safe absolute path within clips_dir.

        For new WP-3.3 keys ("evidence/cam-1/20240101/event-id.jpg.enc") the
        full subdirectory structure is preserved under clips_dir, giving:
            clips_dir/evidence/cam-1/20240101/event-id.jpg.enc

        For legacy bare filenames ("frame_abc.jpg.enc" with no slashes) the
        file lands directly in clips_dir, preserving old behaviour.

        In all cases the resolved path must remain inside clips_dir — any
        attempt to escape (../ etc.) raises PathTraversalError.
        """
        if not object_key:
            raise PathTraversalError("Empty evidence reference.")

        # Normalise OS separators, then reject any remaining ..
        normalised = os.path.normpath(object_key.replace("\\", "/"))
        if normalised.startswith("..") or os.sep + ".." in normalised:
            raise PathTraversalError("Path traversal detected in evidence reference.")

        safe_path = os.path.abspath(os.path.join(self.clips_dir, normalised))

        # Final containment check — must be inside (or equal to) clips_dir.
        if not safe_path.startswith(self.clips_dir + os.sep) and safe_path != self.clips_dir:
            raise PathTraversalError("Evidence path escapes the configured root directory.")

        return safe_path

    def put_object(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        safe_path = self._get_safe_path(object_key)
        # Ensure intermediate subdirectories exist (e.g. evidence/cam/date/)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        try:
            with open(safe_path, "wb") as f:
                f.write(data)
        except Exception as e:
            raise StorageUploadError(f"Failed to write local object: {str(e)}")

    def put_file(self, object_key: str, file_path: str, content_type: str = "application/octet-stream") -> None:
        import shutil

        safe_path = self._get_safe_path(object_key)
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        try:
            shutil.copyfile(file_path, safe_path)
        except Exception as e:
            raise StorageUploadError(f"Failed to copy local object: {str(e)}")

    def get_object(self, object_key: str) -> bytes:
        safe_path = self._get_safe_path(object_key)
        if not os.path.exists(safe_path):
            raise EvidenceNotFoundError(f"Evidence file {object_key} not found.")
        with open(safe_path, "rb") as f:
            return f.read()

    def head_object(self, object_key: str) -> dict:
        safe_path = self._get_safe_path(object_key)
        if not os.path.exists(safe_path):
            raise EvidenceNotFoundError(f"Evidence file {object_key} not found.")
        return {
            "ContentLength": os.path.getsize(safe_path)
        }

    def object_exists(self, object_key: str) -> bool:
        safe_path = self._get_safe_path(object_key)
        return os.path.exists(safe_path)

    def delete_object(self, object_key: str) -> None:
        safe_path = self._get_safe_path(object_key)
        if os.path.exists(safe_path):
            os.remove(safe_path)

    def generate_signed_url(self, object_key: str, expires_in: int = 3600) -> Optional[str]:
        # Local filesystem cannot generate HTTP signed URLs
        return None


class S3Storage(EvidenceStorageBackend):
    def __init__(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str):
        try:
            import boto3
            from botocore.config import Config
            from botocore.exceptions import ClientError as _ClientError
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 storage. "
                "Install it with: pip install boto3==1.34.0"
            )
        self._ClientError = _ClientError
        self.bucket = bucket
        self.s3 = boto3.client(
            's3',
            endpoint_url=endpoint or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "us-east-1",
            # Supabase's S3 endpoint requires AWS Signature Version 4 for
            # presigned URLs as well as normal client requests.  Pinning the
            # signing version prevents botocore from selecting legacy query
            # signing for a custom endpoint in us-east-1.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ) if endpoint else None,
        )

    def put_object(self, object_key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        try:
            self.s3.put_object(
                Bucket=self.bucket,
                Key=object_key,
                Body=data,
                ContentType=content_type
            )
        except self._ClientError as e:
            raise StorageUploadError(f"Failed to upload to S3: {str(e)}")

    def put_file(self, object_key: str, file_path: str, content_type: str = "application/octet-stream") -> None:
        try:
            self.s3.upload_file(
                file_path,
                self.bucket,
                object_key,
                ExtraArgs={"ContentType": content_type},
            )
        except self._ClientError as e:
            raise StorageUploadError(f"Failed to upload file to S3: {str(e)}")

    def get_object(self, object_key: str) -> bytes:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=object_key)
            return response['Body'].read()
        except self._ClientError as e:
            status, code = _log_s3_failure("get_object", e)
            if _is_missing_s3_error(status, code):
                raise EvidenceNotFoundError(f"S3 Object {object_key} not found.")
            raise

    def head_object(self, object_key: str) -> dict:
        try:
            return self.s3.head_object(Bucket=self.bucket, Key=object_key)
        except self._ClientError as e:
            status, code = _log_s3_failure("head_object", e)
            if _is_missing_s3_error(status, code):
                raise EvidenceNotFoundError(f"S3 Object {object_key} not found.")
            raise

    def object_exists(self, object_key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=object_key)
            return True
        except self._ClientError as e:
            status, code = _log_s3_failure("object_exists", e)
            if _is_missing_s3_error(status, code):
                return False
            raise

    def delete_object(self, object_key: str) -> None:
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=object_key)
        except self._ClientError:
            pass

    def generate_signed_url(self, object_key: str, expires_in: int = 3600) -> Optional[str]:
        try:
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket, 'Key': object_key},
                ExpiresIn=expires_in
            )
            return url
        except self._ClientError:
            return None


def get_evidence_storage() -> EvidenceStorageBackend:
    from backend.config import settings
    provider = settings.OBJECT_STORAGE_PROVIDER or settings.EVIDENCE_STORAGE_BACKEND
    if provider == "s3":
        return S3Storage(
            endpoint=settings.OBJECT_STORAGE_ENDPOINT,
            bucket=settings.OBJECT_STORAGE_BUCKET,
            access_key=settings.OBJECT_STORAGE_ACCESS_KEY,
            secret_key=settings.OBJECT_STORAGE_SECRET_KEY,
            region=settings.OBJECT_STORAGE_REGION or "us-east-1"
        )
    return LocalFilesystemStorage(settings.EVIDENCE_CLIPS_DIR)
