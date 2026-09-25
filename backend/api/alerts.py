"""
NETRAKSH — Alerts router.
GET  /alerts               — list alerts (cross-command view)
GET  /alerts/{id}          — get single alert
POST /alerts/{id}/acknowledge — Command B acknowledges alert
POST /alerts/{id}/close        — real terminal close action (SIH PS 26187
                                  audit finding: EventState.CLOSED was
                                  defined but never actually set anywhere)
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import Alert, AlertAcknowledgement, User
from backend.security.auth import audit, require_any_role, require_operator_or_admin, get_command_filter, enforce_command_access
from backend.services.blockchain import get_blockchain_client
from shared.constants import EventState
from shared.schemas import (
    AlertAcknowledgeRequest,
    AlertAcknowledgedTransaction,
    AlertResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=List[AlertResponse])
async def list_alerts(
    command_id: Optional[str] = Query(None, description="Filter by issuing or receiving command"),
    cross_command_only: bool = Query(False),
    severity: Optional[str] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    include_closed: bool = Query(False, description="Include alerts that have been closed (see POST /alerts/{id}/close)"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    q = db.query(Alert)
    command_filter = get_command_filter(_user)
    if command_filter:
        q = q.filter(
            (Alert.command_id_issuing == command_filter) | (Alert.command_id_receiving == command_filter)
        )
        
    if command_id:
        q = q.filter(
            (Alert.command_id_issuing == command_id) | (Alert.command_id_receiving == command_id)
        )
    if cross_command_only:
        q = q.filter(Alert.crosses_jurisdiction_boundary == True)
    if severity:
        q = q.filter(Alert.severity == severity)
    if acknowledged is not None:
        if acknowledged:
            q = q.filter(Alert.acknowledged_at.isnot(None))
        else:
            q = q.filter(Alert.acknowledged_at.is_(None))
    if not include_closed:
        # Default view is the active/open alert list -- a closed alert has
        # already been reviewed and resolved (POST /alerts/{id}/close), so
        # it shouldn't clutter the main dashboard forever. Real opt-in via
        # ?include_closed=true for anyone who wants the full history.
        q = q.filter(Alert.closed_at.is_(None))
    alerts = q.order_by(desc(Alert.created_at)).offset(offset).limit(limit).all()
    return [_alert_to_response(a) for a in alerts]


@router.get("/{alert_id}", response_model=AlertResponse)
async def get_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    command_filter = get_command_filter(_user)
    if command_filter and command_filter not in [alert.command_id_issuing, alert.command_id_receiving]:
        raise HTTPException(status_code=403, detail="Access denied: command isolation boundary.")
        
    return _alert_to_response(alert)


@router.post("/{alert_id}/acknowledge", response_model=AlertResponse)
async def acknowledge_alert(
    alert_id: str,
    payload: AlertAcknowledgeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin),
):
    """
    Command B operator acknowledges a cross-command alert.
    Submits AlertAcknowledged to blockchain if alert was issued via blockchain.
    RBAC: OPERATOR or ADMIN only (AUDITOR cannot acknowledge).
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    # Isolation: Operator cannot spoof receiving_command_id or acknowledge alerts outside their scope.
    command_filter = get_command_filter(current_user)
    target_receiving_command = payload.receiving_command_id
    if command_filter:
        target_receiving_command = command_filter
        if command_filter not in [alert.command_id_issuing, alert.command_id_receiving]:
            raise HTTPException(status_code=403, detail="Access denied: command isolation boundary.")
            
    # Atomic state transition
    now = datetime.utcnow()
    rows_affected = db.query(Alert).filter(
        Alert.id == alert_id,
        Alert.lifecycle_state == EventState.ALERTED.value
    ).update({
        Alert.acknowledged_at: now,
        Alert.acknowledged_by: current_user.username,
        Alert.command_id_receiving: target_receiving_command,
        Alert.lifecycle_state: EventState.ACKNOWLEDGED.value
    })
    
    if rows_affected == 0:
        raise HTTPException(status_code=409, detail="Alert already acknowledged or conflicted")

    db.refresh(alert)

    # Record acknowledgement
    ack = AlertAcknowledgement(
        alert_id=alert_id,
        receiving_command_id=target_receiving_command,
        ack_timestamp=now,
        status=payload.status,
        notes=payload.notes,
    )
    db.add(ack)

    # Submit AlertAcknowledged to blockchain (non-blocking — failure doesn't block dashboard)
    if alert.blockchain_status == "CONFIRMED" or alert.blockchain_status == "MOCK":
        bc = get_blockchain_client()
        tx = AlertAcknowledgedTransaction(
            alert_id=alert_id,
            receiving_command_id=payload.receiving_command_id,
            ack_timestamp=datetime.utcnow(),
            status=payload.status,
            signature="",  # would be org signature in real Fabric
        )
        try:
            result = bc.submit_alert_acknowledged(tx)
            ack.blockchain_tx_id = result.get("tx_id")
            ack.blockchain_status = result.get("status", "MOCK")
        except Exception as exc:
            logger.error(f"Blockchain AlertAcknowledged failed (non-fatal): {exc}")
            ack.blockchain_status = "FAILED"

    db.commit()
    audit(db, "ALERT_ACKNOWLEDGED", user_id=current_user.id, resource_type="alert", resource_id=alert_id)
    return _alert_to_response(alert)


