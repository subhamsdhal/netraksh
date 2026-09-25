"""
NETRAKSH — Watchlist router (Phase 5).

Endpoints:
  GET    /watchlist              — list all active subjects (any role)
  POST   /watchlist              — register subject + first reference photo (ADMIN)
  PUT    /watchlist/{id}         — update location/status/threat level (ADMIN)
  POST   /watchlist/{id}/images  — add another reference photo (ADMIN)
  DELETE /watchlist/{id}         — soft-delete subject (ADMIN)
  GET    /watchlist/sync         — edge LBPH training sync (EDGE AUTH REQUIRED)

SECURITY:
  - All write operations require require_admin (JWT RBAC).
  - Reads require require_any_role.
  - /watchlist/sync requires require_edge_auth (SIH demo implementation).

SCOPE HONESTY:
  Face recognition is classical LBPH, NOT a production-grade deep-learning
  FRS. Sensitive to lighting/pose. No liveness detection. Results are leads
  for human review, NOT confirmed identifications. See docs/LIMITATIONS.md.
"""

import logging
import base64
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import cv2
import numpy as np

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.api.rate_limit import limiter
from backend.database.session import get_db
from backend.models.orm import WatchlistFaceImage, WatchlistPerson
from backend.models.orm import WatchlistFaceImage, WatchlistPerson
from backend.security.auth import audit, require_admin, require_any_role, require_edge_auth

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/watchlist", tags=["watchlist"])


# ─── Pydantic schemas (local — not yet in shared/schemas.py) ─────────────────

VALID_THREAT_LEVELS = {"ELEVATED", "SEVERE", "CRITICAL"}
MAX_ENROLLMENT_BYTES = 2 * 1024 * 1024
MIN_FACE_EDGE = 32


def _validate_face_image(image_base64: str) -> None:
    """Validate an enrollment image before it enters the watchlist.

    Raw image bytes remain available to the edge sync endpoint, but malformed,
    oversized, non-image, empty, and multi-face submissions are rejected here.
    No image/base64 data is written to logs.
    """
    if not isinstance(image_base64, str) or not image_base64:
        raise HTTPException(status_code=422, detail="image_base64 is required")
    if len(image_base64) > (MAX_ENROLLMENT_BYTES * 4 // 3 + 256):
        raise HTTPException(status_code=413, detail="Enrollment image exceeds 2 MiB limit")
    try:
        raw = base64.b64decode(image_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="image_base64 is not valid base64")
    if not raw or len(raw) > MAX_ENROLLMENT_BYTES:
        raise HTTPException(status_code=413, detail="Enrollment image exceeds 2 MiB limit")
    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=422, detail="Enrollment payload is not a supported image")
    h, w = image.shape[:2]
    if min(h, w) < MIN_FACE_EDGE:
        raise HTTPException(status_code=422, detail="Enrollment image is too small")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if float(np.std(gray)) < 5.0:
        raise HTTPException(status_code=422, detail="Enrollment image has insufficient visual quality")
    cascade_path = Path(__file__).resolve().parents[2] / "edge" / "detection" / "cascades" / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(MIN_FACE_EDGE, MIN_FACE_EDGE)) if not cascade.empty() else ()
    if len(faces) != 1:
        raise HTTPException(status_code=422, detail="Enrollment image must contain exactly one detectable face")


class WatchlistPersonResponse(BaseModel):
    """Full subject card response sent to the dashboard."""
    person_id: str
    name: str
    aliases: Optional[str] = None      # Semi-colon separated
    notes: Optional[str] = None
    threat_level: Optional[str] = "ELEVATED"
    category: Optional[str] = None
    last_known_location: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    last_seen_camera_id: Optional[str] = None
    is_active: bool
    face_image_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class WatchlistPersonCreate(BaseModel):
    """Payload for POST /watchlist — admin registration of a new subject."""
    name: str = Field(..., min_length=2, max_length=128)
    aliases: Optional[str] = Field(None, max_length=512,
        description="Semi-colon separated list of known aliases")
    notes: Optional[str] = None
    threat_level: Optional[str] = Field("ELEVATED",
        description="ELEVATED | SEVERE | CRITICAL")
    category: Optional[str] = Field(None, max_length=64)
    last_known_location: Optional[str] = Field(None, max_length=256)
    # First reference photo (base64 JPEG crop) — required for LBPH training
    image_base64: str = Field(..., description="Base64-encoded JPEG face crop")


