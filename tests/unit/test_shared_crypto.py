"""
NETRAKSH — Unit tests for shared/crypto.py (AES-256-GCM primitives shared
between edge/evidence/packager.py and backend/security/evidence_key_wrap.py).
"""
import os

import pytest

from shared.crypto import NONCE_SIZE, aes_gcm_decrypt, aes_gcm_encrypt


def _key() -> bytes:
    return os.urandom(32)


class TestRoundTrip:
    def test_encrypt_decrypt_round_trip(self):
        key = _key()
        plaintext = b"evidence bytes, arbitrary length" * 10
        blob = aes_gcm_encrypt(key, plaintext)
        assert aes_gcm_decrypt(key, blob) == plaintext

    def test_ciphertext_is_not_plaintext(self):
        key = _key()
        plaintext = b"\xff\xd8\xff\xe0some jpeg-like bytes"
        blob = aes_gcm_encrypt(key, plaintext)
        assert blob != plaintext
        assert plaintext not in blob

    def test_empty_plaintext_round_trips(self):
        key = _key()
        blob = aes_gcm_encrypt(key, b"")
        assert aes_gcm_decrypt(key, blob) == b""


class TestNonceUniqueness:
    def test_same_plaintext_encrypts_differently_each_time(self):
        key = _key()
        blob1 = aes_gcm_encrypt(key, b"identical plaintext")
        blob2 = aes_gcm_encrypt(key, b"identical plaintext")
        assert blob1 != blob2  # random nonce per call

    def test_blob_starts_with_a_nonce_of_the_documented_size(self):
        key = _key()
        blob = aes_gcm_encrypt(key, b"x")
        assert len(blob) >= NONCE_SIZE


class TestAuthenticatedEncryptionGuarantees:
    def test_tampered_ciphertext_fails_to_decrypt(self):
        key = _key()
        blob = bytearray(aes_gcm_encrypt(key, b"authentic evidence"))
        blob[-1] ^= 0xFF  # flip a bit in the GCM tag/ciphertext
        with pytest.raises(Exception):  # cryptography raises InvalidTag
            aes_gcm_decrypt(key, bytes(blob))

    def test_wrong_key_fails_to_decrypt(self):
        blob = aes_gcm_encrypt(_key(), b"secret evidence")
        with pytest.raises(Exception):
            aes_gcm_decrypt(_key(), blob)