@router.post("/{alert_id}/close", response_model=AlertResponse)
async def close_alert(
    alert_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator_or_admin),
):
    """
    Real terminal "close" action — the alert lifecycle's actual final step
    (shared.constants.EventState.CLOSED). Before this, an acknowledged
    alert had no further real action available; it stayed "acknowledged"
    forever with no way to mark it as fully reviewed/resolved. RBAC:
    OPERATOR or ADMIN only, same as acknowledge. Requires the alert to
    already be acknowledged first — a real, enforced lifecycle order, not
    just a UI suggestion.
    """
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
        
    command_filter = get_command_filter(current_user)
    if command_filter and command_filter not in [alert.command_id_issuing, alert.command_id_receiving]:
        raise HTTPException(status_code=403, detail="Access denied: command isolation boundary.")
        
    if not alert.acknowledged_at:
        raise HTTPException(status_code=400, detail="Alert must be acknowledged before it can be closed")
        
    # Atomic transition for closing
    now = datetime.utcnow()
    rows_affected = db.query(Alert).filter(
        Alert.id == alert_id,
        Alert.lifecycle_state == EventState.ACKNOWLEDGED.value
    ).update({
        Alert.closed_at: now,
        Alert.closed_by: current_user.username,
        Alert.resolution_notes: payload.get("resolution_notes"),
        Alert.lifecycle_state: EventState.CLOSED.value
    })
    
    if rows_affected == 0:
        raise HTTPException(status_code=409, detail="Alert already closed or conflicted")
        
    db.refresh(alert)

    db.commit()
    audit(db, "ALERT_CLOSED", user_id=current_user.id, resource_type="alert", resource_id=alert_id)
    return _alert_to_response(alert)


def _alert_to_response(alert: Alert) -> AlertResponse:
    return AlertResponse(
        alert_id=alert.id,
        event_id=alert.event_id,
        severity=alert.severity,
        crosses_jurisdiction_boundary=alert.crosses_jurisdiction_boundary,
        command_id_issuing=alert.command_id_issuing,
        command_id_receiving=alert.command_id_receiving,
        blockchain_status=alert.blockchain_status,
        blockchain_tx_id=alert.blockchain_tx_id,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        created_at=alert.created_at,
        camera_id=alert.event.camera_id if alert.event else None,
        event_type=alert.event.event_type if alert.event else None,
        zone_id=alert.event.zone_id if alert.event else None,
        escalated_via_corroboration=alert.escalated_via_corroboration,
        closed_at=alert.closed_at,
        closed_by=alert.closed_by,
        resolution_notes=alert.resolution_notes,
        lifecycle_state=alert.lifecycle_state,
    )
