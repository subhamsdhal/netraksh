"""
NETRAKSH Shared — AES-256-GCM primitives.

Factored out so both sides of the evidence-encryption story share ONE
implementation instead of two copies that could silently drift apart:
  - edge/evidence/packager.py::EvidenceEncryptor encrypts evidence at rest
    on the edge device.
  - backend/security/evidence_key_wrap.py wraps/unwraps each camera's raw
    key for storage, and backend/api/events.py decrypts evidence for an
    authorized dashboard viewer (architecture v4 §10).

GCM is authenticated encryption: decrypt() raises if the ciphertext was
tampered with, so no separate MAC/HMAC construction is needed on top of it.
"""
from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12  # 96-bit nonce, the size AES-GCM is designed for


def aes_gcm_encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Returns nonce || ciphertext+tag, ready to store or transmit as-is."""
    nonce = os.urandom(NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    return nonce + ciphertext


def aes_gcm_decrypt(key: bytes, blob: bytes) -> bytes:
    """Inverse of aes_gcm_encrypt(). Raises cryptography.exceptions.InvalidTag
    if the blob was tampered with or the wrong key is used."""
    nonce, ciphertext = blob[:NONCE_SIZE], blob[NONCE_SIZE:]
    return AESGCM(key).decrypt(nonce, ciphertext, associated_data=None)
