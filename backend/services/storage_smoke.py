"""Opt-in, one-shot verification for the configured S3-compatible storage."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

import httpx

from backend.config import settings
from backend.services.evidence_storage import EvidenceStorageBackend, get_evidence_storage

logger = logging.getLogger(__name__)

_PAYLOAD = b"netraksh-storage-smoke-v1"


def run_startup_storage_smoke_test(
    storage: EvidenceStorageBackend | None = None,
    fetch: Callable[[str], object] | None = None,
) -> bool:
    """Exercise upload, signed download, and cleanup without emitting sensitive URLs.

    This diagnostic is intentionally callable only by the explicit startup flag.
    Its randomly named, tiny object is deleted even if an intermediate operation
    fails. Exceptions are converted into safe operational log lines so a failed
    diagnostic does not hide the backend's normal health information.
    """
    if settings.OBJECT_STORAGE_PROVIDER != "s3":
        logger.warning("Storage smoke test skipped: provider is not s3")
        return False

    storage = storage or get_evidence_storage()
    fetch = fetch or (lambda url: httpx.get(url, timeout=10.0))
    object_key = f"diagnostics/storage-smoke/{uuid.uuid4().hex}"
    success = False

    try:
        storage.put_object(object_key, _PAYLOAD, content_type="application/octet-stream")
        logger.info("Storage smoke test upload=PASS")

        metadata = storage.head_object(object_key)
        if metadata.get("ContentLength") != len(_PAYLOAD):
            raise RuntimeError("temporary object length mismatch")
        logger.info("Storage smoke test head=PASS")
        if storage.get_object(object_key) != _PAYLOAD:
            raise RuntimeError("temporary object readback mismatch")
        logger.info("Storage smoke test get=PASS")

        signed_url = storage.generate_signed_url(object_key, expires_in=60)
        if not signed_url:
            raise RuntimeError("signed URL generation returned no URL")
        response = fetch(signed_url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            # The status is operationally useful and contains no credential
            # material.  Do not log the exception because it may embed the
            # pre-signed URL.
            logger.error("Storage smoke test signed_download=FAIL status=%s", response.status_code)
            raise
        if response.content != _PAYLOAD:
            raise RuntimeError("signed download content mismatch")
        logger.info("Storage smoke test signed_download=PASS status=%s", response.status_code)
        success = True
    except Exception as exc:
        # Do not include exception text: HTTP clients and S3 SDKs may embed a
        # pre-signed URL or credential-derived details in it.
        logger.error("Storage smoke test=FAIL operation=%s", type(exc).__name__)
    finally:
        try:
            storage.delete_object(object_key)
            logger.info("Storage smoke test delete=PASS")
            if storage.object_exists(object_key):
                raise RuntimeError("temporary object remains after cleanup")
            logger.info("Storage smoke test absent_after_delete=PASS")
        except Exception as exc:
            logger.error("Storage smoke test cleanup=FAIL operation=%s", type(exc).__name__)
            success = False
        if not success:
            logger.error("Storage smoke test completed with failure")
    return success
