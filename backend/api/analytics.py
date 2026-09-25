"""
NETRAKSH — Analytics API.
Provides server-side aggregated analytics from real database records.
No fabricated values. Every metric is derived from actual Event/Alert rows.

Endpoints:
  GET /analytics/summary    — totals and state counts for the time window
  GET /analytics/timeseries — event count bucketed by hour or day
  GET /analytics/by-type    — event counts grouped by event_type
  GET /analytics/by-camera  — event counts grouped by camera_id
  GET /analytics/by-severity — event counts grouped by severity

All endpoints:
  - Require authentication (require_any_role)
  - Support ?since=<ISO datetime> and ?until=<ISO datetime> for the time window
  - Use SQL GROUP BY / COUNT() — never download full event table
  - Return "not_available": true for metrics the current schema cannot provide

Time window defaults:
  since: 24 hours ago (if not supplied)
  until: now (if not supplied)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, case, text
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import Alert, Camera, Event, EvidencePackage, User
from backend.security.auth import require_any_role, get_command_filter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_window(since: Optional[str], until: Optional[str]) -> tuple[datetime, datetime]:
    """Parse the since/until query params. Defaults: last 24 hours."""
    try:
        t_until = datetime.fromisoformat(until) if until else datetime.now(timezone.utc).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid 'until' datetime: {until}")
    try:
        t_since = datetime.fromisoformat(since) if since else t_until - timedelta(hours=24)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid 'since' datetime: {since}")
    if t_since >= t_until:
        raise HTTPException(status_code=400, detail="'since' must be before 'until'")
    return t_since, t_until


def _window_events(
    db: Session,
    since: datetime,
    until: datetime,
    user: User = None,
    stream_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    event_type: Optional[str] = None,
):
    """Base query: events within the time window."""
    q = db.query(Event).filter(Event.timestamp >= since, Event.timestamp <= until)
    # REQUIREMENT 6: exclude system heartbeat/ABSTAIN events from real analytics
    q = q.filter(Event.decision_state != 'ABSTAIN')
    if user:
        command_filter = get_command_filter(user)
        if command_filter:
            q = q.join(Camera).filter(Camera.owning_command_id == command_filter)
    if stream_id:
        q = q.filter(Event.stream_id == stream_id)
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    if event_type:
        q = q.filter(Event.event_type == event_type)
    return q


def _window_alerts(db: Session, since: datetime, until: datetime, user: User = None):
    """Base query: alerts created within the time window."""
    q = db.query(Alert).filter(Alert.created_at >= since, Alert.created_at <= until)
    if user:
        command_filter = get_command_filter(user)
        if command_filter:
            q = q.filter((Alert.command_id_issuing == command_filter) | (Alert.command_id_receiving == command_filter))
    return q


# ---------------------------------------------------------------------------
# GET /analytics/summary
# ---------------------------------------------------------------------------

@router.get("/summary")
async def analytics_summary(
    since: Optional[str] = Query(None, description="ISO datetime lower bound (default: 24h ago)"),
    until: Optional[str] = Query(None, description="ISO datetime upper bound (default: now)"),
    stream_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Real aggregated summary for the given time window.
    All counts from actual database rows — no fabricated values.
    Fields marked 'not_available' cannot be derived from the current schema.
    """
    t_since, t_until = _parse_window(since, until)

    # --- Event totals ---
    events = _window_events(db, t_since, t_until, _user, stream_id, camera_id, event_type)
    total_events = events.count()

    # Decision state breakdown
    decision_rows = (
        events
        .with_entities(Event.decision_state, func.count(Event.id).label("n"))
        .group_by(Event.decision_state)
        .all()
    )
    by_decision = {row.decision_state: row.n for row in decision_rows}

    # Severity breakdown (events)
    severity_rows = (
        events
        .filter(Event.severity.isnot(None))
        .with_entities(Event.severity, func.count(Event.id).label("n"))
        .group_by(Event.severity)
        .all()
    )
    by_severity = {(row.severity or "UNKNOWN"): row.n for row in severity_rows}

    # Watchlist face-match events
    watchlist_events = (
        events
        .filter(Event.face_match_person_id.isnot(None))
        .count()
    )

    # ANPR events (plate_text not null)
    anpr_events = (
        events
        .filter(Event.plate_text.isnot(None))
        .count()
    )

    # Intrusion events (event_type = 'zone_intrusion' or 'fence_breach')
    intrusion_events = (
        events
        .filter(Event.event_type.in_(["zone_intrusion", "fence_breach", "loitering"]))
        .count()
    )

    # Vehicle events (detection_class = 'vehicle')
    vehicle_events = (
        events
        .filter(Event.detection_class == "vehicle")
        .count()
    )

    # Person events (detection_class = 'person')
    person_events = (
        events
        .filter(Event.detection_class == "person")
        .count()
    )

    # --- Alert totals ---
    total_alerts = _window_alerts(db, t_since, t_until, _user).count()
    acknowledged_alerts = (
        _window_alerts(db, t_since, t_until, _user)
        .filter(Alert.acknowledged_at.isnot(None))
        .count()
    )
    unresolved_alerts = (
        _window_alerts(db, t_since, t_until, _user)
        .filter(Alert.acknowledged_at.is_(None), Alert.closed_at.is_(None))
        .count()
    )
    closed_alerts = (
        _window_alerts(db, t_since, t_until, _user)
        .filter(Alert.closed_at.isnot(None))
        .count()
    )

    # Active cameras with events in window
    active_cameras = (
        events
        .with_entities(func.count(func.distinct(Event.camera_id)))
        .scalar()
    ) or 0

    verified_events = (
        events.join(EvidencePackage, EvidencePackage.event_id == Event.id)
        .filter(EvidencePackage.verified_ok.is_(True))
        .count()
    )
    detected = by_decision.get("DETECTED", 0)
    confidence_stats = events.with_entities(
        func.avg(Event.confidence), func.min(Event.confidence), func.max(Event.confidence)
    ).first()
    reliability_stats = events.with_entities(
        func.avg(Event.score_r), func.min(Event.score_r), func.max(Event.score_r)
    ).first()

    return {
        "window": {
            "since": t_since.isoformat(),
            "until": t_until.isoformat(),
        },
        "events": {
            "total": total_events,
            "by_decision": by_decision,
            "by_severity": by_severity,
            "watchlist_matches": watchlist_events,
            "anpr": anpr_events,
            "intrusion": intrusion_events,
            "vehicle": vehicle_events,
            "person": person_events,
            "verified": verified_events,
            "detection_rate_pct": round((detected / total_events) * 100, 2) if total_events else None,
            "confidence": {
                "average": confidence_stats[0],
                "minimum": confidence_stats[1],
                "maximum": confidence_stats[2],
            },
            "reliability": {
                "average": reliability_stats[0],
                "minimum": reliability_stats[1],
                "maximum": reliability_stats[2],
            },
        },
        "alerts": {
            "total": total_alerts,
            "acknowledged": acknowledged_alerts,
            "unresolved": unresolved_alerts,
            "closed": closed_alerts,
        },
        "cameras": {
            "active_in_window": active_cameras,
        },
        # Uptime cannot be derived from the current Event/Alert schema.
        # The edge pipeline reports per-device uptime in PipelineMetricsSnapshot,
        # not as a fleet-wide aggregated percentage in the analytics window.
        "uptime_pct": None,
        "uptime_not_available": True,
        "uptime_note": (
            "Per-device uptime is available on the Performance page "
            "(GET /system/metrics) from edge instrumentation data. "
            "Fleet-wide uptime percentage is not derivable from the current schema."
        ),
    }


