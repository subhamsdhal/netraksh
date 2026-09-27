"""
NETRAKSH — Shared Pydantic schemas.
These are the EXACT locked field sets from the architecture document (§1.2, §1.4).
Both edge and backend import from here; do not duplicate definitions elsewhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

from shared.constants import (
    BlockchainStatus,
    CameraHealthState,
    DecisionState,
    DetectionClass,
    EventType,
    HealthReason,
    SceneCondition,
    Severity,
    UserRole,
    ZoneType,
)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

class Point(BaseModel):
    x: float
    y: float


class Polygon(BaseModel):
    points: List[Point]


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def centroid(self) -> Point:
        return Point(x=(self.x1 + self.x2) / 2, y=(self.y1 + self.y2) / 2)

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1


# ---------------------------------------------------------------------------
# Zone (§2 correction — required for fence/checkpoint/verification gating)
# ---------------------------------------------------------------------------

class ZoneSchema(BaseModel):
    """
    A configured zone in the camera's field of view.
    zone_type determines which task module is activated for objects entering it.
    adjacent_command_id being non-null means crossing this zone boundary is
    eligible for cross-command escalation (§1.3).
    """
    zone_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    name: str
    zone_type: ZoneType
    polygon: Polygon
    owning_command_id: str
    adjacent_command_id: Optional[str] = None  # Non-null → boundary zone → escalation eligible
    # Wrong-way vehicle/movement detection (SIH PS 26187's "suspicious
    # activity detection") on a boundary-line zone (zone_type == "boundary",
    # exactly 2 polygon points — see LineCrossingModule). Value is a real
    # LineCrossingDirection string ("A_TO_B" or "B_TO_A"): a crossing in
    # THIS direction is flagged EventType.WRONG_DIRECTION instead of the
    # ordinary LINE_CROSSING. None (the default) means no restriction —
    # every existing zone without this configured behaves exactly as
    # before. Meaningless on fence-type zones; LineCrossingModule only
    # reads this on boundary-line zones.
    restricted_direction: Optional[str] = None

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Camera Health (Gate 1 output)
# ---------------------------------------------------------------------------

class CameraHealthReport(BaseModel):
    """Output of the Camera Health Monitor (Gate 1). All fields required."""
    camera_id: str
    health_state: CameraHealthState
    health_reason: HealthReason
    health_timestamp: datetime = Field(default_factory=datetime.utcnow)
    fps_actual: Optional[float] = None
    fps_declared: Optional[float] = None
    drift_seconds: Optional[float] = None
    blur_score: Optional[float] = None
    exposure_clip_fraction: Optional[float] = None
    frame_variance: Optional[float] = None

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Scene Condition (Gate 2 output)
# ---------------------------------------------------------------------------

class SceneConditionReport(BaseModel):
    """Output of the Scene Condition Classifier (Gate 2)."""
    camera_id: str
    condition: SceneCondition
    brightness_mean: float
    contrast_std: float
    # Real fix (docs/LIMITATIONS.md's fog+glare compound finding): contrast_std
    # is a single scalar over the WHOLE frame, so one small very-bright region
    # (real glare, a light source, a reflection) inflates it and masks a
    # genuinely hazy majority of the frame — exactly what happened in the real
    # fog_glare test (contrast_std≈41, above FOG_CONTRAST_THRESHOLD, while the
    # non-glare majority of the frame was genuinely foggy). This measures
    # spread among NON-blown-out pixels only (edge/condition/scene_condition.py
    # excludes the same near-white band glare_fraction already flags), so a
    # region-aware consumer (e.g. edge/reliability/decision.py's blur
    # exemption) can see the real haze the whole-frame scalar hides.
    # Optional/defaults to None so existing callers that construct this report
    # directly (tests, fixtures) are unaffected — consumers fall back to
    # contrast_std when this is None. Real production frames
    # (SceneConditionClassifier.classify()) always populate it.
    contrast_std_excluding_glare: Optional[float] = None
    glare_fraction: float
    # Explicit lighting state is derived from measured luminance, not demo
    # configuration.  Keep SceneCondition for backward compatibility while
    # exposing the finer low-light distinction needed by the UI and evidence.
    lighting_state: Optional[str] = None
    mean_luminance: Optional[float] = None
    dark_pixel_ratio: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Detection track
# ---------------------------------------------------------------------------

class TrackData(BaseModel):
    """Per-object track from YOLO + ByteTrack."""
    track_id: int
    detection_class: DetectionClass
    bbox: BoundingBox
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    trajectory: List[Point] = Field(default_factory=list)
    # Real sub-classification when detection_class == VEHICLE (see
    # shared.constants.VehicleSubtype) — None for every other detection
    # class, never fabricated when the underlying YOLO class is unknown.
    vehicle_subtype: Optional[str] = None
    source_class_id: Optional[int] = None
    tracker_state: str = "TRACKED_CURRENT_FRAME"
    matched_current_frame: bool = True

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_class_id(cls, values):
        """Translate the pre-v4 ``class_id`` input without exposing it in output."""
        if not isinstance(values, dict) or "detection_class" in values:
            return values
        class_id = values.get("class_id")
        if class_id is None:
            return values
        normalized = str(class_id).strip().lower()
        vehicle_types = {"car", "motorcycle", "bus", "truck", "vehicle"}
        mapping = {
            "person": DetectionClass.PERSON,
            "face": DetectionClass.FACE,
            "license_plate": DetectionClass.LICENSE_PLATE,
            "plate": DetectionClass.LICENSE_PLATE,
        }
        adapted = dict(values)
        adapted.pop("class_id", None)
        adapted["detection_class"] = (
            DetectionClass.VEHICLE if normalized in vehicle_types
            else mapping.get(normalized, DetectionClass.UNKNOWN)
        )
        if normalized in vehicle_types - {"vehicle"} and not adapted.get("vehicle_subtype"):
            adapted["vehicle_subtype"] = normalized
        return adapted

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Reliability decision (Gate 3 output)
# ---------------------------------------------------------------------------

class ReliabilityDecision(BaseModel):
    """
    Output of the 3-gate reliability layer.
    decision_state is the public-facing result: DETECTED / UNCERTAIN / ABSTAIN.
    decision_reason stores the internal explanation string (always logged).
    """
    decision_state: DecisionState
    decision_reason: str
    camera_health: CameraHealthState
    scene_condition: SceneCondition
    detector_confidence: float = Field(ge=0.0, le=1.0)
    applied_threshold: float = Field(ge=0.0, le=1.0)
    score_d: Optional[float] = None
    score_t: Optional[float] = None
    score_s: Optional[float] = None
    score_h: Optional[float] = None
    score_r: Optional[float] = None

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# Live Telemetry (architecture v4 §16)
# ---------------------------------------------------------------------------

class LiveTrack(BaseModel):
    track_id: int
    class_id: Optional[int] = None
    class_name: Optional[str] = None
    detection_class: str
    tracker_state: str = "TRACKED_CURRENT_FRAME"
    matched_current_frame: bool = True
    confidence: float
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float

class LiveDetection(BaseModel):
    detection_class: str
    confidence: float
    bbox_x: float
    bbox_y: float
    bbox_w: float
    bbox_h: float

class LiveTelemetryPayload(BaseModel):
    camera_id: str
    timestamp: float
    video_time: Optional[float] = None
    sequence: int
    # Dimensions and stream identity let the dashboard map boxes to the
    # rendered frame and discard delayed telemetry from a previous run.
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    stream_id: Optional[str] = None
    analysis_session_id: Optional[str] = None
    # Durable replay generation from the control plane. It prevents late
    # telemetry from an older replay from advancing the current lifecycle.
    analysis_generation: Optional[int] = None
    analysis_state: Optional[str] = None
    frame_index: Optional[int] = None
    source_timestamp: Optional[float] = None
    processed_timestamp: Optional[float] = None
    processing_fps: Optional[float] = None
    source_fps: Optional[float] = None
    fps_declared: Optional[float] = None
    expected_interval_ms: Optional[float] = None
    raw_detection_count: int = 0
    tracker_output_count: int = 0
    person_count: int = 0
    vehicle_count: int = 0
    track_count: int = 0
    active_track_ids: List[int] = Field(default_factory=list)
    tracker_output_ids: List[int] = Field(default_factory=list)
    raw_detections: List[LiveDetection] = Field(default_factory=list)
    preview_available: bool = False
    tracks: List[LiveTrack]


class TelemetryFramePayload(BaseModel):
    camera_id: str
    analysis_session_id: Optional[str] = None
    frame_index: Optional[int] = None
    source_timestamp: Optional[float] = None
    processed_timestamp: Optional[float] = None
    person_count: int = 0
    vehicle_count: int = 0
    track_count: int = 0
    clean_jpeg_base64: str
    annotated_jpeg_base64: str


# ---------------------------------------------------------------------------
# Evidence Package — EXACT locked field set from architecture §1.4
# ---------------------------------------------------------------------------

class EvidencePackage(BaseModel):
    """
    Locked evidence package. Every field name here is specified in the
    architecture document and must not be renamed or removed.
    Additional optional fields are appended after the mandatory set.
    """
    # --- Mandatory locked fields (§1.4) ---
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    camera_id: str
    timestamp: datetime
    zone_id: str
    detection_class: DetectionClass
    confidence: float = Field(ge=0.0, le=1.0)
    scene_condition: SceneCondition
    camera_health_state: CameraHealthState
    decision_state: DecisionState
    evidence_clip_ref: Optional[str] = None  # path to snapshot/clip on edge storage
    # Cryptographic fields (set by evidence layer, empty until signed)
    schema_version: Optional[str] = None
    crypto_version: Optional[str] = None
    hash: Optional[str] = None          # SHA-256 of serialized mandatory fields
    signature: Optional[str] = None     # Ed25519 signature over hash
    kid: Optional[str] = None           # Key ID for signature versioning
    previous_hash: Optional[str] = None  # hash of previous record in chain
    stream_id: Optional[str] = None      # Explicit session linkage
    # Concrete analysis-run identity.  Unlike source_stream_id, this rotates
    # for every explicit replay and is cryptographically bound by crypto-v2.
    analysis_session_id: Optional[str] = None
    # Position in the source video for finite uploads. Wall-clock sources may
    # legitimately omit this value.
    video_time: Optional[float] = None

    @model_validator(mode="after")
    def validate_crypto_version_metadata(self) -> EvidencePackage:
        schema = self.schema_version
        crypto = self.crypto_version
        if (schema is None) != (crypto is None):
            raise ValueError("Partial version metadata: schema_version and crypto_version must be both present or both null.")
        if crypto == "crypto-v2" and not self.analysis_session_id:
            raise ValueError("crypto-v2 evidence requires analysis_session_id.")
        return self

    # --- Optional contextual fields (appended per architecture §15) ---
    event_type: Optional[EventType] = None
    decision_reason: Optional[str] = None
    track_id: Optional[int] = None
    severity: Optional[Severity] = None
    # Deliberately `str`, not `FenceDirection`: this field is now shared by
    # multiple task modules with their own direction vocabularies
    # (FenceDirection for zone crossing, LineCrossingDirection for line
    # crossing — architecture v4 §5). Both are str-Enums, so existing values
    # pass through unchanged; a plain string here matches how the backend
    # already stores this column (backend/models/orm.py: String(32)).
    direction: Optional[str] = None
    rule: Optional[str] = None           # rule name that fired, e.g. "dwell_time_exceeded"
    rule_value: Optional[float] = None   # measured value, e.g. dwell seconds
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    raw_plate_text: Optional[str] = None
    normalized_plate_text: Optional[str] = None
    localization_confidence: Optional[float] = None
    ocr_confidence: Optional[float] = None
    observations_count: Optional[int] = None
    processing_method: Optional[str] = None
    fusion_state: Optional[str] = None
    validation_status: Optional[str] = None
    watchlist_match: Optional[bool] = None
    face_bbox: Optional[BoundingBox] = None
    face_confidence: Optional[float] = None
    # Real sub-classification when detection_class == VEHICLE (see
    # shared.constants.VehicleSubtype). Optional/contextual, same as
    # plate_text/face_bbox above — deliberately excluded from
    # get_signable_fields() below, same reasoning as those.
    vehicle_subtype: Optional[str] = None
    # Real watchlist face-match result (edge/detection/face_recognition.py) —
    # same optional/contextual, excluded-from-hash treatment as face_bbox
    # above. None whenever no match was found, never fabricated.
    face_match_person_id: Optional[str] = None
    face_match_person_name: Optional[str] = None
    face_match_confidence: Optional[float] = None
    # Explicit face-watchlist decision contract.  These fields distinguish a
    # known match from an evaluated-but-unknown face and from a face that was
    # not usable for recognition; absence is reserved for no face evaluation.
    face_match_status: Optional[str] = None
    watchlist_person_id: Optional[str] = None
    watchlist_label: Optional[str] = None
    recognition_score: Optional[float] = None
    recognition_threshold: Optional[float] = None
    recognition_engine: Optional[str] = None
    face_quality_status: Optional[str] = None
    recognition_observation_count: Optional[int] = None
    face_bbox_json: Optional[str] = None
    lighting_state: Optional[str] = None
    mean_luminance: Optional[float] = None
    dark_pixel_ratio: Optional[float] = None
    enhancement_applied: Optional[bool] = None
    detection_method: Optional[str] = None
    motion_area: Optional[float] = None
    motion_persistence: Optional[int] = None
    
    # Phase 3 Step 2 Advanced Face Recognition metadata
    face_engine: Optional[str] = None
    similarity_score: Optional[float] = None
    recognition_state: Optional[str] = None
    observation_count: Optional[int] = None
    alignment_method: Optional[str] = None
    
    # Phase 3 Step 7 Behavioral Analytics metadata
    behavior_type: Optional[str] = None
    measured_trigger_values: Optional[dict] = None
    observation_window: Optional[float] = None
    why: Optional[str] = None
    
    # Bounding box coordinates (normalized 0.0 - 1.0)
    bbox_x: Optional[float] = None
    bbox_y: Optional[float] = None
    bbox_w: Optional[float] = None
    bbox_h: Optional[float] = None
    
    # Reliability Score Breakdown
    score_d: Optional[float] = None
    score_t: Optional[float] = None
    score_s: Optional[float] = None
    score_h: Optional[float] = None
    score_r: Optional[float] = None

    class Config:
        use_enum_values = True

    def get_signable_fields(self) -> dict:
        """
        Deprecated as of Phase 8.4 — use `shared.versioning.extract_signable_dict()` for profile-aware extraction.
        This method is retained for backward compatibility and legacy test harnesses.
        
        Returns only the mandatory locked fields for hashing.
        Cryptographic fields (hash/signature/previous_hash) are excluded
        from their own hash computation to avoid circular dependency.
        """
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "timestamp": self.timestamp.isoformat(),
            "zone_id": self.zone_id,
            "detection_class": str(self.detection_class),
            "confidence": self.confidence,
            "scene_condition": str(self.scene_condition),
            "camera_health_state": str(self.camera_health_state),
            "decision_state": str(self.decision_state),
            "evidence_clip_ref": self.evidence_clip_ref or "",
            "previous_hash": self.previous_hash or "",
        }


# ---------------------------------------------------------------------------
# On-chain transaction schemas — EXACT locked field set from architecture §1.2
# ---------------------------------------------------------------------------

class AlertIssuedTransaction(BaseModel):
    """
    Only these fields ever go on-chain (§1.2). Nothing else.
    Populated by the escalation engine in backend/services/escalation.py.
    """
    alert_id: str
    evidence_package_hash: str          # SHA-256 of the evidence package
    severity: Severity
    zone_id: str
    issuing_command_id: str
    timestamp: datetime

    class Config:
        use_enum_values = True


class AlertAcknowledgedTransaction(BaseModel):
    """On-chain acknowledgement record (§1.2). Nothing else goes on-chain."""
    alert_id: str
    receiving_command_id: str
    ack_timestamp: datetime
    status: str                         # "ACKNOWLEDGED" | "DISMISSED"
    signature: str                      # Command B org signature

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# API request/response schemas
# ---------------------------------------------------------------------------

class EventCreateRequest(BaseModel):
    """Posted by the edge sync client to POST /events."""
    evidence_package: EvidencePackage
    edge_device_id: str
    sequence_number: int                # position in edge hash-chain


class EventResponse(BaseModel):
    event_id: str
    camera_id: str
    stream_id: Optional[str] = None
    timestamp: datetime
    video_time: Optional[float] = None
    event_type: Optional[EventType]
    detection_class: DetectionClass
    confidence: float
    scene_condition: SceneCondition
    camera_health_state: CameraHealthState
    decision_state: DecisionState
    decision_reason: Optional[str]
    zone_id: str
    track_id: Optional[int]
    severity: Optional[Severity]
    hash: Optional[str]
    signature: Optional[str]
    schema_version: Optional[str] = None
    crypto_version: Optional[str] = None
    kid: Optional[str] = None
    verified_ok: Optional[bool]
    hash_valid: Optional[bool] = None
    signature_valid: Optional[bool] = None
    chain_valid: Optional[bool] = None
    chain_status: Optional[str] = None
    previous_hash: Optional[str] = None
    evidence_verified_at: Optional[datetime] = None
    evidence_created_at: Optional[datetime] = None
    # Real field, always stored on ingest (backend/api/events.py) but never
    # previously exposed here — the frontend's Evidence page used to show a
    # hardcoded "edge-001 (Active)" for every event because this field
    # simply didn't reach it. None when genuinely absent (never fabricated).
    edge_device_id: Optional[str] = None
    # Cross-camera corroboration (backend/services/cross_camera.py) — see
    # that module's docstring for exact meaning and scope. All None when no
    # plausible corroborating sighting was found; never fabricated.
    corroboration_score: Optional[float] = None
    corroborated_by_event_id: Optional[str] = None
    corroborating_camera_id: Optional[str] = None
    corroboration_status: Optional[str] = None
    corroboration_distance_m: Optional[float] = None
    corroboration_delta_t_s: Optional[float] = None
    corroboration_t_expected_s: Optional[float] = None
    corroboration_sigma_s: Optional[float] = None
    
    appearance_similarity: Optional[float] = None
    representation_type: Optional[str] = None
    
    # BBox coordinates
    bbox_x: Optional[float] = None
    bbox_y: Optional[float] = None
    bbox_w: Optional[float] = None
    bbox_h: Optional[float] = None
    
    # Reliability scores
    score_d: Optional[float] = None
    score_t: Optional[float] = None
    score_s: Optional[float] = None
    score_h: Optional[float] = None
    score_r: Optional[float] = None
    # Real sub-classification when detection_class == "vehicle" (see
    # shared.constants.VehicleSubtype). None for every other detection
    # class or when the underlying YOLO class wasn't a recognized vehicle
    # subtype — never fabricated.
    vehicle_subtype: Optional[str] = None
    # Real watchlist face-match result (edge/detection/face_recognition.py's
    # LBPH recognizer). All None whenever no match was found — never a
    # fabricated "no match" claim about a face that wasn't even checked.
    face_match_person_id: Optional[str] = None
    face_match_person_name: Optional[str] = None
    face_match_confidence: Optional[float] = None
    face_match_status: Optional[str] = None
    watchlist_person_id: Optional[str] = None
    watchlist_label: Optional[str] = None
    recognition_score: Optional[float] = None
    recognition_threshold: Optional[float] = None
    recognition_engine: Optional[str] = None
    face_quality_status: Optional[str] = None
    recognition_observation_count: Optional[int] = None
    face_bbox_json: Optional[str] = None
    lighting_state: Optional[str] = None
    mean_luminance: Optional[float] = None
    dark_pixel_ratio: Optional[float] = None
    enhancement_applied: Optional[bool] = None
    detection_method: Optional[str] = None
    motion_area: Optional[float] = None
    motion_persistence: Optional[int] = None
    
    # Phase 4 WP-3.3 Object Storage Metadata
    storage_provider: Optional[str] = None
    storage_status: Optional[str] = None
    content_hash: Optional[str] = None
    content_size: Optional[int] = None
    uploaded_at: Optional[datetime] = None
    failure_reason: Optional[str] = None

    # Enhanced ANPR metadata (added for Phase 3)
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    raw_plate_text: Optional[str] = None
    normalized_plate_text: Optional[str] = None
    localization_confidence: Optional[float] = None
    ocr_confidence: Optional[float] = None
    observations_count: Optional[int] = None
    processing_method: Optional[str] = None
    fusion_state: Optional[str] = None
    validation_status: Optional[str] = None
    watchlist_match: Optional[bool] = None

    # Phase 3 Step 2 Advanced Face Recognition metadata
    face_engine: Optional[str] = None
    similarity_score: Optional[float] = None
    recognition_state: Optional[str] = None
    # observation_count already exists as observations_count
    alignment_method: Optional[str] = None

    # Phase 3 Step 7 Behavioral Analytics metadata
    behavior_type: Optional[str] = None
    measured_trigger_values: Optional[dict] = None
    observation_window: Optional[float] = None
    why: Optional[str] = None

    # Bounding box coordinates (normalized 0.0 - 1.0)
    bbox_x: Optional[float] = None
    bbox_y: Optional[float] = None
    bbox_w: Optional[float] = None
    bbox_h: Optional[float] = None

    # Blockchain tracking (from associated Alert)
    blockchain_tx_id: Optional[str] = None
    blockchain_status: Optional[str] = None

    # Reliability Score Breakdown
    score_d: Optional[float] = None
    score_t: Optional[float] = None
    score_s: Optional[float] = None
    score_h: Optional[float] = None
    score_r: Optional[float] = None

    class Config:
        use_enum_values = True
        from_attributes = True


class VerificationResponse(BaseModel):
    event_id: str
    hash_valid: bool
    signature_valid: bool
    chain_valid: bool
    chain_status: Optional[str] = None
    detail: str
    calculated_hash: Optional[str] = None
    stored_hash: Optional[str] = None
    verified_at: datetime = Field(default_factory=datetime.utcnow)


class AlertResponse(BaseModel):
    alert_id: str
    event_id: str
    severity: Severity
    crosses_jurisdiction_boundary: bool
    command_id_issuing: str
    command_id_receiving: Optional[str]
    blockchain_status: BlockchainStatus
    blockchain_tx_id: Optional[str]
    acknowledged_at: Optional[datetime]
    acknowledged_by: Optional[str]
    created_at: Optional[datetime] = None
    # Sourced from the related Event (Alert.event, already a real ORM
    # relationship) — widened so the frontend's Alerts page can show real
    # camera/timing/type info instead of the placeholder title/description
    # text it used to always show for every alert, real or not.
    camera_id: Optional[str] = None
    event_type: Optional[str] = None
    zone_id: Optional[str] = None
    # True only when this alert exists because cross-camera corroboration
    # boosted a MEDIUM-severity event to escalation-eligible (see
    # backend/services/escalation.py) rather than the event's own severity
    # alone. False for every HIGH-severity alert, which needed no boost.
    escalated_via_corroboration: bool = False
    # Real terminal close action (SIH PS 26187 audit finding:
    # EventState.CLOSED was defined but never actually set anywhere).
    # closed_at/closed_by/resolution_notes are None until POST
    # /alerts/{id}/close is called. lifecycle_state is a real, queryable
    # EventState value (ALERTED/ACKNOWLEDGED/CLOSED).
    closed_at: Optional[datetime] = None
    closed_by: Optional[str] = None
    resolution_notes: Optional[str] = None
    lifecycle_state: str = "ALERTED"

    class Config:
        use_enum_values = True
        from_attributes = True


class AlertAcknowledgeRequest(BaseModel):
    receiving_command_id: str
    status: str = "ACKNOWLEDGED"
    notes: Optional[str] = None


class CameraStatusResponse(BaseModel):
    camera_id: str
    name: str
    location: str
    # Optional, not CameraHealthState — a camera that has never reported
    # health (no CameraHealth row yet) has no state to report. This used to
    # be a bare CameraHealthState with the endpoint passing the literal
    # string "UNKNOWN" as a fallback — an enum value that doesn't exist
    # (CameraHealthState is only OK/DEGRADED/FAILED) — which made
    # GET /cameras 500 for every real camera before any health had ever
    # been ingested for it, i.e. always, before POST /cameras/{id}/health
    # existed. Now: None means "no data yet", handled explicitly by the
    # frontend rather than crashing the endpoint.
    health_state: Optional[CameraHealthState]
    health_reason: Optional[HealthReason]
    last_health_check: Optional[datetime]
    fps_actual: Optional[float]
    fps_declared: Optional[float]
    drift_seconds: Optional[float]
    # blur_score / exposure_clip_fraction have always been computed and stored
    # on CameraHealth (edge/health/camera_health.py) but never exposed here —
    # widened so the frontend's Camera Health Matrix can show real values
    # instead of the mock BLUR INDEX / EXPOSURE fields it had before.
    blur_score: Optional[float]
    exposure_clip_fraction: Optional[float]
    # Real coordinates for the geospatial map — None for any camera
    # registered before this existed, or never given a location. The map
    # honestly omits such a camera rather than guessing a position.
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    class Config:
        use_enum_values = True
        from_attributes = True


class CameraLocationUpdate(BaseModel):
    """Request body for PUT /cameras/{id}/location."""
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)


class SyncStatusResponse(BaseModel):
    edge_device_id: str
    is_online: bool
    queued_events: int
    last_sync_at: Optional[datetime]
    last_event_at: Optional[datetime]


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: UserRole
    username: str

    class Config:
        use_enum_values = True


class UserCreate(BaseModel):
    username: str
    password: str
    role: UserRole = UserRole.OPERATOR

    class Config:
        use_enum_values = True


# ---------------------------------------------------------------------------
# WebSocket push message
# ---------------------------------------------------------------------------

class WSAlertMessage(BaseModel):
    """Pushed over WebSocket to dashboard on new alert."""
    type: str = "new_alert"
    alert: AlertResponse


# ---------------------------------------------------------------------------
# Pipeline performance metrics (architecture v4 §15)
# ---------------------------------------------------------------------------

class PipelineMetricsReport(BaseModel):
    """
    Request body for POST /system/metrics — the real shape
    edge/instrumentation/metrics.py's PipelineMetrics.summary() already
    produces, plus edge_device_id/timestamp added at report time
    (edge/main.py's _report_metrics). `frames`/`events` are the nested
    per-stage dicts as-is; not re-typed field-by-field here since the
    stage set is owned by PipelineMetrics.FRAME_STAGES/EVENT_STAGES, not
    this schema.
    """
    edge_device_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    uptime_seconds: float
    fps: float
    frames: dict
    events: dict
    alerts_generated: int = 0
    telemetry_produced: Optional[int] = None
    telemetry_dropped: Optional[int] = None
    telemetry_errors: Optional[int] = None
    cpu_percent: Optional[float] = None
    rss_mb: Optional[float] = None
    psutil_available: bool = False
    adaptive_gate: Optional[dict] = None


class PipelineMetricsResponse(BaseModel):
    edge_device_id: str
    timestamp: datetime
    uptime_seconds: float
    fps: float
    frames: dict
    events: dict
    alerts_generated: int
    telemetry_produced: Optional[int] = None
    telemetry_dropped: Optional[int] = None
    telemetry_errors: Optional[int] = None
    cpu_percent: Optional[float]
    rss_mb: Optional[float]
    psutil_available: bool
    adaptive_gate: Optional[dict] = None

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Watchlist (SIH PS 26187 — real facial recognition, not detection alone).
# See backend/models/orm.py's WatchlistPerson/WatchlistFaceImage docstrings
# and edge/detection/face_recognition.py for the full honest scope.
# ---------------------------------------------------------------------------

class WatchlistPersonCreate(BaseModel):
    """POST /watchlist body — registers a person with one real reference
    face photo (a face crop, not a full scene — base64-encoded JPEG)."""
    name: str
    notes: Optional[str] = None
    image_base64: str


class WatchlistPersonResponse(BaseModel):
    person_id: str
    name: str
    notes: Optional[str] = None
    is_active: bool
    created_at: datetime
    face_image_count: int


class WatchlistSyncEntry(BaseModel):
    """One entry of GET /watchlist/sync — real reference images, for the
    edge to train its local LBPH recognizer against. Not a precomputed
    embedding: LBPH trains on the labeled images directly."""
    person_id: str
    name: str
    image_base64_list: List[str]


class WatchlistSyncResponse(BaseModel):
    persons: List[WatchlistSyncEntry]


# ---------------------------------------------------------------------------
# External C2 integration (SIH PS 26187). See backend/models/orm.py's
# WebhookSubscription docstring and backend/services/webhook_delivery.py
# for the real delivery mechanism and its honest scope.
# ---------------------------------------------------------------------------

class WebhookSubscriptionCreate(BaseModel):
    name: str
    url: str
    min_severity: Severity = Severity.LOW


class WebhookSubscriptionResponse(BaseModel):
    subscription_id: str
    name: str
    url: str
    min_severity: Severity
    is_active: bool
    created_at: datetime
    last_delivery_at: Optional[datetime] = None
    last_delivery_status: Optional[str] = None
    last_delivery_error: Optional[str] = None


class WebhookAlertPayload(BaseModel):
    """Real, documented outbound payload — not any named external standard
    (CAP, STIX, etc.) this project has not actually implemented or
    verified compliance against. A deliberately simple, real JSON shape."""
    alert_id: str
    event_id: str
    severity: Severity
    event_type: Optional[str] = None
    camera_id: Optional[str] = None
    zone_id: Optional[str] = None
    detection_class: Optional[str] = None
    crosses_jurisdiction_boundary: bool
    escalated_via_corroboration: bool = False
    timestamp: datetime
    issuing_command_id: str


class EventExportResponse(BaseModel):
    """GET /integrations/events/export — real events for pull-based
    external consumers that don't accept inbound webhooks. Same real
    fields as EventResponse, deliberately not re-declared/duplicated:
    consumers get the same real EventResponse objects, paginated."""
    events: List[EventResponse]
    next_cursor: Optional[str] = None
