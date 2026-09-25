"""
NETRAKSH — Unit tests for backend/security/evidence_key_wrap.py
(architecture v4 §10 — wraps each camera's raw AES evidence key for
storage in the database, never persisting it in the clear).
"""
import base64
import os

import pytest

from backend.security import evidence_key_wrap as kw


def _raw_key() -> bytes:
    return os.urandom(32)


class TestWrapUnwrapRoundTrip:
    def test_round_trip(self):
        raw = _raw_key()
        wrapped = kw.wrap_key(raw)
        assert kw.unwrap_key(wrapped) == raw

    def test_wrapped_value_is_not_the_raw_key(self):
        raw = _raw_key()
        wrapped = kw.wrap_key(raw)
        assert base64.b64decode(wrapped) != raw
        assert raw not in base64.b64decode(wrapped)

    def test_wrapped_value_is_valid_base64_text(self):
        wrapped = kw.wrap_key(_raw_key())
        # Must not raise, and must be a plain str (fits the Text DB column).
        assert isinstance(wrapped, str)
        base64.b64decode(wrapped)  # raises if invalid

    def test_different_keys_wrap_differently(self):
        wrapped1 = kw.wrap_key(_raw_key())
        wrapped2 = kw.wrap_key(_raw_key())
        assert wrapped1 != wrapped2

    def test_same_key_wraps_differently_each_call(self):
        """Random nonce per call (shared/crypto.py) — even identical input
        must not produce identical stored ciphertext."""
        raw = _raw_key()
        assert kw.wrap_key(raw) != kw.wrap_key(raw)


class TestTamperDetection:
    def test_tampered_wrapped_value_fails_to_unwrap(self):
        wrapped = kw.wrap_key(_raw_key())
        raw_bytes = bytearray(base64.b64decode(wrapped))
        raw_bytes[-1] ^= 0xFF
        tampered = base64.b64encode(bytes(raw_bytes)).decode("ascii")
        with pytest.raises(Exception):
            kw.unwrap_key(tampered)

    def test_malformed_base64_raises_rather_than_returning_garbage(self):
        with pytest.raises(Exception):
            kw.unwrap_key("not valid base64 !!! ###")


class TestDomainSeparationFromJWTSecret:
    def test_wrap_key_does_not_equal_secret_key_derived_naively(self, monkeypatch):
        """The KEK must be a proper HKDF derivation, not settings.SECRET_KEY
        reused directly — this is the actual point of _derive_wrap_key()."""
        derived = kw._derive_wrap_key()
        from backend.config import settings
        assert derived != settings.SECRET_KEY.encode("utf-8")
        assert len(derived) == 32

    def test_derivation_is_deterministic_for_the_same_secret(self):
        """Same settings.SECRET_KEY must always derive the same KEK, or
        previously-wrapped keys in the database would become unreadable."""
        assert kw._derive_wrap_key() == kw._derive_wrap_key()
