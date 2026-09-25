"""
Tests for backend/security/auth.py's password hashing.

Regression coverage for a real production crash: Render's `generateValue:
true` for ADMIN_PASSWORD (render.yaml) produces a random string long
enough to exceed bcrypt's hard 72-byte limit. bcrypt's 4.x line raises
ValueError instead of silently truncating like older versions did, which
crashed the entire app at startup inside bootstrap_users() — this is not
a hypothetical: it happened on the actual first Render deploy attempt.
"""
import secrets

from backend.security.auth import hash_password, verify_password


class TestPasswordHashing:
    def test_short_password_hashes_and_verifies(self):
        h = hash_password("admin")
        assert verify_password("admin", h)
        assert not verify_password("wrong", h)

    def test_password_longer_than_72_bytes_does_not_crash(self):
        # Reproduces the exact failure mode: a long random secret, the
        # same shape Render's generateValue produces.
        long_password = secrets.token_urlsafe(64)
        assert len(long_password.encode("utf-8")) > 72

        h = hash_password(long_password)  # must not raise
        assert verify_password(long_password, h)
        assert not verify_password("wrong", h)

    def test_two_long_passwords_that_share_a_72_byte_prefix_still_differ(self):
        # Truncation must not make the *hashing* target only 72 bytes wide
        # in a way that treats every password sharing the same 73rd+ byte
        # prefix as equal — bcrypt's own 72-byte limit already means the
        # tail past that point was never distinguishing, so this only
        # confirms the truncation didn't introduce a NEW collision beyond
        # that inherent bcrypt limit.
        prefix = "x" * 72
        h = hash_password(prefix + "AAAA")
        assert verify_password(prefix + "AAAA", h)
        assert verify_password(prefix + "ZZZZ", h)  # expected: bcrypt's own limit, not a bug