# ---------------------------------------------------------------------------
# GET /analytics/timeseries
# ---------------------------------------------------------------------------

@router.get("/timeseries")
async def analytics_timeseries(
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    bucket: str = Query("hour", description="'hour' or 'day'"),
    stream_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Event count bucketed by hour or day, within the time window.
    Uses SQL strftime for SQLite or date_trunc for PostgreSQL.
    Returns list of {bucket, total, watchlist, intrusion, vehicle, person}.
    """
    if bucket not in ("hour", "day"):
        raise HTTPException(status_code=400, detail="bucket must be 'hour' or 'day'")

    t_since, t_until = _parse_window(since, until)
    events = _window_events(db, t_since, t_until, _user, stream_id, camera_id, event_type)

    # Detect database dialect for time bucketing
    dialect = db.bind.dialect.name if db.bind else "sqlite"

    if dialect == "postgresql":
        trunc_expr = func.date_trunc(bucket, Event.timestamp)
    else:
        # SQLite: strftime
        fmt = "%Y-%m-%d %H:00:00" if bucket == "hour" else "%Y-%m-%d"
        trunc_expr = func.strftime(fmt, Event.timestamp)

    rows = (
        events
        .with_entities(
            trunc_expr.label("bucket"),
            func.count(Event.id).label("total"),
            func.sum(
                case((Event.face_match_person_id.isnot(None), 1), else_=0)
            ).label("watchlist"),
            func.sum(
                case(
                    (Event.event_type.in_(["zone_intrusion", "fence_breach", "loitering"]), 1),
                    else_=0,
                )
            ).label("intrusion"),
            func.sum(
                case((Event.detection_class == "vehicle", 1), else_=0)
            ).label("vehicle"),
            func.sum(
                case((Event.detection_class == "person", 1), else_=0)
            ).label("person"),
        )
        .group_by(trunc_expr)
        .order_by(trunc_expr)
        .all()
    )

    return {
        "window": {"since": t_since.isoformat(), "until": t_until.isoformat()},
        "bucket": bucket,
        "series": [
            {
                "bucket": str(row.bucket),
                "total": row.total or 0,
                "watchlist": row.watchlist or 0,
                "intrusion": row.intrusion or 0,
                "vehicle": row.vehicle or 0,
                "person": row.person or 0,
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# GET /analytics/by-type
# ---------------------------------------------------------------------------

@router.get("/by-type")
async def analytics_by_type(
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Event counts grouped by event_type."""
    t_since, t_until = _parse_window(since, until)

    rows = (
        _window_events(db, t_since, t_until, _user, stream_id, camera_id, event_type)
        .with_entities(
            func.coalesce(Event.event_type, "unknown").label("event_type"),
            func.count(Event.id).label("n"),
        )
        .group_by(Event.event_type)
        .order_by(func.count(Event.id).desc())
        .all()
    )

    return {
        "window": {"since": t_since.isoformat(), "until": t_until.isoformat()},
        "by_type": [{"event_type": row.event_type, "count": row.n} for row in rows],
    }


# ---------------------------------------------------------------------------
# GET /analytics/by-camera
# ---------------------------------------------------------------------------

@router.get("/by-camera")
async def analytics_by_camera(
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Event counts grouped by camera_id, with camera name where available."""
    t_since, t_until = _parse_window(since, until)

    rows = (
        _window_events(db, t_since, t_until, _user, stream_id, camera_id, event_type)
        .with_entities(
            Event.camera_id,
            func.count(Event.id).label("n"),
        )
        .group_by(Event.camera_id)
        .order_by(func.count(Event.id).desc())
        .all()
    )

    # Enrich with camera names
    camera_names = {
        c.id: c.name for c in db.query(Camera.id, Camera.name).all()
    }

    return {
        "window": {"since": t_since.isoformat(), "until": t_until.isoformat()},
        "by_camera": [
            {
                "camera_id": row.camera_id,
                "camera_name": camera_names.get(row.camera_id, row.camera_id),
                "count": row.n,
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# GET /analytics/by-severity
# ---------------------------------------------------------------------------

@router.get("/by-severity")
async def analytics_by_severity(
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    camera_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Event counts grouped by severity (including events with null severity)."""
    t_since, t_until = _parse_window(since, until)

    rows = (
        _window_events(db, t_since, t_until, _user, stream_id, camera_id, event_type)
        .with_entities(
            func.coalesce(Event.severity, "NONE").label("severity"),
            func.count(Event.id).label("n"),
        )
        .group_by(Event.severity)
        .order_by(func.count(Event.id).desc())
        .all()
    )

    return {
        "window": {"since": t_since.isoformat(), "until": t_until.isoformat()},
        "by_severity": [{"severity": row.severity, "count": row.n} for row in rows],
    }


@router.get("/options")
async def analytics_options(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Return filter values that actually exist in persisted event rows."""
    return {
        "streams": [row[0] for row in db.query(Event.stream_id).filter(Event.stream_id.isnot(None)).distinct().order_by(Event.stream_id).all()],
        "cameras": [row[0] for row in db.query(Event.camera_id).distinct().order_by(Event.camera_id).all()],
        "event_types": [row[0] for row in db.query(Event.event_type).filter(Event.event_type.isnot(None)).distinct().order_by(Event.event_type).all()],
    }
