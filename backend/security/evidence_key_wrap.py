"""
NETRAKSH Backend — Evidence Key Wrapping (architecture v4 §10).

Each camera's raw AES-256 evidence-encryption key (generated on the edge
device by edge/evidence/packager.py::EvidenceEncryptor) is wrapped with a
server-derived key-encryption-key (KEK) before being stored in the database
(Camera.evidence_key_wrapped, backend/models/orm.py) — the raw key is never
persisted, only the wrapped form.

The KEK is derived via HKDF from settings.SECRET_KEY with a domain-
separation label, deliberately NOT settings.SECRET_KEY used directly:
reusing one secret across two different cryptographic purposes (JWT
signing there, key-wrapping here) is a real anti-pattern this avoids.
HKDF is designed for exactly this — deriving multiple independent-looking
keys from one master secret for different purposes.

Real limitation, recorded honestly (see docs/LIMITATIONS.md): the KEK is
derived from an application secret, not held in a dedicated secrets
manager or HSM. Anyone with settings.SECRET_KEY (already a sensitive value
protecting JWTs) can derive the KEK and unwrap every camera's evidence key.
This is a proportionate MVP tradeoff, not a claim of production-grade key
management.
"""
from __future__ import annotations

import base64
import logging

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.config import settings
from shared.crypto import aes_gcm_decrypt, aes_gcm_encrypt

logger = logging.getLogger(__name__)

_HKDF_INFO = b"netraksh-evidence-key-wrap-v1"


def _derive_wrap_key() -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_HKDF_INFO)
    return hkdf.derive(settings.SECRET_KEY.encode("utf-8"))


def wrap_key(raw_key: bytes) -> str:
    """Wraps a raw 32-byte evidence key for storage. Returns a base64 string."""
    wrapped = aes_gcm_encrypt(_derive_wrap_key(), raw_key)
    return base64.b64encode(wrapped).decode("ascii")


def unwrap_key(wrapped_b64: str) -> bytes:
    """Inverse of wrap_key(). Raises cryptography.exceptions.InvalidTag if the
    stored value was tampered with, or ValueError/binascii.Error if it isn't
    valid base64 (e.g. a Camera row with a corrupted/malformed field)."""
    wrapped = base64.b64decode(wrapped_b64)
    return aes_gcm_decrypt(_derive_wrap_key(), wrapped)
