"""
NETRAKSH Backend — Security layer.
JWT authentication, RBAC (ADMIN/OPERATOR/AUDITOR), password hashing.
No private keys exposed to frontend. No credentials hardcoded.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Security, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import AuditLog, User
from shared.constants import UserRole

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------

def _truncate_for_bcrypt(password: str) -> str:
    """
    bcrypt has a hard 72-byte limit and, as of the `bcrypt` package's 4.x
    line, raises ValueError instead of silently truncating like older
    versions did. This bit in production: Render's `generateValue: true`
    for ADMIN_PASSWORD (render.yaml) produces a random string long enough
    to exceed 72 bytes, which crashed the whole app at startup inside
    bootstrap_users() — a real user could hit the same crash with a long
    real password, not just a generated one. Truncates at the byte level,
    dropping any partial trailing UTF-8 sequence so the result decodes
    cleanly. Every password this app hashes or verifies goes through this,
    for login (backend/api/auth.py), registration, and bootstrap alike.
    """
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(plain: str) -> str:
    return pwd_context.hash(_truncate_for_bcrypt(plain))


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_truncate_for_bcrypt(plain), hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Current user dependency
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    username: str = payload.get("sub", "")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_roles(*roles: UserRole):
    """Dependency factory that enforces RBAC."""
    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted for this action. Required: {[r.value for r in roles]}",
            )
        return current_user
    return _check


# Convenience role dependencies
require_admin = require_roles(UserRole.ADMIN)
require_operator_or_admin = require_roles(UserRole.ADMIN, UserRole.OPERATOR)
require_any_role = require_roles(UserRole.ADMIN, UserRole.OPERATOR, UserRole.AUDITOR)


# ---------------------------------------------------------------------------
# Command Isolation
# ---------------------------------------------------------------------------

def get_command_filter(user: User) -> Optional[str]:
    """
    Returns the command_id to filter by, or None if the user has global access.
    ADMIN and AUDITOR have global read access (None).
    OPERATOR is restricted to their command_id.
    """
    if user.role in [UserRole.ADMIN.value, UserRole.AUDITOR.value]:
        return None
    return user.command_id

def enforce_command_access(user: User, target_command_id: str) -> None:
    """
    Raises 403 Forbidden if the user is an OPERATOR and target_command_id != user.command_id.
    """
    filter_id = get_command_filter(user)
    if filter_id is not None and filter_id != target_command_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: command isolation boundary."
        )


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def audit(
    db: Session,
    action: str,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    detail: Optional[str] = None,
    success: bool = True,
) -> None:
    if not settings.AUDIT_LOG_ENABLED:
        return
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        detail=detail,
        success=success,
    )
    db.add(log)
    db.commit()


# ---------------------------------------------------------------------------
# Bootstrap: create or repair development users
# ---------------------------------------------------------------------------

def bootstrap_users(db: Session) -> None:
    """Ensure the configured initial accounts exist without creating duplicates.

    Development databases commonly outlive changes to the bootstrap code.  In
    that environment, an existing default account may therefore retain a
    stale password hash, role, or disabled flag.  Repair those *configured
    bootstrap accounts* idempotently so the documented local credentials keep
    working.  Production and staging never rewrite an existing account here;
    their passwords and roles are managed deliberately outside application
    startup.
    """
    if not settings.BOOTSTRAP_USERS and settings.ENV not in ("development", "test"):
        logger.info("Bootstrap: Automatic privileged-user bootstrap is DISABLED by default in production.")
        return

    defaults = [
        (settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD, UserRole.ADMIN.value),
        (settings.INITIAL_OPERATOR_USERNAME, settings.INITIAL_OPERATOR_PASSWORD, UserRole.OPERATOR.value),
        (settings.INITIAL_AUDITOR_USERNAME, settings.INITIAL_AUDITOR_PASSWORD, UserRole.AUDITOR.value),
    ]
    for username, password, role in defaults:
        existing = db.query(User).filter(User.username == username).first()
        if existing is None:
            user = User(username=username, hashed_password=hash_password(password), role=role)
            db.add(user)
            logger.info(f"Bootstrap: created user '{username}' with role '{role}'")
        elif settings.ENV in ("development", "test"):
            repaired = []
            if not verify_password(password, existing.hashed_password):
                existing.hashed_password = hash_password(password)
                repaired.append("password hash")
            if existing.role != role:
                existing.role = role
                repaired.append("role")
            if not existing.is_active:
                existing.is_active = True
                repaired.append("active status")
            if repaired:
                logger.info(
                    "Bootstrap: repaired %s for development user '%s'",
                    ", ".join(repaired),
                    username,
                )
    db.commit()


# ---------------------------------------------------------------------------
# Phase 4 WP-2: Edge Identity Binding
# ---------------------------------------------------------------------------

def extract_verified_client_identity(request: Request) -> Optional[dict]:
    """
    Extracts cryptographically verified client identity from the TLS connection.
    Supports two modes explicitly defined by MTLS_TRUSTED_PROXY:
    
    MODE A (MTLS_TRUSTED_PROXY=False): Direct TLS termination.
    Reads from ASGI scope `extensions.tls.client_cert`.
    
    MODE B (MTLS_TRUSTED_PROXY=True): Trusted reverse-proxy TLS termination.
    Reads `X-Client-Fingerprint` and `X-Client-Serial` headers.
    This MUST ONLY be used if the backend connection is strictly firewalled 
    to only allow traffic from the trusted proxy that performs the validation.
    """
    if settings.MTLS_TRUSTED_PROXY:
        fingerprint = request.headers.get("X-Client-Fingerprint")
        serial = request.headers.get("X-Client-Serial")
        if fingerprint:
            return {"fingerprint": fingerprint, "serial": serial}
        return None
    else:
        # MODE A: Direct Uvicorn TLS (ASGI standard)
        tls_ext = request.scope.get("extensions", {}).get("tls", {})
        client_cert_der = tls_ext.get("client_cert")
        if not client_cert_der:
            return None
            
        import hashlib
        # The ASGI spec provides the certificate as a DER-encoded byte string.
        # We hash it to generate the fingerprint.
        fingerprint = hashlib.sha256(client_cert_der).hexdigest().lower()
        
        # We don't parse the full x509 here for serial, but could if cryptography was available.
        # For our identity binding, fingerprint is the primary unique identifier.
        return {"fingerprint": fingerprint, "serial": None}

def get_edge_identity(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Dependency for Edge ingress endpoints (POST /events, /ws/sync).
    Binds the cryptographically verified client certificate to the EdgeIdentity.
    """
    from backend.models.orm import EdgeIdentity

    if settings.MTLS_MODE == "disabled":
        # No mTLS enforcement
        return None

    identity_info = extract_verified_client_identity(request)
    
    if not identity_info:
        if settings.MTLS_MODE == "required":
            audit(db, "EDGE_AUTHENTICATION_FAILED", ip_address=request.client.host if request.client else "unknown", detail="Missing client certificate")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Client certificate required")
        else:
            return None # Optional mode
            
    fingerprint = identity_info["fingerprint"]
    
    identity = db.query(EdgeIdentity).filter(EdgeIdentity.certificate_fingerprint == fingerprint).first()
    
    if not identity:
        audit(db, "EDGE_CERTIFICATE_UNKNOWN", ip_address=request.client.host if request.client else "unknown", detail=f"Unknown fingerprint: {fingerprint}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Certificate not registered")
        
    if identity.status == "REVOKED":
        audit(db, "EDGE_CERTIFICATE_REVOKED", ip_address=request.client.host if request.client else "unknown", detail=f"Revoked identity: {identity.edge_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Certificate revoked")
        
    if identity.status == "SUSPENDED":
        audit(db, "EDGE_CERTIFICATE_SUSPENDED", ip_address=request.client.host if request.client else "unknown", detail=f"Suspended identity: {identity.edge_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Certificate suspended")
        
    if identity.status == "EXPIRED":
        audit(db, "EDGE_CERTIFICATE_EXPIRED", ip_address=request.client.host if request.client else "unknown", detail=f"Expired identity: {identity.edge_id}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Certificate expired")
        
    if identity.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Identity is not active")

    # Optional: could check `expires_at` against datetime.utcnow() directly if not relying on background jobs to update status

    audit(db, "EDGE_CONNECTED", resource_type="EdgeIdentity", resource_id=identity.edge_id, ip_address=request.client.host if request.client else "unknown")
    
    return identity


def require_edge_auth(
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate an edge ingestion request without exposing its secret.

    Registered mTLS identities take precedence. Deployments where mTLS is
    optional or disabled must provision EDGE_AUTH_TOKEN to the backend and
    each approved edge. Local development remains deliberately permissive
    only when no token is configured, so a demo does not require a committed
    development secret.
    """
    identity = get_edge_identity(request, db)
    if identity is not None:
        return identity

    expected = settings.EDGE_AUTH_TOKEN
    scheme, _, supplied = request.headers.get("Authorization", "").partition(" ")
    if expected and scheme.lower() == "bearer" and secrets.compare_digest(supplied, expected):
        return None
    if settings.ENV in ("development", "test") and not expected:
        return None

    audit(
        db,
        "EDGE_AUTHENTICATION_FAILED",
        ip_address=request.client.host if request.client else "unknown",
        detail="Missing or invalid edge authentication",
        success=False,
    )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Edge authentication required")
