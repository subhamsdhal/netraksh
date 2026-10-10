"""Bounded, owner-authorized database export used only for a fresh backup.

Disabled by default.  The endpoint is hidden from the API schema and requires
an ADMIN JWT.  Its single-use guard and explicit expiry bound the temporary
maintenance window; plaintext dump bytes are held in memory only and only an
RSA-wrapped AES-GCM archive is returned.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.engine import URL, make_url

from backend.config import settings
from backend.security.auth import require_admin
from shared.crypto import aes_gcm_encrypt

router = APIRouter(prefix="/api/admin", tags=["admin"])
_ARCHIVE_MAGIC = b"NETRAKSH-PG-BACKUP\x01"
_OAEP_LABEL = b"NETRAKSH-PG-BACKUP-v1"
_EXPORT_LOCK = threading.Lock()
_EXPORT_CONSUMED = False


def _dump_database() -> bytes:
    """Run pg_dump without placing a plaintext dump on disk or in logs."""
    try:
        url: URL = make_url(settings.DATABASE_URL)
        child_env = {
            "PATH": os.environ.get("PATH", ""),
            "PGHOST": url.host or "",
            "PGPORT": str(url.port or 5432),
            "PGDATABASE": url.database or "",
            "PGUSER": url.username or "",
            "PGPASSWORD": url.password or "",
            "PGSSLMODE": str(url.query.get("sslmode", "require")),
        }
        result = subprocess.run(
            ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--compress=6"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=child_env,
            timeout=240,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise HTTPException(status_code=503, detail="One-time backup could not be created.") from None
    max_bytes = min(max(settings.DB_BACKUP_EXPORT_MAX_BYTES, 1), 134217728)
    if result.returncode != 0 or not result.stdout:
        raise HTTPException(status_code=503, detail="One-time backup could not be created.")
    if len(result.stdout) > max_bytes:
        raise HTTPException(status_code=413, detail="Backup exceeds the configured size limit.")
    return result.stdout


def _encrypt_archive(plaintext: bytes, public_key_pem: str) -> bytes:
    public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 2048:
        raise ValueError("Recipient key must be RSA 2048-bit or stronger")
    data_key = os.urandom(32)
    wrapped_key = public_key.encrypt(
        data_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=_OAEP_LABEL,
        ),
    )
    ciphertext = aes_gcm_encrypt(data_key, plaintext)
    return _ARCHIVE_MAGIC + len(wrapped_key).to_bytes(2, "big") + wrapped_key + ciphertext


@router.get("/database-backup", include_in_schema=False)
def export_database_backup(_admin=Depends(require_admin)) -> Response:
    """Export one encrypted database archive during an explicit short window."""
    global _EXPORT_CONSUMED
    if (
        not settings.DB_BACKUP_EXPORT_ENABLED
        or not settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY
        or settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH <= int(time.time())
    ):
        raise HTTPException(status_code=404, detail="Not found")

    with _EXPORT_LOCK:
        if _EXPORT_CONSUMED:
            raise HTTPException(status_code=410, detail="One-time backup already consumed.")
        # Consume before starting pg_dump so errors cannot trigger an automatic retry.
        _EXPORT_CONSUMED = True
        try:
            plaintext = _dump_database()
            encrypted = _encrypt_archive(plaintext, settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=503, detail="One-time backup could not be created.") from None
        finally:
            if "plaintext" in locals():
                del plaintext

    digest = hashlib.sha256(encrypted).hexdigest()
    return Response(
        content=encrypted,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store, private",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Backup-SHA256": digest,
            "Content-Disposition": 'attachment; filename="netraksh-stage-encrypted.backup"',
        },
    )
