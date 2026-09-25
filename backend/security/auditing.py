"""
NETRAKSH Backend — Immutable Audit Ledger Utilities.
Phase 7: Centralized auditing for defense-grade deployments.
"""
import logging
from typing import Optional
from sqlalchemy.orm import Session
from backend.models.orm import AuditLog
from fastapi import Request

logger = logging.getLogger(__name__)

def get_client_ip(request: Request) -> str:
    """Extract client IP from request securely (considering proxies)."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def log_audit_action(
    db: Session,
    action: str,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    detail: Optional[str] = None,
    success: bool = True
) -> None:
    """
    Writes a strict append-only record to the audit_logs table.
    Must be called within a database session that will be committed.
    """
    try:
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            detail=detail,
            success=success
        )
        db.add(audit_entry)
        db.commit()
    except Exception as e:
        logger.error(f"[AUDIT] Failed to write audit log for action {action}: {e}")
        # In a defense-grade system, failing to write an audit log might optionally panic or abort the action.
        # But we log the error and allow continuation to prevent denial of service unless configured otherwise.
        db.rollback()
