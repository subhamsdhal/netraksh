"""
NETRAKSH — Events router.
GET  /events           — list events (paginated, filterable)
GET  /events/{id}      — get single event with evidence
GET  /events/{id}/evidence-image — decrypted evidence image for an authorized viewer
POST /events           — ingest event from edge sync (edge device auth)
POST /events/{id}/verify — run integrity verification
"""
import json
import logging
import os
import hashlib
import csv
import io
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status, UploadFile, Form, File
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from backend.api.rate_limit import limiter
from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import Camera, EvidencePackage, Event, User
from backend.security.auth import audit, require_any_role, require_edge_auth, get_command_filter, enforce_command_access
from backend.security.evidence_key_wrap import unwrap_key
from backend.services.evidence_storage import get_evidence_storage, EvidenceNotFoundError, PathTraversalError, validate_object_key_segment
from backend.services.verification import authenticated_chain_scope, verify_event_integrity
from shared.crypto import aes_gcm_decrypt
from shared.schemas import (
    EventCreateRequest,
    EventResponse,
    VerificationResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=List[EventResponse])
async def list_events(
    camera_id: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    decision_state: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    q = db.query(Event)
    command_filter = get_command_filter(_user)
    if command_filter:
        q = q.join(Camera).filter(Camera.owning_command_id == command_filter)
        
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    if stream_id:
        q = q.filter(Event.stream_id == stream_id)
    if decision_state:
        q = q.filter(Event.decision_state == decision_state)
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if severity:
        q = q.filter(Event.severity == severity)
    events = q.order_by(desc(Event.timestamp)).offset(offset).limit(limit).all()
    return [_event_to_response(e, db) for e in events]


def _evidence_vault_query(
    db: Session,
    user: User,
    search: Optional[str] = None,
    camera_id: Optional[str] = None,
    stream_id: Optional[str] = None,
    decision_state: Optional[str] = None,
    event_type: Optional[str] = None,
    chain_status: Optional[str] = None,
):
    """Authoritative, evidence-only query shared by the vault page and export."""
    q = db.query(Event).join(EvidencePackage, EvidencePackage.event_id == Event.id)
    command_filter = get_command_filter(user)
    if command_filter:
        q = q.join(Camera).filter(Camera.owning_command_id == command_filter)
    if camera_id:
        q = q.filter(Event.camera_id == camera_id)
    if stream_id:
        q = q.filter(Event.stream_id == stream_id)
    if decision_state:
        q = q.filter(Event.decision_state == decision_state)
    if event_type:
        q = q.filter(Event.event_type == event_type)
    if chain_status:
        q = q.filter(EvidencePackage.chain_status == chain_status)
    if search:
        term = f"%{search.strip()}%"
        q = q.filter(or_(
            Event.id.ilike(term),
            Event.camera_id.ilike(term),
            Event.stream_id.ilike(term),
            Event.event_type.ilike(term),
            Event.decision_state.ilike(term),
            EvidencePackage.sha256.ilike(term),
        ))
    return q


@router.get("/evidence-vault")
async def list_evidence_vault(
    search: Optional[str] = Query(None, max_length=128),
    camera_id: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    decision_state: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    chain_status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    """Stable, paginated Evidence Vault listing backed by evidence packages."""
    q = _evidence_vault_query(
        db, _user, search, camera_id, stream_id, decision_state, event_type, chain_status,
    )
    total = q.count()
    rows = q.order_by(desc(Event.timestamp), desc(Event.id)).offset(offset).limit(limit).all()
    return {
        "items": [_event_to_response(event, db) for event in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _csv_safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@router.get("/evidence-vault/export")
async def export_evidence_vault(
    search: Optional[str] = Query(None, max_length=128),
    camera_id: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    decision_state: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    chain_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    """Export the complete filtered vault ledger, not only the visible page."""
    q = _evidence_vault_query(
        db, _user, search, camera_id, stream_id, decision_state, event_type, chain_status,
    )
    rows = q.order_by(desc(Event.timestamp), desc(Event.id)).all()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "Event ID", "Timestamp UTC", "Camera", "Analysis Session", "Event Type",
        "Decision", "SHA-256", "Hash Valid", "Ed25519 Valid", "Chain Status",
        "Storage Status",
    ])
    for event in rows:
        ep = event.evidence_package
        writer.writerow([_csv_safe(value) for value in (
            event.id, event.timestamp.isoformat(), event.camera_id, event.stream_id,
            event.event_type, event.decision_state, ep.sha256, ep.hash_valid,
            ep.signature_valid, ep.chain_status, event.storage_status,
        )])
    filename = f"netraksh_evidence_vault_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/correlation/current")
async def current_correlation(
    active_camera_ids: Optional[str] = Query(None),
    stream_ids: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    """Explain the current active-camera corroboration state.

    This is a read-only, persisted-event view. It never creates a result or
    claims identity/ReID; it simply reruns the same deterministic rule against
    the newest current-session event.
    """
    camera_ids = [value.strip() for value in (active_camera_ids or "").split(",") if value.strip()]
    streams = {value.strip() for value in (stream_ids or "").split(",") if value.strip()}
    if len(camera_ids) < 2:
        return {"status": "SECOND_CAMERA_REQUIRED", "active_camera_ids": camera_ids}
    query = db.query(Event).filter(Event.camera_id.in_(camera_ids))
    if streams:
        query = query.filter(Event.stream_id.in_(streams))
    latest = query.order_by(Event.timestamp.desc()).first()
    if latest is None:
        return {"status": "WAITING_FOR_SECOND_CAMERA", "active_camera_ids": camera_ids}
    from backend.services.cross_camera import find_corroboration, DEMO_CORRELATION_WINDOW_SECONDS
    status, result = find_corroboration(latest, db)
    if result and streams:
        secondary_stream = db.query(Event.stream_id).filter(Event.id == result.other_event_id).scalar()
        if secondary_stream not in streams:
            status, result = "WAITING_FOR_SECOND_CAMERA", None
    payload = {
        "status": status,
        "active_camera_ids": camera_ids,
        "correlation_window_seconds": DEMO_CORRELATION_WINDOW_SECONDS,
        "primary_event_id": latest.id,
        "primary_camera_id": latest.camera_id,
        "primary_event_type": latest.event_type,
    }
    if result:
        payload.update({
            "secondary_event_id": result.other_event_id,
            "secondary_camera_id": result.other_camera_id,
            "secondary_event_type": db.query(Event.event_type).filter(Event.id == result.other_event_id).scalar(),
            "time_delta_seconds": result.delta_t_s,
            "correlation_method": "TEMPORAL_CAMERA_RELATION_RULE",
            "reason": "Related cameras produced compatible security events within the configured window",
        })
    return payload


@router.get("/anpr", response_model=List[EventResponse])
async def search_anpr_reads(
    plate: Optional[str] = Query(None, description="Exact normalized plate"),
    partial: Optional[str] = Query(None, description="Case-insensitive normalized substring"),
    camera_id: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    """Protected historical ANPR search over persisted event metadata."""
    query = db.query(Event).filter(Event.normalized_plate_text.isnot(None))
    command_filter = get_command_filter(_user)
    if command_filter:
        query = query.join(Camera).filter(Camera.owning_command_id == command_filter)
    if plate:
        query = query.filter(Event.normalized_plate_text == plate.upper().replace(" ", "").replace("-", ""))
    if partial:
        query = query.filter(Event.normalized_plate_text.ilike(f"%{partial.upper().replace(' ', '')}%"))
    if camera_id:
        query = query.filter(Event.camera_id == camera_id)
    if start:
        query = query.filter(Event.timestamp >= start)
    if end:
        query = query.filter(Event.timestamp <= end)
    return [_event_to_response(event, db) for event in query.order_by(desc(Event.timestamp)).offset(offset).limit(limit).all()]


@router.get("/face", response_model=List[EventResponse])
async def search_face_events(
    camera_id: Optional[str] = Query(None),
    person_id: Optional[str] = Query(None),
    match_status: Optional[str] = Query(None),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    """Protected historical face-watchlist events, scoped to authorized cameras."""
    query = db.query(Event).filter(Event.event_type == "FACE_DETECTED")
    command_filter = get_command_filter(_user)
    if command_filter:
        query = query.join(Camera).filter(Camera.owning_command_id == command_filter)
    if camera_id:
        query = query.filter(Event.camera_id == camera_id)
    if person_id:
        query = query.filter(Event.watchlist_person_id == person_id)
    if match_status:
        query = query.filter(Event.face_match_status == match_status.upper())
    if start:
        query = query.filter(Event.timestamp >= start)
    if end:
        query = query.filter(Event.timestamp <= end)
    return [_event_to_response(event, db) for event in query.order_by(desc(Event.timestamp)).offset(offset).limit(limit).all()]


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    _user: User = Depends(require_any_role),
):
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    enforce_command_access(_user, event.camera.owning_command_id)
    return _event_to_response(event, db)


@router.get("/{event_id}/evidence-image")
async def get_evidence_image(
    request: Request,
    event_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Returns the decrypted evidence image for an event, for an authenticated,
    RBAC-gated viewer (architecture v4 §10). Requires require_any_role, same
    as get_event() and verify_event() above (auth was added to those two as
    part of the pre-deployment hardening pass — see docs/LIMITATIONS.md).

    IMPORTANT DEPLOYMENT CAVEAT (docs/LIMITATIONS.md): this reads the file
    directly from the local path stored in Event.evidence_clip_ref, which
    only works because the backend and edge device share a filesystem in
    this project's current single-machine deployment. Edge sync
    (edge/sync/sync_client.py) transmits only this path string today, not
    the evidence bytes themselves — a real distributed deployment, where
    the edge device and backend run on different machines, would need the
    edge to actually upload the bytes during sync. That is a separate,
    larger change, not implemented here.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    enforce_command_access(_user, event.camera.owning_command_id)
        
    if event.storage_status in ("CREATED", "UPLOADING"):
        raise HTTPException(status_code=425, detail="Evidence is still synchronizing")
    elif event.storage_status not in (None, "AVAILABLE"):
        raise HTTPException(status_code=404, detail=f"Evidence is not available (status: {event.storage_status})")

    # Treat object_key as the authoritative backend storage reference.
    ref = event.object_key
    if not ref:
        raise HTTPException(status_code=425, detail="Evidence binary has not been uploaded yet")
        
    storage = get_evidence_storage()
    
    # If the storage provider supports signed URLs, redirect the client directly.
    # Note: If the object is application-encrypted (.jpg.enc), the client will receive
    # the encrypted bytes and must decrypt them. If this is an issue, the backend could
    # stream and decrypt via get_object(), but generating a signed URL is the WP-3.3 preferred path.
    if event.storage_provider != "local":
        url = storage.generate_signed_url(ref, expires_in=settings.EVIDENCE_SIGNED_URL_TTL_SECONDS)
        if url:
            audit(db, "EVIDENCE_URL_GENERATED", user_id=_user.id, ip_address=request.client.host if hasattr(request, 'client') and request.client else "unknown",
                  resource_type="Event", resource_id=event_id)
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=url, status_code=307)

    try:
        raw = storage.get_object(ref)
    except PathTraversalError as exc:
        logger.warning(f"Path traversal blocked for event {event_id}: {exc}")
        raise HTTPException(status_code=400, detail="Invalid path in evidence reference.")
    except EvidenceNotFoundError as exc:
        logger.warning(f"Evidence not found for event {event_id}: {exc}")
        # If the DB says it's AVAILABLE but we can't find it, it's MISSING.
        if event.storage_status == "AVAILABLE":
            event.storage_status = "MISSING"
            db.commit()
            
        raise HTTPException(
            status_code=404,
            detail="Evidence file not found on the storage backend."
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))

    if ref.endswith(".jpg.enc"):
        camera = db.query(Camera).filter(Camera.id == event.camera_id).first()
        if not camera or not camera.evidence_key_wrapped:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Camera {event.camera_id} has not registered its evidence-encryption key "
                    f"yet — PUT /cameras/{event.camera_id}/evidence-key (see "
                    f"scripts/upload_evidence_key.py)."
                ),
            )
        try:
            raw_key = unwrap_key(camera.evidence_key_wrapped)
            image_bytes = aes_gcm_decrypt(raw_key, raw)
        except Exception as exc:
            logger.error(f"Evidence decryption failed for event {event_id}: {exc}")
            raise HTTPException(
                status_code=500,
                detail="Evidence decryption failed — wrong key, or the file was tampered with.",
            )
    else:
        # Legacy plain JPEG predating the AES-256 encryption change (real
        # examples of this exist in edge/data/clips/ from before that change
        # — see docs/LIMITATIONS.md) — served as-is, not an error case.
        image_bytes = raw

    audit(db, "EVIDENCE_DECRYPTED", user_id=_user.id, ip_address=request.client.host if hasattr(request, 'client') and request.client else "unknown",
          resource_type="Event", resource_id=event_id)

    return Response(content=image_bytes, media_type="image/jpeg")


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")  # Security: rate-limit edge ingest endpoint
async def ingest_event(
    request: Request,           # Required by slowapi to extract client IP
    payload: EventCreateRequest,
    db: Session = Depends(get_db),
    edge_identity = Depends(require_edge_auth),
):
    """
    Called by edge sync client when connectivity is restored.
    Runs server-side verification before storing.
    """
    from backend.services.escalation import check_and_escalate

    ep = payload.evidence_package

    # If mTLS identity is present, force the edge_device_id to match the authenticated identity.
    # We do NOT trust the edge_device_id provided inside the JSON payload if mTLS is active.
    authenticated_edge_id = edge_identity.edge_id if edge_identity else payload.edge_device_id

    if authenticated_edge_id != ep.camera_id:
        logger.warning(f"[Security] Cross-camera submission attempt blocked | auth_edge_id={authenticated_edge_id} target_camera_id={ep.camera_id}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated edge identity does not match evidence camera_id"
        )
        
    if payload.edge_device_id != ep.camera_id:
        logger.warning(f"[Security] Payload inconsistency blocked | edge_device_id={payload.edge_device_id} target_camera_id={ep.camera_id}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload edge_device_id must match evidence camera_id"
        )

    # Ensure camera exists (create stub if unknown, mark for review)
    camera = db.query(Camera).filter(Camera.id == ep.camera_id).first()
    if not camera:
        logger.warning(f"[Ingest] Event from unknown camera | camera_id={ep.camera_id} event_id={ep.event_id} kid={ep.kid}")
        camera = Camera(id=ep.camera_id, name=f"Unknown-{ep.camera_id[:8]}", location="unknown")
        db.add(camera)
        db.flush()

    # Ensure zone exists (create stub if unknown) to prevent IntegrityError
    if ep.zone_id:
        from backend.models.orm import Zone
        zone = db.query(Zone).filter(Zone.id == ep.zone_id).first()
        if not zone:
            logger.warning(f"[Ingest] Event from unknown zone | zone_id={ep.zone_id} event_id={ep.event_id} camera_id={ep.camera_id}")
            zone = Zone(
                id=ep.zone_id,
                camera_id=ep.camera_id,
                name=f"Unknown-{ep.zone_id[:8]}",
                zone_type="unknown",
                polygon_json="[]",
                owning_command_id=camera.owning_command_id,
            )
            db.add(zone)
            db.flush()

    # Check if event already exists (prevents crash from mock edge simulator re-sending same events)
    if db.query(Event).filter(Event.id == ep.event_id).first():
        logger.info(f"[Ingest] Duplicate detected, skipping ingest | event_id={ep.event_id} camera_id={ep.camera_id} kid={ep.kid}")
        return {"event_id": ep.event_id, "verified": True, "status": "duplicate"}

    # Create event record
    event = Event(
        id=ep.event_id,
        camera_id=ep.camera_id,
        stream_id=ep.stream_id,
        zone_id=ep.zone_id,
        timestamp=ep.timestamp,
        video_time=ep.video_time,
        event_type=ep.event_type,
        detection_class=ep.detection_class,
        confidence=ep.confidence,
        scene_condition=ep.scene_condition,
        camera_health_state=ep.camera_health_state,
        decision_state=ep.decision_state,
        decision_reason=ep.decision_reason,
        track_id=ep.track_id,
        severity=ep.severity,
        direction=ep.direction,
        rule=ep.rule,
        rule_value=ep.rule_value,
        plate_text=ep.plate_text,
        plate_confidence=ep.plate_confidence,
        raw_plate_text=ep.raw_plate_text,
        normalized_plate_text=ep.normalized_plate_text,
        localization_confidence=ep.localization_confidence,
        ocr_confidence=ep.ocr_confidence,
        observations_count=ep.observations_count,
        processing_method=ep.processing_method,
        fusion_state=ep.fusion_state,
        validation_status=getattr(ep, "validation_status", None),
        watchlist_match=getattr(ep, "watchlist_match", None),
        vehicle_subtype=ep.vehicle_subtype,
        face_match_person_id=ep.face_match_person_id,
        face_match_person_name=ep.face_match_person_name,
        face_match_confidence=ep.face_match_confidence,
        face_match_status=getattr(ep, "face_match_status", None),
        watchlist_person_id=getattr(ep, "watchlist_person_id", None) or ep.face_match_person_id,
        watchlist_label=getattr(ep, "watchlist_label", None) or ep.face_match_person_name,
        recognition_score=getattr(ep, "recognition_score", None),
        recognition_threshold=getattr(ep, "recognition_threshold", None),
        recognition_engine=getattr(ep, "recognition_engine", None),
        face_quality_status=getattr(ep, "face_quality_status", None),
        recognition_observation_count=getattr(ep, "recognition_observation_count", None),
        face_bbox_json=json.dumps(ep.face_bbox.model_dump()) if getattr(ep, "face_bbox", None) else None,
        face_engine=getattr(ep, "face_engine", None),
        similarity_score=getattr(ep, "similarity_score", None),
        recognition_state=getattr(ep, "recognition_state", None),
        alignment_method=getattr(ep, "alignment_method", None),
        lighting_state=getattr(ep, "lighting_state", None),
        mean_luminance=getattr(ep, "mean_luminance", None),
        dark_pixel_ratio=getattr(ep, "dark_pixel_ratio", None),
        enhancement_applied=getattr(ep, "enhancement_applied", None),
        detection_method=getattr(ep, "detection_method", None),
        motion_area=getattr(ep, "motion_area", None),
        motion_persistence=getattr(ep, "motion_persistence", None),
        evidence_clip_ref=ep.evidence_clip_ref,
        bbox_x=ep.bbox_x,
        bbox_y=ep.bbox_y,
        bbox_w=ep.bbox_w,
        bbox_h=ep.bbox_h,
        score_d=ep.score_d,
        score_t=ep.score_t,
        score_s=ep.score_s,
        score_h=ep.score_h,
        score_r=ep.score_r,
        edge_device_id=authenticated_edge_id,
        sequence_number=payload.sequence_number,
        synced_from_edge=True,
    )
    db.add(event)
    db.flush()

    # Store evidence package — idempotency guard prevents duplicate rows
    # if the edge retries an event that was already partially ingested.
    evidence = db.query(EvidencePackage).filter(EvidencePackage.event_id == ep.event_id).first()
    if not evidence:
        evidence = EvidencePackage(
            event_id=ep.event_id,
            schema_version=ep.schema_version,
            crypto_version=ep.crypto_version,
            kid=ep.kid,
            sha256=ep.hash or "",
            digital_signature=ep.signature or "",
            previous_hash=ep.previous_hash,
            current_hash=ep.hash or "",
            raw_package_json=json.dumps(ep.model_dump(), default=str),
        )
        db.add(evidence)
    else:
        logger.debug(
            f"EvidencePackage for event {ep.event_id} already exists — skipping insert "
            f"(camera_id={ep.camera_id})"
        )

    # 4) Tamper-evident verification (Phase 2 core mechanic)
    vr = verify_event_integrity(ep, db, payload.edge_device_id, payload.sequence_number)
    evidence.hash_valid = vr.hash_valid
    evidence.signature_valid = vr.signature_valid
    evidence.chain_valid = vr.chain_valid
    evidence.chain_status = vr.chain_status
    evidence.verified_ok = vr.hash_valid and vr.signature_valid and vr.chain_status == "VALID"
    evidence.verified_at = datetime.utcnow()

    db.commit()
    logger.info(
        f"Event ingested: event_id={ep.event_id} camera_id={ep.camera_id} "
        f"edge_device_id={payload.edge_device_id} seq={payload.sequence_number} "
        f"verified={evidence.verified_ok} decision={ep.decision_state}"
    )

    # 5) Iterative forward resolution if we just resolved a chain link
    if evidence.chain_status == "VALID":
        from backend.services.verification import resolve_pending_chains
        try:
            resolve_pending_chains(
                db, payload.edge_device_id, payload.sequence_number, evidence.current_hash,
                authenticated_chain_scope(ep),
            )
            db.commit()
        except Exception as exc:
            logger.error(f"Chain healing failed (non-fatal): {exc}")
            db.rollback()

    # Cross-camera corroboration (backend/services/cross_camera.py) — real,
    # computed now because it needs other cameras' already-committed events,
    # which only exist backend-side, never on the edge. Failure here must
    # never block ingest of the actual event; same non-fatal posture as
    # escalation/blockchain below.
    try:
        from backend.services.cross_camera import apply_corroboration
        correlation_result = apply_corroboration(event, db)
        from backend.api.websocket import broadcast_correlation
        import asyncio
        asyncio.create_task(broadcast_correlation({
            "status": event.corroboration_status,
            "primary_event_id": event.id,
            "primary_camera_id": event.camera_id,
            "primary_event_type": event.event_type,
            "secondary_event_id": correlation_result.other_event_id if correlation_result else None,
            "secondary_camera_id": correlation_result.other_camera_id if correlation_result else None,
            "time_delta_seconds": correlation_result.delta_t_s if correlation_result else None,
            "correlation_window_seconds": getattr(__import__("backend.services.cross_camera", fromlist=["DEMO_CORRELATION_WINDOW_SECONDS"]), "DEMO_CORRELATION_WINDOW_SECONDS", None),
        }))
    except Exception as exc:
        logger.error(f"Cross-camera corroboration failed for event {ep.event_id} (non-fatal): {exc}")

    # Check escalation eligibility
    check_and_escalate(event, db)

    # Watchlist-driven threat escalation (CRITICAL/SEVERE face matches only).
    # BUG FIX: was person.subject_name — WatchlistPerson.name is the correct field.
    if event.face_match_person_id:
        from backend.models.orm import WatchlistPerson
        from backend.services.escalation import dispatch_webhook_alert
        person = db.query(WatchlistPerson).filter(
            WatchlistPerson.id == event.face_match_person_id
        ).first()
        if person and person.threat_level in ("CRITICAL", "SEVERE"):
            logger.info(
                f"Watchlist match dispatch: event_id={event.id} "
                f"camera_id={event.camera_id} person_id={person.id} "
                f"threat_level={person.threat_level}"
                # Do NOT log person.name — biometric PII; do NOT log credentials
            )
            dispatch_webhook_alert({
                "event_id": event.id,
                "person_id": person.id,
                # FIXED: .name is the correct WatchlistPerson field (not .subject_name)
                "subject_name": person.name,
                "threat_level": person.threat_level,
                "camera_id": event.camera_id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            }, person.id)

    # Push to live dashboard
    from backend.api.websocket import broadcast_event
    import asyncio
    asyncio.create_task(broadcast_event(_event_to_response(event, db).model_dump(mode="json")))

    return {"event_id": ep.event_id, "verified": evidence.verified_ok}


@router.post("/{event_id}/evidence", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def ingest_evidence(
    request: Request,
    event_id: str,
    expected_hash: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    edge_identity = Depends(require_edge_auth),
):
    """
    WP-3.3: Explicit evidence binary upload via multipart form-data.
    Must be called after the main /events metadata ingest.
    """
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
        
    # WP-3.3 Edge identity enforcement
    authenticated_edge_id = edge_identity.edge_id if edge_identity else None
    if authenticated_edge_id and event.edge_device_id != authenticated_edge_id:
        raise HTTPException(status_code=403, detail="Not authorized to upload evidence for this event")
        
    if event.storage_status == "AVAILABLE":
        return {"status": "already_available"}
        
    event.storage_status = "UPLOADING"
    db.commit()

    # WP-3.3 Content-Type validation
    allowed_types = {"image/jpeg", "application/octet-stream"}
    if file.content_type not in allowed_types:
        event.storage_status = "FAILED"
        event.failure_reason = f"Unsupported Media Type: {file.content_type}"
        db.commit()
        raise HTTPException(status_code=415, detail=f"Unsupported Media Type. Expected {', '.join(allowed_types)}")

    # Read the upload BEFORE the try block that converts all exceptions to 500.
    # The HTTPException raised here (413, 415) must propagate directly to FastAPI
    # and must NOT be caught and downgraded by the generic handler below.
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        event.storage_status = "FAILED"
        event.failure_reason = f"Upload size {len(content)} exceeds limit {settings.MAX_UPLOAD_SIZE_BYTES}"
        db.commit()
        raise HTTPException(status_code=413, detail="Evidence file too large")

    try:
        # Validate segments
        safe_camera_id = validate_object_key_segment(event.camera_id, "camera_id")
        safe_event_id = validate_object_key_segment(event_id, "event_id", is_uuid=True)

        # Naming convention: evidence/{camera_id}/{date}/{event_id}.jpg.enc
        date_str = event.timestamp.strftime("%Y%m%d")
        ext = ".jpg.enc" if event.evidence_clip_ref and event.evidence_clip_ref.endswith(".enc") else ".jpg"

        # Validate binary characteristics
        if ext == ".jpg":
            if not content.startswith(b'\xff\xd8\xff'):
                raise ValueError("Invalid file format. Magic bytes do not match JPEG.")

        calculated_hash = hashlib.sha256(content).hexdigest()
        if calculated_hash != expected_hash:
            raise ValueError(f"Content hash mismatch. Expected {expected_hash}, got {calculated_hash}")

        object_key = f"evidence/{safe_camera_id}/{date_str}/{safe_event_id}{ext}"

        storage = get_evidence_storage()
        storage.put_object(object_key, content, content_type=file.content_type or "application/octet-stream")

        try:
            event.object_key = object_key
            event.storage_provider = settings.OBJECT_STORAGE_PROVIDER or "local"
            event.content_hash = calculated_hash
            event.content_size = len(content)
            event.storage_status = "AVAILABLE"
            event.uploaded_at = datetime.utcnow()
            event.failure_reason = None
            db.commit()
        except Exception as db_exc:
            db.rollback()
            try:
                storage.delete_object(object_key)
            except Exception as cleanup_exc:
                logger.error(f"Failed to cleanup orphan object {object_key} after DB failure: {cleanup_exc}")
            raise db_exc

        return {"status": "success", "object_key": object_key}

    except Exception as exc:
        db.rollback()
        event.storage_status = "FAILED"
        event.failure_reason = str(exc)
        db.commit()
        logger.error(f"Failed to ingest evidence for event {event_id}: {exc}")
        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc))
        raise HTTPException(status_code=500, detail="Failed to store evidence")



