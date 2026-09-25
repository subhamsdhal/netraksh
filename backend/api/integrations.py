"""
NETRAKSH — External integrations router (SIH PS 26187: "support
integration with existing command and control systems").

POST   /integrations/webhooks              — register an outbound webhook (ADMIN)
GET    /integrations/webhooks              — list webhook subscriptions (ADMIN)
DELETE /integrations/webhooks/{id}         — remove a subscription (ADMIN)
GET    /integrations/events/export         — real, paginated event export
                                              for pull-based external consumers

See backend/services/webhook_delivery.py and backend/models/orm.py's
WebhookSubscription docstring for the full honest scope.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.api.events import _event_to_response
from backend.database.session import get_db
from backend.models.orm import Event, WebhookSubscription
from backend.security.auth import require_admin, require_any_role, get_command_filter
from shared.schemas import (
    EventExportResponse,
    WebhookSubscriptionCreate,
    WebhookSubscriptionResponse,
)
from backend.services.webhook_delivery import validate_webhook_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])


def _sub_to_response(sub: WebhookSubscription) -> WebhookSubscriptionResponse:
    return WebhookSubscriptionResponse(
        subscription_id=sub.id,
        name=sub.name,
        url=sub.url,
        min_severity=sub.min_severity,
        is_active=sub.is_active,
        created_at=sub.created_at,
        last_delivery_at=sub.last_delivery_at,
        last_delivery_status=sub.last_delivery_status,
        last_delivery_error=sub.last_delivery_error,
    )


@router.post("/webhooks", status_code=status.HTTP_201_CREATED, response_model=WebhookSubscriptionResponse)
async def register_webhook(
    payload: WebhookSubscriptionCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    try:
        validate_webhook_url(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    sub = WebhookSubscription(name=payload.name, url=payload.url, min_severity=str(payload.min_severity))
    db.add(sub)
    db.commit()
    db.refresh(sub)
    logger.info(f"[Integrations] Registered webhook subscription {sub.id} ({sub.name}) -> {sub.url}")
    return _sub_to_response(sub)


@router.get("/webhooks", response_model=List[WebhookSubscriptionResponse])
async def list_webhooks(
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    subs = db.query(WebhookSubscription).filter(WebhookSubscription.is_active == True).all()
    return [_sub_to_response(s) for s in subs]


@router.delete("/webhooks/{subscription_id}", status_code=status.HTTP_200_OK)
async def remove_webhook(
    subscription_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    sub = db.query(WebhookSubscription).filter(WebhookSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    sub.is_active = False
    db.commit()
    return {"subscription_id": subscription_id, "is_active": False}


@router.get("/events/export", response_model=EventExportResponse)
async def export_events(
    since: Optional[str] = Query(None, description="ISO timestamp — only events at or after this"),
    min_severity: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    cursor: Optional[str] = Query(None, description="event_id of the last item from a previous page"),
    db: Session = Depends(get_db),
    _user=Depends(require_any_role),
):
    """
    Real, paginated event export for external C2 systems that prefer
    pulling over receiving inbound webhooks. Returns the same real
    EventResponse objects the dashboard itself uses — no separate,
    parallel data shape to keep honest and in sync.
    """
    q = db.query(Event)
    command_filter = get_command_filter(_user)
    if command_filter:
        from backend.models.orm import Camera
        q = q.join(Camera).filter(Camera.owning_command_id == command_filter)
        
    if since:
        from datetime import datetime
        try:
            since_dt = datetime.fromisoformat(since)
            q = q.filter(Event.timestamp >= since_dt)
        except ValueError:
            raise HTTPException(status_code=422, detail="`since` must be a real ISO timestamp")
    if min_severity:
        from backend.services.webhook_delivery import SEVERITY_RANK
        if min_severity not in SEVERITY_RANK:
            raise HTTPException(status_code=422, detail=f"`min_severity` must be one of {list(SEVERITY_RANK)}")
        allowed = [s for s, rank in SEVERITY_RANK.items() if rank >= SEVERITY_RANK[min_severity]]
        q = q.filter(Event.severity.in_(allowed))
    if cursor:
        cursor_event = db.query(Event).filter(Event.id == cursor).first()
        if cursor_event:
            q = q.filter(Event.timestamp < cursor_event.timestamp)

    events = q.order_by(desc(Event.timestamp)).limit(limit).all()
    next_cursor = events[-1].id if len(events) == limit else None
    return EventExportResponse(
        events=[_event_to_response(e, db) for e in events],
        next_cursor=next_cursor,
    )
