"""
Phase 3C permanent regression tests for object key segment validation
and local-storage containment.

These tests prove:
  1. Valid identifiers are accepted without modification.
  2. Every class of hostile input is rejected with a ValueError (never
     silently normalised to an accepted key).
  3. No hostile input can produce the same accepted key as a different
     hostile input (no collision via lossy normalisation).
  4. The LocalFilesystemStorage backend confines all writes inside the
     configured evidence root — hostile keys cannot escape via ../

Allowlist decision (documented):
  Accepted:  [A-Za-z0-9_-]+
  Rejected:  everything else — including periods (prevents '..'), slashes,
             backslashes, NUL bytes, control chars, whitespace, empty strings.
  Camera IDs in production: cam-border-01, cam-checkpoint-01, cam_A, cam1
  Event IDs:  UUID strings (canonicalized through uuid.UUID)
  → No existing ID requires a period; no expansion is needed.
"""
import os
import re
import tempfile
import uuid

import pytest

from backend.services.evidence_storage import (
    LocalFilesystemStorage,
    PathTraversalError,
    validate_object_key_segment,
)


# ---------------------------------------------------------------------------
# Valid inputs
# ---------------------------------------------------------------------------

def test_validate_object_key_segment_valid():
    assert validate_object_key_segment("cam-1", "camera_id") == "cam-1"
    assert validate_object_key_segment("camera_test_123", "camera_id") == "camera_test_123"
    assert validate_object_key_segment("cam-border-01", "camera_id") == "cam-border-01"
    assert validate_object_key_segment("cam-checkpoint-01", "camera_id") == "cam-checkpoint-01"
    assert validate_object_key_segment("cam_A", "camera_id") == "cam_A"


def test_validate_object_key_segment_uuid():
    valid_uuid = str(uuid.uuid4())
    # UUID strings are accepted and canonicalised to lowercase.
    assert validate_object_key_segment(valid_uuid.upper(), "event_id", is_uuid=True) == valid_uuid.lower()


def test_validate_object_key_segment_uuid_invalid():
    with pytest.raises(ValueError, match="must be a valid UUID"):
        validate_object_key_segment("not-a-uuid", "event_id", is_uuid=True)


# ---------------------------------------------------------------------------
# Invalid inputs — each must be rejected, never silently normalised
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("invalid_input, expected_fragment", [
    # Empty / None
    ("",      "cannot be empty"),
    (None,    "cannot be empty"),
    # Whitespace
    (" cam-1",  "unsafe leading or trailing whitespace"),
    ("cam-1 ",  "unsafe leading or trailing whitespace"),
    ("cam 1",   "outside the allowed set"),  # internal space: strip() passes, caught by allow-list
    # Path traversal — must be caught BEFORE the generic slash check
    ("..",       "path traversal"),
    ("../cam",   "path traversal"),          # slash present, but .. checked first
    ("cam/..",   "path traversal"),
    ("cam/../x", "path traversal"),
    ("cam..",    "path traversal"),
    # Control characters — NUL is a control char (ord 0)
    ("cam\x00",  "control characters"),
    ("cam\x01",  "control characters"),
    ("cam\x1f",  "control characters"),
    # Slash / backslash (after .. check)
    ("cam/1",    "unsafe character"),
    ("cam\\1",   "unsafe character"),
    # Characters outside the strict allow-list
    ("cam.1",    "outside the allowed set"),  # period not allowed
    ("cam:1",    "outside the allowed set"),
    ("{cam}",    "outside the allowed set"),
])
def test_validate_object_key_segment_invalid(invalid_input, expected_fragment):
    """Every hostile input must raise ValueError. The message must mention the expected issue."""
    with pytest.raises(ValueError, match=re.escape(expected_fragment)):
        validate_object_key_segment(invalid_input, "test")


# ---------------------------------------------------------------------------
# Collision resistance — hostile inputs must not collapse to the same key
# ---------------------------------------------------------------------------

def test_no_normalization_collision():
    """
    Different hostile inputs must ALL be rejected rather than normalised
    to some shared accepted value.  If any of these raised NO exception
    it would mean two logically distinct inputs map to the same object key.
    """
    hostile = [
        "cam/1",
        "cam\\1",
        "cam..1",
        "../cam",
        "cam/../x",
        "cam\x00",
    ]
    for h in hostile:
        with pytest.raises(ValueError):
            validate_object_key_segment(h)


# ---------------------------------------------------------------------------
# Local storage containment — hostile object_key cannot escape tmpdir
# ---------------------------------------------------------------------------

def test_local_storage_containment():
    """
    Prove that LocalFilesystemStorage._get_safe_path never resolves outside
    the configured clips_dir regardless of the object_key value.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalFilesystemStorage(clips_dir=tmpdir)

        hostile_keys = [
            "../outside.txt",
            "../../etc/passwd",
            "evidence/../../etc/passwd",
            "evidence/../../../autoexec.bat",
            os.path.join("..", "outside.txt"),
        ]

        for key in hostile_keys:
            with pytest.raises(PathTraversalError):
                storage._get_safe_path(key)

        # Also verify put_object raises for hostile keys (belt-and-suspenders)
        for key in hostile_keys:
            with pytest.raises((PathTraversalError, OSError)):
                storage.put_object(key, b"evil")


def test_local_storage_valid_key_stays_inside():
    """A well-formed key must land inside clips_dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalFilesystemStorage(clips_dir=tmpdir)
        data = b"\xff\xd8\xff valid-evidence"
        key = "evidence/cam-1/20240101/evt-abc-123.jpg"
        storage.put_object(key, data)
        expected_path = os.path.join(tmpdir, "evidence", "cam-1", "20240101", "evt-abc-123.jpg")
        assert os.path.isfile(expected_path)
        assert os.path.abspath(expected_path).startswith(os.path.abspath(tmpdir))


def test_local_storage_sha256_integrity():
    """
    Prove SHA-256 content integrity:
      - Original evidence bytes are SHA-256 hashed locally before upload.
      - Retrieved evidence bytes are independently SHA-256 hashed after download.
      - The two digests match.
    S3 ETags are NOT used and are not SHA-256.
    """
    import hashlib

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalFilesystemStorage(clips_dir=tmpdir)
        original = b"\xff\xd8\xff test-evidence-payload"
        key = "evidence/cam-test/20240101/evt-integrity.jpg"

        original_digest = hashlib.sha256(original).hexdigest()
        storage.put_object(key, original)

        retrieved = storage.get_object(key)
        retrieved_digest = hashlib.sha256(retrieved).hexdigest()

        assert original_digest == retrieved_digest, (
            f"Digest mismatch: original={original_digest}, retrieved={retrieved_digest}"
        )
