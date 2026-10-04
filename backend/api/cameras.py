"""
NETRAKSH â€” Cameras router.
GET  /cameras          â€” list all cameras with latest health
GET  /cameras/{id}     â€” get camera detail + health history
POST /cameras          â€” register camera (ADMIN)
POST /cameras/{id}/health       â€” periodic real health telemetry from the edge
PUT  /cameras/{id}/public-key   â€” upload edge device public key (ADMIN)
PUT  /cameras/{id}/evidence-key â€” upload edge device evidence-encryption key (ADMIN)
PUT  /cameras/{id}/location     â€” set real lat/lon for the geospatial map (ADMIN)
"""

import asyncio
import base64
import hashlib
import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import Camera, CameraHealth, CameraKey
from backend.security.auth import require_admin, require_any_role, require_edge_auth, audit
from backend.security.evidence_key_wrap import wrap_key
from shared.schemas import (
    CameraHealthReport,
    CameraLocationUpdate,
    CameraRegistrationRequest,
    CameraStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=List[CameraStatusResponse])
async def list_cameras(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    cameras = db.query(Camera).filter(Camera.is_active == True).all()
    return [_camera_to_response(cam, db) for cam in cameras]


@router.get("/{camera_id}", response_model=CameraStatusResponse)
async def get_camera(
    camera_id: str,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return _camera_to_response(cam, db)


@router.post("/{camera_id}/health", status_code=status.HTTP_201_CREATED)
async def report_camera_health(
    camera_id: str,
    payload: CameraHealthReport,
    db: Session = Depends(get_db),
    edge_identity = Depends(require_edge_auth),
):
    """
    Periodic real health telemetry push from the edge (edge/main.py's
    EdgePipeline._report_camera_health, roughly every 5s), independent of
    any detection event.

    Before this endpoint existed, CameraHealthMonitor
    (edge/health/camera_health.py) computed real health every frame but
    nothing ever persisted it â€” the CameraHealth table was never written to
    by any code path, so GET /cameras always returned health_state=UNKNOWN
    for every real camera and the frontend's Camera Health Matrix page ran
    entirely on mock data. This is what actually connects the two.
    """
    if edge_identity and edge_identity.edge_id != camera_id:
        raise HTTPException(status_code=403, detail="Authenticated edge identity does not match camera_id")

    camera = db.query(Camera).filter(Camera.id == camera_id).first()
    if not camera:
        logger.warning(f"Health report from unknown camera {camera_id} — creating stub camera")
        camera = Camera(id=camera_id, name="Unknown / Unregistered Camera", location="unknown")
        db.add(camera)
        db.flush()

    record = CameraHealth(
        camera_id=camera_id,
        health_state=str(payload.health_state),
        health_reason=str(payload.health_reason),
        timestamp=payload.health_timestamp,
        fps_actual=payload.fps_actual,
        fps_declared=payload.fps_declared,
        drift_seconds=payload.drift_seconds,
        blur_score=payload.blur_score,
        exposure_clip_fraction=payload.exposure_clip_fraction,
        frame_variance=payload.frame_variance,
    )
    db.add(record)
    db.commit()

    from backend.api.websocket import broadcast_camera_health
    asyncio.create_task(broadcast_camera_health({
        "camera_id": camera_id,
        "health_state": record.health_state,
        "health_reason": record.health_reason,
        "fps_actual": record.fps_actual,
        "blur_score": record.blur_score,
        "exposure_clip_fraction": record.exposure_clip_fraction,
        "drift_seconds": record.drift_seconds,
        "last_health_check": record.timestamp.isoformat(),
    }))

    return {"camera_id": camera_id, "health_state": record.health_state}


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_camera(
    payload: CameraRegistrationRequest,
    request: Request,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    cam = Camera(
        name=payload.name,
        location=payload.location,
        owning_command_id="COMMAND_A",
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    db.add(cam)
    db.commit()
    audit(
        db,
        "CAMERA_REGISTERED",
        user_id=_admin.id,
        resource_type="Camera",
        resource_id=cam.id,
        ip_address=request.client.host if request.client else "unknown",
        detail=json.dumps({
            "display_name": cam.name,
            "physical_location": cam.location,
            "coordinates_supplied": cam.latitude is not None and cam.longitude is not None,
        }, separators=(",", ":")),
    )
    return {"camera_id": cam.id, "name": cam.name}


@router.put("/{camera_id}/public-key", status_code=status.HTTP_200_OK)
async def upload_public_key(
    camera_id: str,
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    """Upload or rotate the Ed25519 public key for a registered edge device.

    Lifecycle:
        - First upload: the key is registered as ACTIVE (KEY_REGISTERED audit event).
        - Subsequent upload with a different key: the old ACTIVE key is
          transitioned to RETIRED (KEY_RETIRED audit event) then the new key
          is made ACTIVE (KEY_ROTATION_REQUESTED audit event).
        - Re-uploading the same key: idempotent â€” the key is confirmed ACTIVE
          with no RETIRED transition.

    Historical evidence signed with the old kid remains verifiable:
        old kid -> old public key (now RETIRED, still in CameraKey table)

    KEY STATUS vs CRYPTOGRAPHIC VALIDITY are independent:
        A RETIRED key still validates signatures made before rotation.
        A REVOKED key: signatures are technically valid but operationally
        untrusted â€” the verification layer reports both.
    """
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    public_key_pem = payload.get("public_key_pem", "")
    if not public_key_pem:
        raise HTTPException(status_code=400, detail="Missing public_key_pem")

    # Derive kid per WP-3.1 specification:
    #   kid = "ed25519-" + lowercase(hex(SHA-256(DER SubjectPublicKeyInfo)))[:32]
    try:
        from cryptography.hazmat.primitives import serialization
        pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        canonical_bytes = pub_key.public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        digest = hashlib.sha256(canonical_bytes).hexdigest().lower()
        kid = f"ed25519-{digest[:32]}"
    except Exception as e:
        audit(
            db, "KEY_ROTATION_FAILED",
            user_id=_admin.id,
            resource_type="Camera", resource_id=camera_id,
            ip_address=request.client.host if request.client else "unknown",
            detail=f"Invalid public key PEM: {e}",
            success=False,
        )
        raise HTTPException(status_code=400, detail=f"Invalid public key PEM: {e}")

    # Retire existing ACTIVE keys that are different from the incoming key
    active_keys = db.query(CameraKey).filter(
        CameraKey.camera_id == camera_id,
        CameraKey.status == "ACTIVE"
    ).all()

    is_rotation = False
    for k in active_keys:
        if k.kid != kid:
            k.status = "RETIRED"
            k.retired_at = datetime.utcnow()
            is_rotation = True
            audit(
                db, "KEY_RETIRED",
                user_id=_admin.id,
                resource_type="CameraKey", resource_id=k.id,
                ip_address=request.client.host if request.client else "unknown",
                detail=f"camera_id={camera_id} kid={k.kid} (superseded by rotation)",
            )
            logger.info(f"[Cameras] Retired key kid={k.kid} for camera {camera_id}")

    # Insert or re-activate the new key
    existing_key = db.query(CameraKey).filter(CameraKey.kid == kid).first()
    if existing_key:
        if existing_key.camera_id != camera_id:
            audit(
                db, "KEY_ROTATION_FAILED",
                user_id=_admin.id,
                resource_type="Camera", resource_id=camera_id,
                ip_address=request.client.host if request.client else "unknown",
                detail=f"kid={kid} already registered to camera_id={existing_key.camera_id}",
                success=False,
            )
            raise HTTPException(status_code=400, detail="Key already registered to another camera")
        existing_key.status = "ACTIVE"
        existing_key.activated_at = datetime.utcnow()
    else:
        new_key = CameraKey(
            kid=kid,
            camera_id=camera_id,
            public_key_pem=public_key_pem,
            status="ACTIVE",
            created_at=datetime.utcnow(),
            activated_at=datetime.utcnow(),
        )
        db.add(new_key)

    # Preserve Camera.public_key_pem for backward compatibility
    cam.public_key_pem = public_key_pem
    db.commit()

    # Emit structured audit events (no key material logged)
    action = "KEY_ROTATION_REQUESTED" if is_rotation else "KEY_REGISTERED"
    audit(
        db, action,
        user_id=_admin.id,
        resource_type="Camera", resource_id=camera_id,
        ip_address=request.client.host if request.client else "unknown",
        detail=f"kid={kid}",
    )
    logger.info(f"[Cameras] {'Rotated' if is_rotation else 'Registered'} key kid={kid} for camera {camera_id}")

    return {"status": "ok", "camera_id": camera_id, "kid": kid, "rotated": is_rotation}


@router.put("/{camera_id}/evidence-key", status_code=status.HTTP_200_OK)
async def upload_evidence_key(
    camera_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    """
    Upload the edge device's raw AES-256 evidence-encryption key (base64;
    see edge/evidence/packager.py::EvidenceEncryptor.get_raw_key_b64(), and
    scripts/upload_evidence_key.py for a ready-made client for this call).

    The raw key is wrapped with a server-derived key before being stored
    (backend/security/evidence_key_wrap.py) â€” it is never persisted in the
    clear. Call this once per camera, over a trusted channel: in any
    non-local deployment this endpoint MUST be served over TLS, since the
    request body carries the raw key in transit â€” see docs/LIMITATIONS.md.

    Architecture v4 Â§10: this is what lets an authorized dashboard viewer
    decrypt this camera's evidence via GET /events/{event_id}/evidence-image.
    Before this is called for a camera, its evidence stays encrypted at rest
    (as it always has) but simply cannot be decrypted for viewing yet.
    """
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    raw_key_b64 = payload.get("evidence_key_b64", "")
    try:
        raw_key = base64.b64decode(raw_key_b64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="evidence_key_b64 is not valid base64")
    if len(raw_key) != 32:
        raise HTTPException(
            status_code=400,
            detail=f"Evidence key must be exactly 32 bytes (AES-256); got {len(raw_key)}",
        )

    cam.evidence_key_wrapped = wrap_key(raw_key)
    db.commit()
    logger.info(f"[Cameras] Evidence-encryption key registered for camera {camera_id}")
    return {"status": "ok", "camera_id": camera_id}


@router.put("/{camera_id}/edge-keys", status_code=status.HTTP_200_OK)
async def register_edge_keys(
    camera_id: str,
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
    edge_identity=Depends(require_edge_auth),
):
    """Register an edge's current public signing key and AES evidence key.

    This is an edge-to-command-center bootstrap path, not a browser endpoint.
    It is protected by the same edge authentication used for event ingest; in
    mTLS deployments the authenticated identity must belong to this camera.
    The AES key is wrapped before persistence and is never returned or logged.
    """
    if edge_identity is not None and getattr(edge_identity, "edge_id", camera_id) != camera_id:
        raise HTTPException(status_code=403, detail="Edge identity cannot register keys for another camera")
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    public_key_pem = payload.get("public_key_pem", "")
    encoded_key = payload.get("evidence_key_b64", "")
    if not public_key_pem or not encoded_key:
        raise HTTPException(status_code=400, detail="Both public_key_pem and evidence_key_b64 are required")
    try:
        from cryptography.hazmat.primitives import serialization
        pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
        canonical = pub_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        kid = f"ed25519-{hashlib.sha256(canonical).hexdigest().lower()[:32]}"
        raw_key = base64.b64decode(encoded_key, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid edge key material")
    if len(raw_key) != 32:
        raise HTTPException(status_code=400, detail="Evidence key must be exactly 32 bytes (AES-256)")

    existing = db.query(CameraKey).filter(CameraKey.kid == kid).first()
    if existing and existing.camera_id != camera_id:
        raise HTTPException(status_code=400, detail="Signing key is registered to another camera")
    for old in db.query(CameraKey).filter(CameraKey.camera_id == camera_id, CameraKey.status == "ACTIVE").all():
        if old.kid != kid:
            old.status, old.retired_at = "RETIRED", datetime.utcnow()
    if existing:
        existing.status, existing.activated_at = "ACTIVE", datetime.utcnow()
    else:
        db.add(CameraKey(kid=kid, camera_id=camera_id, public_key_pem=public_key_pem,
                         status="ACTIVE", created_at=datetime.utcnow(), activated_at=datetime.utcnow()))
    cam.public_key_pem = public_key_pem
    cam.evidence_key_wrapped = wrap_key(raw_key)
    db.commit()
    audit(db, "EDGE_KEY_BOOTSTRAPPED", resource_type="Camera", resource_id=camera_id,
          ip_address=request.client.host if request.client else "unknown", detail=f"kid={kid}")
    return {"status": "ok", "camera_id": camera_id, "kid": kid}


@router.put("/{camera_id}/location", status_code=status.HTTP_200_OK)
async def update_camera_location(
    camera_id: str,
    payload: CameraLocationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin = Depends(require_admin),
):
    """
    Set a camera's real latitude/longitude â€” what the Alerts page's
    geospatial map actually plots. Before this endpoint existed, no camera
    anywhere had real coordinates and that map was pure decoration (a
    static illustrative image with hardcoded pin positions).
    """
    cam = db.query(Camera).filter(Camera.id == camera_id).first()
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    cam.latitude = payload.latitude
    cam.longitude = payload.longitude
    db.commit()
    audit(
        db,
        "CAMERA_LOCATION_UPDATED",
        user_id=_admin.id,
        resource_type="Camera",
        resource_id=camera_id,
        ip_address=request.client.host if request.client else "unknown",
        detail=json.dumps({
            "latitude": cam.latitude,
            "longitude": cam.longitude,
        }, separators=(",", ":")),
    )
    return {"status": "ok", "camera_id": camera_id, "latitude": cam.latitude, "longitude": cam.longitude}


def _camera_to_response(cam: Camera, db: Session) -> CameraStatusResponse:
    latest_health = (
        db.query(CameraHealth)
        .filter(CameraHealth.camera_id == cam.id)
        .order_by(desc(CameraHealth.timestamp))
        .first()
    )
    return CameraStatusResponse(
        camera_id=cam.id,
        name=cam.name,
        location=cam.location,
        health_state=latest_health.health_state if latest_health else None,
        health_reason=latest_health.health_reason if latest_health else None,
        last_health_check=latest_health.timestamp if latest_health else None,
        fps_declared=latest_health.fps_declared if latest_health else None,
        blur_score=latest_health.blur_score if latest_health else None,
        exposure_clip_fraction=latest_health.exposure_clip_fraction if latest_health else None,
        fps_actual=latest_health.fps_actual if latest_health else None,
        drift_seconds=latest_health.drift_seconds if latest_health else None,
        latitude=cam.latitude,
        longitude=cam.longitude,
    )
