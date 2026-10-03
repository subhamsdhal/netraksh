from datetime import timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database.session import get_db
from backend.models.orm import AuditLog, User
from backend.security.auth import get_current_user

router = APIRouter(prefix="/api/audit", tags=["Audit"])


def _utc_isoformat(value):
    """Serialize persisted UTC-naive audit timestamps unambiguously."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _actor_fields(log: AuditLog, username: Optional[str]) -> dict:
    if log.user_id:
        return {
            "actor_type": "USER",
            "username": username,
            "attempted_username": None,
        }
    if log.action == "LOGIN_FAILED":
        attempted_username = None
        if log.detail and log.detail.startswith("username="):
            attempted_username = log.detail.partition("=")[2].strip()[:64] or None
        return {
            "actor_type": "UNAUTHENTICATED",
            "username": None,
            "attempted_username": attempted_username,
        }
    return {
        "actor_type": "SYSTEM",
        "username": None,
        "attempted_username": None,
    }

@router.get("")
def get_audit_logs(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    action: Optional[str] = None,
    user_id: Optional[str] = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch paginated audit logs.
    Requires ADMIN or AUDITOR role.
    """
    if current_user.role not in ["ADMIN", "AUDITOR"]:
        # We don't raise 403 directly per earlier security principles but return 401/403 securely,
        # or we can rely on standard 403 for unauthorized access. Let's raise standard 403.
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Insufficient permissions for audit ledger.")
    
    query = db.query(AuditLog, User.username).outerjoin(User, AuditLog.user_id == User.id)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)

    total = query.count()
    rows = (
        query
        .order_by(desc(AuditLog.timestamp), desc(AuditLog.id))
        .offset(skip)
        .limit(limit)
        .all()
    )
    logs = [row[0] for row in rows]
    
    # Format the response
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "has_newer": skip > 0,
        "has_older": skip + len(logs) < total,
        "logs": [
            {
                "id": log.id,
                "timestamp": _utc_isoformat(log.timestamp),
                "action": log.action,
                "user_id": log.user_id,
                **_actor_fields(log, username),
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "ip_address": log.ip_address,
                "detail": log.detail,
                "success": log.success
            }
            for log, username in rows
        ]
    }