class WatchlistPersonUpdate(BaseModel):
    """Payload for PUT /watchlist/{id} — update mutable fields."""
    aliases: Optional[str] = None
    notes: Optional[str] = None
    threat_level: Optional[str] = None
    category: Optional[str] = None
    last_known_location: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    last_seen_camera_id: Optional[str] = None
    is_active: Optional[bool] = None


class WatchlistSyncEntry(BaseModel):
    person_id: str
    name: str
    image_base64_list: List[str]


class WatchlistSyncResponse(BaseModel):
    persons: List[WatchlistSyncEntry]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _person_to_response(person: WatchlistPerson) -> WatchlistPersonResponse:
    return WatchlistPersonResponse(
        person_id=person.id,
        name=person.name,
        aliases=person.aliases,
        notes=person.notes,
        threat_level=person.threat_level or "ELEVATED",
        category=person.category,
        last_known_location=person.last_known_location,
        last_seen_at=person.last_seen_at,
        last_seen_camera_id=person.last_seen_camera_id,
        is_active=person.is_active,
        face_image_count=len(person.face_images),
        created_at=person.created_at,
    )


def _validate_threat_level(val: Optional[str]) -> str:
    if val is None:
        return "ELEVATED"
    upper = val.upper()
    if upper not in VALID_THREAT_LEVELS:
        raise HTTPException(
            status_code=422,
            detail=f"threat_level must be one of: {', '.join(sorted(VALID_THREAT_LEVELS))}"
        )
    return upper


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("", response_model=List[WatchlistPersonResponse])
@limiter.limit("60/minute")
async def list_watchlist(
    request: Request,
    threat_level: Optional[str] = None,
    db: Session = Depends(get_db),
    _user=Depends(require_any_role),
):
    """
    Returns all active watchlist subjects ordered by threat severity
    (CRITICAL → SEVERE → ELEVATED) then by most recently seen.

    Optional query param `?threat_level=CRITICAL` for filtered views.
    """
    q = db.query(WatchlistPerson).filter(WatchlistPerson.is_active == True)
    if threat_level:
        q = q.filter(WatchlistPerson.threat_level == threat_level.upper())
    persons = q.all()

    # Sort by threat severity (CRITICAL first), then most recently seen
    level_order = {"CRITICAL": 0, "SEVERE": 1, "ELEVATED": 2}
    persons.sort(key=lambda p: (
        level_order.get(p.threat_level or "ELEVATED", 2),
        -(p.last_seen_at.timestamp() if p.last_seen_at else 0),
    ))
    return [_person_to_response(p) for p in persons]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=WatchlistPersonResponse)
