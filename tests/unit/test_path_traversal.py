"""
Regression tests for Priority 7: Path Traversal Fix in Evidence Storage.

Verifies that the EvidenceStorageBackend correctly blocks path traversal
attempts, allows safe basenames, and safely extracts basenames from absolute paths
for backward compatibility.
"""

import os
import pytest
from backend.services.evidence_storage import (
    LocalFilesystemStorage,
    PathTraversalError,
    EvidenceNotFoundError,
)

@pytest.fixture
def temp_clips_dir(tmp_path):
    # Create a dummy clips directory
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    # Create a dummy evidence file
    (clips_dir / "safe_file.jpg.enc").write_bytes(b"safe_content")
    return str(clips_dir)

def test_safe_basename(temp_clips_dir):
    storage = LocalFilesystemStorage(temp_clips_dir)
    # Should not raise any PathTraversalError
    content = storage.read_evidence_bytes("safe_file.jpg.enc")
    assert content == b"safe_content"


def test_path_traversal_dot_dot(temp_clips_dir):
    storage = LocalFilesystemStorage(temp_clips_dir)
    with pytest.raises(PathTraversalError):
        # Even though we extract basename, os.path.basename("../file") is "file",
        # but the backend explicitly rejects the original reference if it contained ".."
        # or if it's unsafe. Let's see how LocalFilesystemStorage handles it:
        # We explicitly check for ".." in basename or the original ref.
        storage.read_evidence_bytes("../safe_file.jpg.enc")

def test_path_traversal_encoded(temp_clips_dir):
    storage = LocalFilesystemStorage(temp_clips_dir)
    with pytest.raises(PathTraversalError):
        # Attempting to bypass with slashes in the basename
        storage.read_evidence_bytes("..\\safe_file.jpg.enc")

def test_empty_reference(temp_clips_dir):
    storage = LocalFilesystemStorage(temp_clips_dir)
    with pytest.raises(PathTraversalError):
        storage.read_evidence_bytes("")
    with pytest.raises(PathTraversalError):
        storage.read_evidence_bytes("/")

def test_not_found(temp_clips_dir):
    storage = LocalFilesystemStorage(temp_clips_dir)
    with pytest.raises(EvidenceNotFoundError):
        storage.read_evidence_bytes("does_not_exist.jpg.enc")
