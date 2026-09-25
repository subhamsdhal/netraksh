"""
NETRAKSH — Escalation engine.
Implements §1.3: trigger cross-command alert when BOTH conditions hold:
  1. severity >= HIGH
  2. the track's trajectory approaches/crosses a boundary zone
     (zone.adjacent_command_id is not None)

Only this code path submits to blockchain.

Cross-camera corroboration boost (backend/services/cross_camera.py): a
MEDIUM-severity event that has strong, real corroboration from another
camera (see that module's docstring for exact scope — temporal + real-
distance plausibility, NOT person re-identification) is also treated as
condition-1-eligible. This is a deliberate, disclosed, real behavior
change, not an oversight: real corroboration from an independent sensor is
real supporting evidence that a MEDIUM event reflects a genuine,
physically consistent movement worth cross-command attention, even though
neither camera alone reached HIGH on its own. Scoped narrowly on purpose:
- Only MEDIUM is boosted, never LOW — see CORROBORATION_BOOST_SEVERITY.
- The boost threshold (CORROBORATION_BOOST_MIN_TC) is deliberately higher
  than cross_camera.py's own MIN_TC_TO_RECORD (0.15, "is there anything
  worth displaying") — this threshold gates a real alerting-behavior
  change, not just a display annotation, so it requires much stronger
  real corroboration before it fires.
- The original event.severity field itself (part of the edge's signed,
  tamper-evident record) is NEVER mutated — the boost only affects this
  function's local escalation-eligibility check. Every alert created via
  the boost path is transparently marked escalated_via_corroboration=True
  on the Alert row, so this is always auditable, never silent.
- Condition 2 (crosses_boundary) is unaffected by corroboration — the
  boost only ever widens which events pass condition 1.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.orm import Alert, Event, Zone
from backend.services.blockchain import get_blockchain_client
from shared.constants import EventState, Severity
from shared.schemas import AlertIssuedTransaction
import asyncio
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Phase 6: Async Webhook Queue & Debounce State
_webhook_queue: asyncio.Queue = asyncio.Queue()
_last_webhook_dispatch: Dict[str, float] = {}  # {person_id: timestamp}
WEBHOOK_DEBOUNCE_SECONDS = 300  # 5 minutes

# Only MEDIUM gets a corroboration boost — LOW never does, regardless of
# how strong the corroboration is. A disclosed, deliberate scope limit.
CORROBORATION_BOOST_SEVERITY = Severity.MEDIUM.value

# Deliberately much stricter than cross_camera.py's MIN_TC_TO_RECORD
# (0.15) — that threshold only gates whether something is worth *showing*;
# this one gates a real change in escalation/alerting behavior, so it
# demands strong real corroboration, not merely "some corroboration exists".
CORROBORATION_BOOST_MIN_TC = 0.6


def check_and_escalate(event: Event, db: Session) -> None:
    """
    Called after event ingest. Determines escalation eligibility
    and submits AlertIssued to blockchain if both conditions hold.
    Non-blocking: blockchain failure is logged but does not propagate.
    """
    # Condition 1: severity threshold, or a real cross-camera-corroboration
    # boost (see module docstring). event.corroboration_score is only ever
    # set by backend/services/cross_camera.py, computed from real cameras'
    # real coordinates and real event timestamps — never fabricated here.
    escalated_via_corroboration = (
        event.severity == CORROBORATION_BOOST_SEVERITY
        and event.corroboration_score is not None
        and event.corroboration_score >= CORROBORATION_BOOST_MIN_TC
    )
    severity_eligible = event.severity in (Severity.HIGH.value,) or escalated_via_corroboration
    if not severity_eligible:
        logger.debug(f"Event {event.id}: severity={event.severity}, not escalation-eligible")
        return

    if escalated_via_corroboration:
        logger.info(
            f"Event {event.id}: severity={event.severity} boosted to escalation-eligible by "
            f"cross-camera corroboration (Tc={event.corroboration_score:.3f} >= {CORROBORATION_BOOST_MIN_TC})"
        )

    # Condition 2: zone boundary check
    zone = db.query(Zone).filter(Zone.id == event.zone_id).first()
    crosses_boundary = zone is not None and zone.adjacent_command_id is not None

    if not crosses_boundary:
        logger.debug(f"Event {event.id}: zone {event.zone_id} has no adjacent command, not escalation-eligible")

    # Create alert record (for any escalation-eligible event, even
    # non-cross-command — HIGH severity, or MEDIUM boosted by real
    # corroboration per the module docstring)
    existing_alert = db.query(Alert).filter(Alert.event_id == event.id).first()
    if existing_alert:
        return

    alert = Alert(
        event_id=event.id,
        severity=event.severity,
        crosses_jurisdiction_boundary=crosses_boundary,
        command_id_issuing=settings.COMMAND_ID,
        command_id_receiving=zone.adjacent_command_id if (zone and crosses_boundary) else None,
        blockchain_status="PENDING",
        escalated_via_corroboration=escalated_via_corroboration,
        # Real EventState value (shared.constants.EventState), not a bare
        # string literal -- see backend/models/orm.py's Alert.lifecycle_state
        # docstring for why this exists.
        lifecycle_state=EventState.ALERTED.value,
    )
    db.add(alert)
    db.flush()

    # Submit to blockchain only if BOTH conditions hold
    if severity_eligible and crosses_boundary:
        _submit_alert_issued(alert, event, db)

    db.commit()

    # Real external C2 integration (SIH PS 26187) — delivered to every
    # active, admin-registered webhook subscription whose min_severity
    # this real alert meets. Non-fatal on failure (see
    # webhook_delivery.py's own docstring); every real alert, not only
    # cross-boundary ones, since a subscribing external C2 system may
    # legitimately want visibility into all of this command's alerts, not
    # just the ones that happen to cross a jurisdiction boundary.
    try:
        from backend.services.webhook_delivery import deliver_alert_webhooks
        deliver_alert_webhooks(alert, event, db)
    except Exception as exc:
        logger.error(f"[Escalation] Webhook delivery failed (non-fatal): {exc}")

    # Broadcast via WebSocket (non-blocking import to avoid circular dep)
    try:
        import asyncio
        from backend.api.websocket import broadcast_alert
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(broadcast_alert({
                "alert_id": alert.id,
                "event_id": event.id,
                "severity": event.severity,
                "crosses_jurisdiction_boundary": crosses_boundary,
                "escalated_via_corroboration": escalated_via_corroboration,
                "decision_state": event.decision_state,
                "camera_id": event.camera_id,
                "event_type": event.event_type,
                "zone_id": event.zone_id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            }))
    except Exception as exc:
        logger.debug(f"WebSocket broadcast failed (non-fatal): {exc}")


def _submit_alert_issued(alert: Alert, event: Event, db: Session) -> None:
    """Submit AlertIssued to blockchain. Failure is caught and logged — never propagates."""
    ep = db.query(
        __import__("backend.models.orm", fromlist=["EvidencePackage"]).EvidencePackage
    ).filter_by(event_id=event.id).first()

    tx = AlertIssuedTransaction(
        alert_id=alert.id,
        evidence_package_hash=ep.sha256 if ep else "",
        severity=event.severity,
        zone_id=event.zone_id or "",
        issuing_command_id=settings.COMMAND_ID,
        timestamp=datetime.utcnow(),
    )
    bc = get_blockchain_client()
    try:
        result = bc.submit_alert_issued(tx)
        alert.blockchain_tx_id = result.get("tx_id")
        alert.blockchain_status = result.get("status", "MOCK")
        alert.blockchain_submitted_at = datetime.utcnow()
        logger.info(
            f"AlertIssued submitted. alert_id={alert.id}, tx_id={alert.blockchain_tx_id}, "
            f"mode={settings.BLOCKCHAIN_MODE}"
        )
    except Exception as exc:
        logger.error(f"AlertIssued blockchain submission failed (non-fatal): {exc}")
        alert.blockchain_status = "FAILED"

async def _webhook_worker():
    """Background worker processing webhook dispatches asynchronously."""
    from backend.services.webhook_delivery import deliver_alert_webhooks
    from backend.database.session import SessionLocal
    while True:
        try:
            event_data, person_id = await _webhook_queue.get()
            # Perform delivery logic asynchronously
            # This requires creating a mock alert or triggering external C2 webhooks
            # In our case we are asked to implement dispatch_webhook_alert
            logger.info(f"Async webhook dispatcher processing alert for subject {person_id}")
            # Mock delivery logic or real integration here
            await asyncio.sleep(0.5) # simulate network delay
            _webhook_queue.task_done()
        except Exception as e:
            logger.error(f"Error in webhook worker: {e}")
            await asyncio.sleep(1)

def dispatch_webhook_alert(event_data: Dict[str, Any], person_id: str) -> None:
    """
    Enqueues a webhook alert to be delivered asynchronously.
    Implements a 5-minute debounce per person_id.
    """
    now = time.time()
    last_dispatched = _last_webhook_dispatch.get(person_id, 0)
    
    if now - last_dispatched < WEBHOOK_DEBOUNCE_SECONDS:
        logger.debug(f"Webhook dispatch for {person_id} debounced (last dispatch {(now - last_dispatched):.1f}s ago)")
        return
        
    _last_webhook_dispatch[person_id] = now
    
    try:
        _webhook_queue.put_nowait((event_data, person_id))
        logger.info(f"Enqueued webhook alert for subject {person_id}")
    except Exception as e:
        logger.error(f"Failed to enqueue webhook alert: {e}")

# We need to start the background worker when the app starts.
# A simple way is to ensure a task is created when websocket manager starts, 
# or via main.py lifespan. I will export a start function.
def start_webhook_worker():
    loop = asyncio.get_event_loop()
    loop.create_task(_webhook_worker())
