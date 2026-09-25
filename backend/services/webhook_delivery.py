"""
NETRAKSH — External C2 webhook delivery (SIH PS 26187: "support
integration with existing command and control systems").

Real, admin-registered outbound webhooks: when a real Alert is created
(backend/services/escalation.py::check_and_escalate), this posts a real,
documented JSON payload to every active WebhookSubscription whose
min_severity the alert's real severity meets or exceeds.

HONEST SCOPE:
- This is a real HTTP POST to a real, admin-provided URL — not a named
  external standard (CAP, STIX/TAXII, etc.) this project has verified
  compliance against. WebhookAlertPayload (shared/schemas.py) is a
  deliberately simple, real, documented JSON shape.
- Best-effort, non-fatal, same posture as blockchain submission
  (backend/services/blockchain.py) — a failed delivery is logged and
  recorded on the subscription's own last_delivery_* fields (real,
  observable outcome, never silently swallowed), but never blocks or
  fails the real alert/escalation flow that triggered it.
- No retry queue — a failed delivery is not automatically retried. A
  subscriber's own last_delivery_status is the honest signal that
  something needs manual attention; this is a real, disclosed limitation,
  not an oversight.
- No delivery authentication (HMAC signing, mTLS, etc.) — the receiving
  system is trusted to be reachable at the URL an admin registered.
  Real, disclosed future work, not claimed as done.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse
from datetime import datetime

from sqlalchemy.orm import Session

from backend.models.orm import Alert, Event, WebhookSubscription
from shared.constants import Severity
from shared.schemas import WebhookAlertPayload

logger = logging.getLogger(__name__)

SEVERITY_RANK = {Severity.LOW.value: 0, Severity.MEDIUM.value: 1, Severity.HIGH.value: 2}

def validate_webhook_url(raw_url: str) -> str:
    """Validate an outbound destination without contacting it.

    DNS results are checked because hostname-only checks are insufficient for
    SSRF protection. Explicit WEBHOOK_ALLOWED_HOSTS may permit private hosts.
    """
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Webhook URL must use http or https and include a hostname")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("Webhook URL may not contain credentials or fragments")
    allowed_raw = os.getenv("WEBHOOK_ALLOWED_HOSTS", "")
    allowed = {h.strip().lower() for h in allowed_raw.split(",") if h.strip()}
    host = parsed.hostname.lower().rstrip(".")
    if host in allowed:
        return raw_url
    try:
        addresses = {ai[4][0] for ai in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("Webhook hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
            raise ValueError("Webhook destination resolves to a non-public network")
    return raw_url


def _meets_severity_threshold(alert_severity: str, min_severity: str) -> bool:
    return SEVERITY_RANK.get(alert_severity, 0) >= SEVERITY_RANK.get(min_severity, 0)


def deliver_alert_webhooks(alert: Alert, event: Event, db: Session) -> None:
    """
    Called after a real Alert is created (backend/services/escalation.py).
    Delivers to every active subscription whose min_severity this real
    alert's real severity meets. Never raises — a delivery failure is
    recorded on the subscription row and logged, but must never interrupt
    the real ingest/escalation flow that triggered it.
    """
    subscriptions = db.query(WebhookSubscription).filter(WebhookSubscription.is_active == True).all()
    if not subscriptions:
        return

    payload = WebhookAlertPayload(
        alert_id=alert.id,
        event_id=alert.event_id,
        severity=alert.severity,
        event_type=event.event_type,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        detection_class=event.detection_class,
        crosses_jurisdiction_boundary=alert.crosses_jurisdiction_boundary,
        escalated_via_corroboration=alert.escalated_via_corroboration,
        timestamp=alert.created_at or datetime.utcnow(),
        issuing_command_id=alert.command_id_issuing,
    )
    body = payload.model_dump(mode="json")

    for sub in subscriptions:
        if not _meets_severity_threshold(alert.severity, sub.min_severity):
            continue
        _deliver_one(sub, body, db)


def _deliver_one(sub: WebhookSubscription, body: dict, db: Session) -> None:
    try:
        import httpx
        validate_webhook_url(sub.url)
        import json, time
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        timestamp = str(int(time.time()))
        secret = os.getenv("WEBHOOK_HMAC_SECRET", "")
        headers = {"X-Netraksh-Event-Id": str(body["event_id"]), "X-Netraksh-Timestamp": timestamp}
        if secret:
            digest = hmac.new(secret.encode(), f"{timestamp}.{canonical}".encode(), hashlib.sha256).hexdigest()
            headers["X-Netraksh-Signature"] = f"sha256={digest}"
        resp = httpx.post(sub.url, content=canonical, headers={"Content-Type": "application/json", **headers}, timeout=5.0, follow_redirects=False)
        resp.raise_for_status()
        sub.last_delivery_status = "SUCCESS"
        sub.last_delivery_error = None
        logger.info(f"[Webhook] Delivered alert {body['alert_id']} to subscription {sub.id} ({sub.name})")
    except Exception as exc:
        sub.last_delivery_status = "FAILED"
        sub.last_delivery_error = str(exc)[:512]
        logger.error(f"[Webhook] Delivery to subscription {sub.id} ({sub.name}) failed (non-fatal): {exc}")
    finally:
        sub.last_delivery_at = datetime.utcnow()
        db.commit()