@router.post("/{event_id}/verify", response_model=VerificationResponse)
@limiter.limit("30/minute")  # Security: prevent brute-force verify/replay attacks
async def verify_event(
    request: Request,  # Required by slowapi
    event_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """One-click 'verify integrity' from the dashboard."""
    event = db.query(Event).filter(Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    evidence = db.query(EvidencePackage).filter(EvidencePackage.event_id == event_id).first()
    if not evidence or not evidence.raw_package_json:
        raise HTTPException(status_code=404, detail="Evidence package not found")

    from shared.schemas import EvidencePackage as EPSchema

    camera = db.query(Camera).filter(Camera.id == event.camera_id).first()
    ep = EPSchema(**json.loads(evidence.raw_package_json))
    vr = verify_event_integrity(ep, db, event.edge_device_id, event.sequence_number)

    # Update stored verification state
    evidence.hash_valid = vr.hash_valid
    evidence.signature_valid = vr.signature_valid
    evidence.chain_valid = vr.chain_valid
    evidence.chain_status = vr.chain_status
    evidence.verified_ok = vr.hash_valid and vr.signature_valid and vr.chain_status == "VALID"
    evidence.verified_at = datetime.utcnow()
    db.commit()

    audit(db, "EVIDENCE_VERIFIED", user_id=_user.id, ip_address=request.client.host if hasattr(request, 'client') and request.client else "unknown",
          resource_type="Event", resource_id=event_id, detail=f"verified_ok={evidence.verified_ok}")

    return vr


def _event_to_response(event: Event, db: Session) -> EventResponse:
    def _scalar(name: str):
        value = getattr(event, name, None)
        return value if value is None or isinstance(value, (str, int, float, bool)) else None

    ep = db.query(EvidencePackage).filter(EvidencePackage.event_id == event.id).first()
    from backend.models.orm import Alert
    alert = db.query(Alert).filter(Alert.event_id == event.id).first()
    # Preserve access to evidence created by pre-enum deployments.  These
    # aliases normalize only known historical values; unknown/corrupt values
    # still fail validation instead of being silently relabelled.
    detection_class = {"PERSON": "person", "VEHICLE": "vehicle"}.get(
        event.detection_class, event.detection_class
    )
    scene_condition = {"CLEAR": "CLEAR_DAY"}.get(event.scene_condition, event.scene_condition)
    camera_health_state = {"ONLINE": "OK"}.get(
        event.camera_health_state, event.camera_health_state
    )
    decision_state = {"VERIFIED": "DETECTED"}.get(event.decision_state, event.decision_state)
    return EventResponse(
        event_id=event.id,
        camera_id=event.camera_id,
        stream_id=event.stream_id if isinstance(event.stream_id, str) else None,
        timestamp=event.timestamp,
        video_time=event.video_time,
        event_type=event.event_type,
        detection_class=detection_class,
        confidence=event.confidence,
        scene_condition=scene_condition,
        camera_health_state=camera_health_state,
        decision_state=decision_state,
        decision_reason=event.decision_reason,
        zone_id=event.zone_id or "",
        track_id=event.track_id,
        severity=event.severity,
        schema_version=ep.schema_version if ep else None,
        crypto_version=ep.crypto_version if ep else None,
        hash=ep.sha256 if ep else None,
        signature=ep.digital_signature if ep else None,
        kid=ep.kid if ep else None,
        verified_ok=ep.verified_ok if ep else None,
        hash_valid=ep.hash_valid if ep else None,
        signature_valid=ep.signature_valid if ep else None,
        chain_valid=ep.chain_valid if ep else None,
        chain_status=ep.chain_status if ep else None,
        previous_hash=ep.previous_hash if ep else None,
        evidence_verified_at=ep.verified_at if ep else None,
        evidence_created_at=ep.created_at if ep else None,
        edge_device_id=event.edge_device_id,
        corroboration_score=event.corroboration_score,
        corroborated_by_event_id=event.corroborated_by_event_id,
        corroborating_camera_id=(
            event.corroborating_camera_id
            if isinstance(event.corroborating_camera_id, str)
            else None
        ),
        corroboration_distance_m=event.corroboration_distance_m,
        corroboration_delta_t_s=event.corroboration_delta_t_s,
        corroboration_t_expected_s=event.corroboration_t_expected_s,
        corroboration_sigma_s=event.corroboration_sigma_s,
        corroboration_status=event.corroboration_status,
        appearance_similarity=event.appearance_similarity,
        representation_type=event.representation_type,
        vehicle_subtype=event.vehicle_subtype,
        face_match_person_id=event.face_match_person_id,
        face_match_person_name=event.face_match_person_name,
        face_match_confidence=event.face_match_confidence,
        face_match_status=_scalar("face_match_status"),
        watchlist_person_id=_scalar("watchlist_person_id") or event.face_match_person_id,
        watchlist_label=_scalar("watchlist_label") or event.face_match_person_name,
        recognition_score=_scalar("recognition_score"),
        recognition_threshold=_scalar("recognition_threshold"),
        recognition_engine=_scalar("recognition_engine"),
        face_quality_status=_scalar("face_quality_status"),
        recognition_observation_count=_scalar("recognition_observation_count"),
        face_bbox_json=_scalar("face_bbox_json"),
        face_engine=_scalar("face_engine"),
        similarity_score=_scalar("similarity_score"),
        recognition_state=_scalar("recognition_state"),
        alignment_method=_scalar("alignment_method"),
        lighting_state=_scalar("lighting_state"),
        mean_luminance=_scalar("mean_luminance"),
        dark_pixel_ratio=_scalar("dark_pixel_ratio"),
        enhancement_applied=_scalar("enhancement_applied"),
        detection_method=_scalar("detection_method"),
        motion_area=_scalar("motion_area"),
        motion_persistence=_scalar("motion_persistence"),
        bbox_x=event.bbox_x,
        bbox_y=event.bbox_y,
        bbox_w=event.bbox_w,
        bbox_h=event.bbox_h,
        score_d=event.score_d,
        score_t=event.score_t,
        score_s=event.score_s,
        score_h=event.score_h,
        score_r=event.score_r,
        blockchain_tx_id=alert.blockchain_tx_id if alert else None,
        blockchain_status=alert.blockchain_status if alert else None,
        storage_provider=event.storage_provider,
        storage_status=event.storage_status,
        content_hash=event.content_hash,
        content_size=event.content_size,
        uploaded_at=event.uploaded_at,
        failure_reason=event.failure_reason,
        plate_text=_scalar("plate_text"),
        plate_confidence=_scalar("plate_confidence"),
        raw_plate_text=_scalar("raw_plate_text"),
        normalized_plate_text=_scalar("normalized_plate_text"),
        localization_confidence=_scalar("localization_confidence"),
        ocr_confidence=_scalar("ocr_confidence"),
        observations_count=_scalar("observations_count"),
        processing_method=_scalar("processing_method"),
        fusion_state=_scalar("fusion_state"),
        validation_status=_scalar("validation_status"),
        watchlist_match=_scalar("watchlist_match"),
    )