@limiter.limit("10/minute")  # Tighter limit — admin write operation
async def register_watchlist_person(
    request: Request,
    payload: WatchlistPersonCreate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    ADMIN ONLY. Register a new watchlist subject with their first reference photo.

    The image_base64 must be a JPEG face crop (not a full frame) for best LBPH
    accuracy. Multiple photos can be added via POST /watchlist/{id}/images.
    """
    threat = _validate_threat_level(payload.threat_level)
    _validate_face_image(payload.image_base64)
    person = WatchlistPerson(
        name=payload.name,
        aliases=payload.aliases,
        notes=payload.notes,
        threat_level=threat,
        category=payload.category,
        last_known_location=payload.last_known_location,
    )
    db.add(person)
    db.flush()
    image = WatchlistFaceImage(person_id=person.id, image_base64=payload.image_base64)
    db.add(image)
    db.commit()
    db.refresh(person)
    logger.info(
        f"[Watchlist] Registered {person.id} ({person.name}) "
        f"threat={threat} with 1 reference image"
    )
    audit(db, "WATCHLIST_ADD_SUBJECT", user_id=_admin.id, ip_address=request.client.host,
          resource_type="WatchlistPerson", resource_id=person.id, detail=f"name={payload.name}, threat={threat}")
    return _person_to_response(person)


@router.put("/{person_id}", response_model=WatchlistPersonResponse)
@limiter.limit("20/minute")
async def update_watchlist_person(
    request: Request,
    person_id: str,
    payload: WatchlistPersonUpdate,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    ADMIN ONLY. Update mutable fields on an existing watchlist subject.

    Typical use cases:
      - Updating last_known_location after a sighting
      - Escalating threat_level after new intelligence
      - Recording last_seen_at / last_seen_camera_id after a face-match event
      - Soft-archiving (is_active=False) without deleting the record
    """
    person = db.query(WatchlistPerson).filter(WatchlistPerson.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Watchlist person not found")

    # Apply only the fields that were explicitly provided (partial update)
    update_data = payload.model_dump(exclude_unset=True)

    if "threat_level" in update_data and update_data["threat_level"] is not None:
        update_data["threat_level"] = _validate_threat_level(update_data["threat_level"])

    for field, value in update_data.items():
        setattr(person, field, value)

    db.commit()
    db.refresh(person)
    logger.info(f"[Watchlist] Updated {person_id}: {list(update_data.keys())}")
    audit(db, "WATCHLIST_UPDATE_SUBJECT", user_id=_admin.id, ip_address=request.client.host,
          resource_type="WatchlistPerson", resource_id=person.id, detail=f"updated={list(update_data.keys())}")
    return _person_to_response(person)


@router.post("/{person_id}/images", status_code=status.HTTP_201_CREATED, response_model=WatchlistPersonResponse)
@limiter.limit("10/minute")
async def add_watchlist_image(
    request: Request,
    person_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    ADMIN ONLY. Add another reference face photo to an existing subject.
    More varied images (lighting/angle) genuinely improve LBPH match robustness
    against its known sensitivity to these factors.
    """
    person = db.query(WatchlistPerson).filter(WatchlistPerson.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Watchlist person not found")
    image_base64 = payload.get("image_base64")
    if not image_base64:
        raise HTTPException(status_code=422, detail="image_base64 is required")
    _validate_face_image(image_base64)
    image = WatchlistFaceImage(person_id=person_id, image_base64=image_base64)
    db.add(image)
    db.commit()
    db.refresh(person)
    audit(db, "WATCHLIST_ADD_IMAGE", user_id=_admin.id, ip_address=request.client.host,
          resource_type="WatchlistFaceImage", resource_id=image.id, detail=f"person_id={person_id}")
    return _person_to_response(person)


@router.delete("/{person_id}", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def remove_watchlist_person(
    request: Request,
    person_id: str,
    db: Session = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    ADMIN ONLY. Soft-delete a watchlist subject (is_active=False).
    Past face-match events referencing this person_id remain intact and
    auditable — we never hard-delete forensic evidence records.
    """
    person = db.query(WatchlistPerson).filter(WatchlistPerson.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail="Watchlist person not found")
    person.is_active = False
    db.commit()
    logger.info(f"[Watchlist] Soft-deleted {person_id} ({person.name})")
    audit(db, "WATCHLIST_REMOVE_SUBJECT", user_id=_admin.id, ip_address=request.client.host,
          resource_type="WatchlistPerson", resource_id=person.id)
    return {"person_id": person_id, "is_active": False}


@router.get("/sync", response_model=WatchlistSyncResponse)
async def sync_watchlist(
    db: Session = Depends(get_db),
    _edge=Depends(require_edge_auth),
):
    """
    Called by edge at startup + periodically to (re)train local LBPH recognizer.
    Returns all active persons WITH at least one reference image.
    """
    persons = db.query(WatchlistPerson).filter(WatchlistPerson.is_active == True).all()
    entries = [
        WatchlistSyncEntry(
            person_id=p.id,
            name=p.name,
            image_base64_list=[img.image_base64 for img in p.face_images],
        )
        for p in persons
        if p.face_images
    ]
    return WatchlistSyncResponse(persons=entries)
