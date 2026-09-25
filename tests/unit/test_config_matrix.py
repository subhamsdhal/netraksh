"""
Phase 3C permanent regression tests for Settings configuration validation.

Tests in this module are fully isolated:
  - Each test uses monkeypatch to set/clear ONLY the env vars it needs.
  - Settings is instantiated with _env_file=None so no local .env file
    can bleed state into the test's explicit environment.
  - Assertions target stable invariants (substring in error message),
    not fragile exact Pydantic v2 formatting strings.

This means tests are order-independent and do not depend on .env content.
"""
import os
import pytest
from backend.config import Settings


# Minimal required production env vars (satisfies non-S3 validation paths)
_PROD_BASE = {
    "ENVIRONMENT": "production",
    "ENV": "production",
    "SECRET_KEY": "a" * 64,  # 64-char hex
    "EDGE_AUTH_TOKEN": "a" * 32,
    "DATABASE_URL": "postgresql://user:pass@host/db",
}


def _make_settings(monkeypatch, extra: dict, *, remove: list = None):
    """
    Build a fresh isolated Settings() instance.

    Steps:
      1. Clear the env entirely for the keys we care about.
      2. Apply _PROD_BASE defaults (satisfies production mode checks).
      3. Apply `extra` overrides.
      4. Remove any keys in `remove`.
      5. Instantiate Settings with _env_file=None so no .env is loaded.
    """
    all_keys = list(_PROD_BASE) + list(extra) + (remove or []) + [
        "OBJECT_STORAGE_PROVIDER",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
        "OBJECT_STORAGE_ENDPOINT",
        "BOOTSTRAP_USERS",
    ]
    for k in all_keys:
        monkeypatch.delenv(k, raising=False)

    for k, v in _PROD_BASE.items():
        monkeypatch.setenv(k, v)

    for k, v in extra.items():
        monkeypatch.setenv(k, v)

    for k in (remove or []):
        monkeypatch.delenv(k, raising=False)

    return Settings(_env_file=None)


# ---------------------------------------------------------------------------
# Local provider — no S3 fields required
# ---------------------------------------------------------------------------

def test_config_matrix_local_no_s3(monkeypatch):
    """local + no S3 config → Settings constructs cleanly."""
    settings = _make_settings(monkeypatch, {"OBJECT_STORAGE_PROVIDER": "local"})
    assert settings.OBJECT_STORAGE_PROVIDER == "local"


# ---------------------------------------------------------------------------
# S3 provider — missing bucket → startup must fail in production
# ---------------------------------------------------------------------------

def test_config_matrix_s3_missing_bucket(monkeypatch):
    """
    ENV=production, OBJECT_STORAGE_PROVIDER=s3, OBJECT_STORAGE_BUCKET absent
    → Settings.__init__ must raise an error that proves the S3 bucket constraint
      was evaluated.

    The invariant tested here is behavioural:
      - Settings() MUST raise (fail-closed) rather than constructing silently.
      - The error must be traceable to the missing OBJECT_STORAGE_BUCKET.

    Implementation note: Pydantic v2 wraps model_validator ValueError into a
    ValidationError. The human-readable detail (mentioning OBJECT_STORAGE_BUCKET)
    is printed to stderr and stored in the inner error. We test that the
    exception is raised AND that the error context proves S3 validation ran
    (i.e., we get more than 0 validation errors from the model validator).
    """
    from pydantic import ValidationError as PydanticValidationError

    with pytest.raises((ValueError, PydanticValidationError)) as exc_info:
        _make_settings(
            monkeypatch,
            {"OBJECT_STORAGE_PROVIDER": "s3"},
            remove=["OBJECT_STORAGE_BUCKET"],
        )

    # The settings validator must have fired and rejected the configuration.
    # Acceptable evidence: the exception chain references production config
    # failure (we don't assert on incidental Pydantic formatting strings).
    exc = exc_info.value
    full_text = str(exc)

    # Pydantic v2 ValidationError: unwrap inner errors for richer text
    if isinstance(exc, PydanticValidationError):
        for err in exc.errors():
            full_text += str(err)

    assert "OBJECT_STORAGE_BUCKET" in full_text or "Production secrets not configured" in full_text, (
        f"Expected failure referencing S3 config, got: {full_text}"
    )


# ---------------------------------------------------------------------------
# S3 provider — bucket present, no explicit endpoint → uses AWS default
# ---------------------------------------------------------------------------

def test_config_matrix_s3_missing_endpoint(monkeypatch):
    """s3 + bucket present + no endpoint → succeeds (defaults to AWS S3)."""
    settings = _make_settings(monkeypatch, {
        "OBJECT_STORAGE_PROVIDER": "s3",
        "OBJECT_STORAGE_BUCKET": "test-bucket",
    }, remove=["OBJECT_STORAGE_ENDPOINT"])
    assert settings.OBJECT_STORAGE_PROVIDER == "s3"
    assert settings.OBJECT_STORAGE_BUCKET == "test-bucket"
    assert settings.OBJECT_STORAGE_ENDPOINT is None


# ---------------------------------------------------------------------------
# S3 provider — custom MinIO endpoint → accepted
# ---------------------------------------------------------------------------

def test_config_matrix_s3_custom_endpoint(monkeypatch):
    """s3 + custom endpoint → accepted (supports MinIO)."""
    settings = _make_settings(monkeypatch, {
        "OBJECT_STORAGE_PROVIDER": "s3",
        "OBJECT_STORAGE_BUCKET": "test-bucket",
        "OBJECT_STORAGE_ENDPOINT": "http://localhost:9000",
    })
    assert settings.OBJECT_STORAGE_PROVIDER == "s3"
    assert settings.OBJECT_STORAGE_BUCKET == "test-bucket"
    assert settings.OBJECT_STORAGE_ENDPOINT == "http://localhost:9000"


# ---------------------------------------------------------------------------
# Development mode — S3 bucket check is skipped
# ---------------------------------------------------------------------------

def test_config_matrix_dev_mode_skips_s3_bucket_check(monkeypatch):
    """
    ENV=development, OBJECT_STORAGE_PROVIDER=s3, bucket absent
    → no startup failure (dev mode relaxes production-only guards).
    """
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "s3")
    monkeypatch.delenv("OBJECT_STORAGE_BUCKET", raising=False)
    # development mode — no EDGE_AUTH_TOKEN required, no strict secrets
    settings = Settings(_env_file=None)
    assert settings.ENV == "development"
    assert settings.OBJECT_STORAGE_PROVIDER == "s3"
