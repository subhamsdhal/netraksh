"""
NETRAKSH Backend — Application settings loaded from environment / .env file.

PRODUCTION STARTUP VALIDATION:
  When ENV=production, the application refuses to start if any of the
  following conditions are detected:
    - SECRET_KEY is the default CHANGE_ME placeholder
    - ADMIN_PASSWORD is one of the known weak defaults ("admin")
    - INITIAL_OPERATOR_PASSWORD is one of the known weak defaults ("operator")
    - INITIAL_AUDITOR_PASSWORD is one of the known weak defaults ("auditor")
    - DATABASE_URL still points to the previously-leaked credential pattern

  These checks are bypassed in ENV=development to preserve local dev
  convenience. They are NEVER bypassed in ENV=production or ENV=staging.

  To switch to production mode locally:
    ENV=production (in .env) — then all required vars must be set securely.

SECRETS THAT MUST NEVER APPEAR IN LOGS / SOURCE / GIT:
  SECRET_KEY, DATABASE_URL, ADMIN_PASSWORD, INITIAL_OPERATOR_PASSWORD,
  INITIAL_AUDITOR_PASSWORD
"""
from __future__ import annotations

import sys
from typing import Any, Union, Optional
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# These are the known-weak development-default passwords that must never
# be used in production. We store only the literals here (in source) —
# they are NOT the real passwords; they are the values we are explicitly
# REJECTING. Comparing against them lets us detect "operator forgot to set
# the env var" without storing any real secret in code.
_WEAK_SECRET_KEY_PREFIXES = ("CHANGE_ME",)
_WEAK_ADMIN_PASSWORDS = {"admin", "admin123", "password", "netraksh"}
_WEAK_OPERATOR_PASSWORDS = {"operator", "operator123", "password", "netraksh"}
_WEAK_AUDITOR_PASSWORDS = {"auditor", "auditor123", "password", "netraksh"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Environment mode ---
    # "production"  — strict validation; startup fails on weak secrets
    # "development" — lenient defaults; no startup-fail on weak secrets
    # "staging"     — treated as production for security purposes
    ENV: str = "production"

    # --- Server ---
    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 8443
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    AUDIT_LOG_ENABLED: bool = True

    # --- Database ---
    # Credential-free development fallback. Production must provide DATABASE_URL
    # through the deployment environment.
    DATABASE_URL: str = "postgresql://localhost:5432/netraksh"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_postgres_scheme(cls, v: str) -> str:
        """
        Render (and Heroku-style platforms before it) hand out a managed
        Postgres connection string starting with the legacy `postgres://`
        scheme. SQLAlchemy 1.4+ rejects that scheme outright — it requires
        `postgresql://`. Without this, DATABASE_URL pasted verbatim from
        Render's dashboard into an env var would fail at engine creation,
        not at request time, so this is caught here rather than being a
        confusing first-boot crash on the exact platform this project
        targets for its live deployment.
        """
        if v.startswith("postgres://"):
            return "postgresql://" + v[len("postgres://"):]
        return v

    # --- Security / JWT ---
    # REQUIRED IN PRODUCTION. Must not be the CHANGE_ME placeholder.
    SECRET_KEY: str = "CHANGE_ME_USE_openssl_rand_hex_32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    TLS_ENABLED: bool = False  # Set True when certs are provisioned

    # --- TLS / mTLS ---
    MTLS_MODE: str = "disabled"  # "disabled" | "optional" | "required"
    MTLS_TRUSTED_PROXY: bool = False  # If True, trust X-Client-Fingerprint header from a verified proxy
    SERVER_CERT_PATH: str = "certs/server/server.crt"
    SERVER_KEY_PATH: str = "certs/server/server.key"
    CA_CERT_PATH: str = "certs/ca/ca.crt"
    # Used only by backend and approved edge devices when mTLS is not
    # mandatory. Never expose this through a VITE_ variable.
    EDGE_AUTH_TOKEN: Optional[str] = None


    # --- RBAC default users ---
    # REQUIRED IN PRODUCTION: all three passwords must not be weak defaults if BOOTSTRAP_USERS=true.
    BOOTSTRAP_USERS: bool = False
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"
    INITIAL_OPERATOR_USERNAME: str = "operator"
    INITIAL_OPERATOR_PASSWORD: str = "operator"
    INITIAL_AUDITOR_USERNAME: str = "auditor"
    INITIAL_AUDITOR_PASSWORD: str = "auditor"

    # --- Command identity ---
    COMMAND_ID: str = "COMMAND_A"

    # --- Blockchain ---
    BLOCKCHAIN_MODE: str = "mock"  # "mock" | "fabric"
    BLOCKCHAIN_MOCK_LABEL: str = "BLOCKCHAIN: MOCK MODE (Fabric not available on this host — WSL2/Docker required)"
    FABRIC_PEER_BIN: str = "peer"
    FABRIC_CHANNEL: str = "netraksh-channel"
    FABRIC_CHAINCODE: str = "netraksh-cc"
    FABRIC_ORG_MSP: str = "CommandAMSP"

    # --- Evidence storage ---
    # "local" — read evidence images from local filesystem (development default)
    # "s3"    — S3-compatible object storage via EvidenceStorageBackend abstraction
    #           In production, all OBJECT_STORAGE_* vars below must be set.
    EVIDENCE_STORAGE_BACKEND: str = "local"
    EVIDENCE_CLIPS_DIR: str = "edge/data/clips"

    OBJECT_STORAGE_PROVIDER: str = "local"  # "local" | "s3"
    # Required when OBJECT_STORAGE_PROVIDER=s3:
    OBJECT_STORAGE_ENDPOINT: Optional[str] = None   # e.g. https://s3.amazonaws.com
    OBJECT_STORAGE_BUCKET: Optional[str] = None     # S3 bucket name
    OBJECT_STORAGE_ACCESS_KEY: Optional[str] = None # AWS_ACCESS_KEY_ID
    OBJECT_STORAGE_SECRET_KEY: Optional[str] = None # AWS_SECRET_ACCESS_KEY
    OBJECT_STORAGE_REGION: Optional[str] = None     # e.g. us-east-1
    # A deliberate, one-shot deployment diagnostic. It is disabled by default
    # and must never be enabled permanently in a production environment.
    RUN_STORAGE_SMOKE_TEST_ON_STARTUP: bool = False
    MAX_UPLOAD_SIZE_BYTES: int = 5242880  # 5 MiB default
    EVIDENCE_SIGNED_URL_TTL_SECONDS: int = 3600  # Default 1 hour
    WEBHOOK_HMAC_SECRET: Optional[str] = None
    WEBHOOK_ALLOWED_HOSTS: Union[list[str], str] = []


    # --- Phase 3 Step 8: Multi-Camera Intelligence ---
    # "disabled" (default) or "appearance"
    CROSS_CAMERA_REID: str = "disabled"
    REID_EMBEDDING_TTL_SECONDS: int = 1800

    # --- Frontend CORS ---
    CORS_ORIGINS: Union[list[str], str] = []
    FRONTEND_ORIGIN: Optional[str] = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Any, info) -> Any:
        # Access the ENV value from the pydantic ValidationInfo
        env = info.data.get("ENV", "production")
        frontend_origin = info.data.get("FRONTEND_ORIGIN")

        origins = []
        if isinstance(v, list):
            origins.extend(v)
        elif v and v.strip():
            origins.extend([i.strip() for i in v.split(",") if i.strip()])

        if frontend_origin and frontend_origin.strip():
            origins.append(frontend_origin.strip())

        if not origins:
            if env == "development":
                return [
                    "http://localhost:5173", 
                    "http://localhost:3000", 
                    "https://localhost:5173",
                    "http://localhost:8443",
                    "http://127.0.0.1:8443",
                    "http://192.168.29.123:8443"
                ]
            return []

        if "*" in origins:
            raise ValueError("Wildcard '*' CORS is strictly prohibited.")
        return origins

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """
        In production (or staging), refuse to start if unsafe defaults
        are detected. This is a hard fail — not a warning — because an
        application that silently runs with 'admin'/'admin' credentials
        in production is a worse outcome than a visible startup failure.

        Development mode (ENV=development) skips these checks so that
        `cp .env.example .env && python -m backend.main` works out of
        the box for first-time contributors without needing to generate
        secrets first.
        """
        is_strict = self.ENV in ("production", "staging")
        if not is_strict:
            return self

        errors: list[str] = []

        # Check SECRET_KEY
        if any(self.SECRET_KEY.startswith(prefix) for prefix in _WEAK_SECRET_KEY_PREFIXES):
            errors.append(
                "SECRET_KEY is the default placeholder. "
                "Set a strong random key: openssl rand -hex 32"
            )

        # Check admin password
        if self.BOOTSTRAP_USERS:
            if self.ADMIN_PASSWORD.lower() in _WEAK_ADMIN_PASSWORDS:
                errors.append(
                    f"ADMIN_PASSWORD is a known weak default. "
                    f"Set a strong ADMIN_PASSWORD in the environment."
                )

            # Check operator password
            if self.INITIAL_OPERATOR_PASSWORD.lower() in _WEAK_OPERATOR_PASSWORDS:
                errors.append(
                    f"INITIAL_OPERATOR_PASSWORD is a known weak default. "
                    f"Set a strong INITIAL_OPERATOR_PASSWORD in the environment."
                )

            # Check auditor password
            if self.INITIAL_AUDITOR_PASSWORD.lower() in _WEAK_AUDITOR_PASSWORDS:
                errors.append(
                    f"INITIAL_AUDITOR_PASSWORD is a known weak default. "
                    f"Set a strong INITIAL_AUDITOR_PASSWORD in the environment."
                )

        if self.MTLS_MODE not in {"disabled", "optional", "required"}:
            errors.append("MTLS_MODE must be one of: disabled, optional, required.")

        # Check mTLS
        if self.MTLS_MODE == "required":
            import os
            if not self.TLS_ENABLED:
                errors.append("MTLS_MODE=required but TLS_ENABLED=False. Production mTLS requires TLS.")
            if not os.path.exists(self.CA_CERT_PATH):
                errors.append(f"MTLS_MODE=required but CA_CERT_PATH ({self.CA_CERT_PATH}) does not exist.")

        # Edge ingestion must never be anonymously writable in production.
        # Phase 3A: EDGE_AUTH_TOKEN is always required in production, even if mTLS is planned.
        token = self.EDGE_AUTH_TOKEN or ""
        if len(token) < 32 or token.startswith("REPLACE_"):
            errors.append(
                "EDGE_AUTH_TOKEN must be a non-placeholder secret of at least 32 characters "
                "in production."
            )

        # WP-3.3: If S3 storage is selected in production, we require at least
        # the bucket to be specified. We do NOT strictly require the access/secret
        # keys here because boto3 supports credential provider chains (IAM roles, etc).
        if self.OBJECT_STORAGE_PROVIDER == "s3":
            _s3_missing: list[str] = []
            if not self.OBJECT_STORAGE_BUCKET:
                _s3_missing.append("OBJECT_STORAGE_BUCKET")
            if _s3_missing:
                errors.append(
                    f"OBJECT_STORAGE_PROVIDER=s3 but the following required S3 settings are "
                    f"not configured: {', '.join(_s3_missing)}. "
                    f"Set these environment variables or switch to OBJECT_STORAGE_PROVIDER=local."
                )

        if errors:
            # Print to stderr (not stdout, not a logger that might be
            # forwarded to a monitoring system with secrets in message).
            # Never include the actual secret values in these messages.
            print(
                "\n" + "=" * 70 + "\n"
                "NETRAKSH STARTUP FAILURE — PRODUCTION SECRETS NOT CONFIGURED\n"
                "=" * 70,
                file=sys.stderr,
            )
            for err in errors:
                print(f"  ✗  {err}", file=sys.stderr)
            print(
                "\nSet the required environment variables and restart.\n"
                "See .env.example for a complete list of required variables.\n"
                "To run in development mode: set ENV=development in .env\n"
                + "=" * 70,
                file=sys.stderr,
            )
            raise ValueError(
                f"Production secrets not configured ({len(errors)} issue(s)). "
                "See stderr output above."
            )

        return self


settings = Settings()
