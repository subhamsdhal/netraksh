from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database.session import get_db
from backend.models.orm import AuditLog
from backend.security.auth import get_current_user

router = APIRouter(prefix="/api/audit", tags=["Audit"])

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
    
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
        
    logs = query.order_by(desc(AuditLog.timestamp)).offset(skip).limit(limit).all()
    total = query.count()
    
    # Format the response
    return {
        "total": total,
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "action": log.action,
                "user_id": log.user_id,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "ip_address": log.ip_address,
                "detail": log.detail,
                "success": log.success
            }
            for log in logs
        ]
    }
