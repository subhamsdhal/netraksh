"""
NETRAKSH Backend — SQLAlchemy ORM models.
All models correspond 1:1 to the data schema in the architecture document (§25).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str] = mapped_column(String(256), nullable=False)
    rtsp_url: Mapped[Optional[str]] = mapped_column(String(512))
    public_key_pem: Mapped[Optional[str]] = mapped_column(Text)   # Ed25519 public key PEM
    # AES-256 evidence-encryption key (architecture v4 §10), wrapped via
    # backend/security/evidence_key_wrap.py before storage — never the raw key.
    evidence_key_wrapped: Mapped[Optional[str]] = mapped_column(Text)
    # Real coordinates for the geospatial map (Alerts page) — Optional
    # because most cameras registered before this existed have neither;
    # the map honestly omits a camera with no location rather than
    # guessing one.
    latitude: Mapped[Optional[float]] = mapped_column(Float)
    longitude: Mapped[Optional[float]] = mapped_column(Float)
    owning_command_id: Mapped[str] = mapped_column(String(64), nullable=False, default="COMMAND_A")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    health_records: Mapped[List["CameraHealth"]] = relationship(
        "CameraHealth", back_populates="camera", cascade="all, delete-orphan"
    )
    events: Mapped[List["Event"]] = relationship(
        "Event", back_populates="camera", cascade="all, delete-orphan"
    )
    zones: Mapped[List["Zone"]] = relationship(
        "Zone", back_populates="camera", cascade="all, delete-orphan"
    )
    keys: Mapped[List["CameraKey"]] = relationship(
        "CameraKey", back_populates="camera", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# CameraKey (Key Registry)
# ---------------------------------------------------------------------------

class CameraKey(Base):
    __tablename__ = "camera_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    kid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(32), default="ed25519")
    purpose: Mapped[str] = mapped_column(String(32), default="EVIDENCE_SIGNING")
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE") # ACTIVE, RETIRED, REVOKED
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="keys")


# ---------------------------------------------------------------------------
# CameraHealth
# ---------------------------------------------------------------------------

class CameraHealth(Base):
    __tablename__ = "camera_health"
    __table_args__ = (
        Index("ix_camera_health_camera_id_ts", "camera_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    health_state: Mapped[str] = mapped_column(String(16), nullable=False)   # OK/DEGRADED/FAILED
    health_reason: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    fps_actual: Mapped[Optional[float]] = mapped_column(Float)
    fps_declared: Mapped[Optional[float]] = mapped_column(Float)
    drift_seconds: Mapped[Optional[float]] = mapped_column(Float)
    blur_score: Mapped[Optional[float]] = mapped_column(Float)
    exposure_clip_fraction: Mapped[Optional[float]] = mapped_column(Float)
    frame_variance: Mapped[Optional[float]] = mapped_column(Float)

    camera: Mapped["Camera"] = relationship("Camera", back_populates="health_records")


# ---------------------------------------------------------------------------
# Zone (§2 correction)
# ---------------------------------------------------------------------------

class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(32), nullable=False)  # fence/checkpoint/verification/boundary
    polygon_json: Mapped[str] = mapped_column(Text, nullable=False)     # JSON list of {x,y} points
    owning_command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    adjacent_command_id: Mapped[Optional[str]] = mapped_column(String(64))  # non-null = boundary zone
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    camera: Mapped["Camera"] = relationship("Camera", back_populates="zones")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="zone")


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_camera_id_ts", "camera_id", "timestamp"),
        Index("ix_events_decision_state", "decision_state"),
        Index("ix_events_severity", "severity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), ForeignKey("cameras.id"), nullable=False)
    zone_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("zones.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # Source-video position in seconds. Nullable for live/legacy events where
    # the edge cannot provide a finite media clock.
    video_time: Mapped[Optional[float]] = mapped_column(Float)
    event_type: Mapped[Optional[str]] = mapped_column(String(64))
    detection_class: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    scene_condition: Mapped[str] = mapped_column(String(32), nullable=False)
    camera_health_state: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_state: Mapped[str] = mapped_column(String(16), nullable=False)
    decision_reason: Mapped[Optional[str]] = mapped_column(String(256))
    track_id: Mapped[Optional[int]] = mapped_column(Integer)
    severity: Mapped[Optional[str]] = mapped_column(String(16))
    direction: Mapped[Optional[str]] = mapped_column(String(32))
    rule: Mapped[Optional[str]] = mapped_column(String(64))
    rule_value: Mapped[Optional[float]] = mapped_column(Float)
    stream_id: Mapped[Optional[str]] = mapped_column(String(36))
    # Concrete inference/replay identity.  Nullable for legacy events whose
    # edge payload predates run-scoped telemetry.
    analysis_session_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    plate_text: Mapped[Optional[str]] = mapped_column(String(32))
    plate_confidence: Mapped[Optional[float]] = mapped_column(Float)
    raw_plate_text: Mapped[Optional[str]] = mapped_column(String(64))
    normalized_plate_text: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    localization_confidence: Mapped[Optional[float]] = mapped_column(Float)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(Float)
    observations_count: Mapped[Optional[int]] = mapped_column(Integer)
    processing_method: Mapped[Optional[str]] = mapped_column(String(128))
    fusion_state: Mapped[Optional[str]] = mapped_column(String(32))
    validation_status: Mapped[Optional[str]] = mapped_column(String(24))
    watchlist_match: Mapped[Optional[bool]] = mapped_column(Boolean)
    # Real sub-classification when detection_class == "vehicle" (see
    # shared.constants.VehicleSubtype) -- SIH PS 26187 asks for "vehicle
    # detection AND classification", not detection alone.
    vehicle_subtype: Mapped[Optional[str]] = mapped_column(String(32))
    # Real watchlist face-match result (edge/detection/face_recognition.py's
    # LBPH recognizer) -- None whenever no face was detected, no watchlist
    # was synced, or the detected face didn't match any enrolled person
    # closely enough (see that module's docstring for the real, disclosed
    # match threshold). Never fabricated -- an absent match is shown as an
    # absent match, not a false "no match" claim about a face that wasn't
    # even checked.
    face_match_person_id: Mapped[Optional[str]] = mapped_column(String(36))
    face_match_person_name: Mapped[Optional[str]] = mapped_column(String(128))
    face_match_confidence: Mapped[Optional[float]] = mapped_column(Float)
    face_match_status: Mapped[Optional[str]] = mapped_column(String(32))
    watchlist_person_id: Mapped[Optional[str]] = mapped_column(String(36))
    watchlist_label: Mapped[Optional[str]] = mapped_column(String(128))
    recognition_score: Mapped[Optional[float]] = mapped_column(Float)
    recognition_threshold: Mapped[Optional[float]] = mapped_column(Float)
    recognition_engine: Mapped[Optional[str]] = mapped_column(String(32))
    face_quality_status: Mapped[Optional[str]] = mapped_column(String(32))
    recognition_observation_count: Mapped[Optional[int]] = mapped_column(Integer)
    face_bbox_json: Mapped[Optional[str]] = mapped_column(Text)
    face_engine: Mapped[Optional[str]] = mapped_column(String(32))
    similarity_score: Mapped[Optional[float]] = mapped_column(Float)
    recognition_state: Mapped[Optional[str]] = mapped_column(String(32))
    alignment_method: Mapped[Optional[str]] = mapped_column(String(32))
    lighting_state: Mapped[Optional[str]] = mapped_column(String(32))
    mean_luminance: Mapped[Optional[float]] = mapped_column(Float)
    dark_pixel_ratio: Mapped[Optional[float]] = mapped_column(Float)
    enhancement_applied: Mapped[Optional[bool]] = mapped_column(Boolean)
    detection_method: Mapped[Optional[str]] = mapped_column(String(32))
    motion_area: Mapped[Optional[float]] = mapped_column(Float)
    motion_persistence: Mapped[Optional[int]] = mapped_column(Integer)
    evidence_clip_ref: Mapped[Optional[str]] = mapped_column(String(512))
    evidence_image_ref: Mapped[Optional[str]] = mapped_column(String(512))
    
    # Phase 4 WP-3.3 Object Storage Metadata
    storage_provider: Mapped[str] = mapped_column(String(32), default="local")
    object_key: Mapped[Optional[str]] = mapped_column(String(512))
    storage_status: Mapped[str] = mapped_column(String(32), default="CREATED")
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    content_size: Mapped[Optional[int]] = mapped_column(Integer)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    storage_version_id: Mapped[Optional[str]] = mapped_column(String(128))
    failure_reason: Mapped[Optional[str]] = mapped_column(String(256))
    
    # Bounding box coordinates (normalized 0.0 - 1.0)
    bbox_x: Mapped[Optional[float]] = mapped_column(Float)
    bbox_y: Mapped[Optional[float]] = mapped_column(Float)
    bbox_w: Mapped[Optional[float]] = mapped_column(Float)
    bbox_h: Mapped[Optional[float]] = mapped_column(Float)
    
    score_d: Mapped[Optional[float]] = mapped_column(Float)
    score_t: Mapped[Optional[float]] = mapped_column(Float)
    score_s: Mapped[Optional[float]] = mapped_column(Float)
    score_h: Mapped[Optional[float]] = mapped_column(Float)
    score_r: Mapped[Optional[float]] = mapped_column(Float)
    
    edge_device_id: Mapped[Optional[str]] = mapped_column(String(64))
    sequence_number: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    synced_from_edge: Mapped[bool] = mapped_column(Boolean, default=False)

    # Cross-camera corroboration (backend/services/cross_camera.py) — real,
    # computed post-ingest from real camera coordinates and real event
    # timestamps. Never retroactively changes decision_state/confidence on
    # this (already tamper-evident-signed) row; see that module's docstring
    # for why. All nullable: most events will have no plausible corroborating
    # sighting, and that absence is itself real information, not a gap to
    # fill with a fabricated 0.
    corroboration_score: Mapped[Optional[float]] = mapped_column(Float)
    corroborated_by_event_id: Mapped[Optional[str]] = mapped_column(String(36))
    corroboration_distance_m: Mapped[Optional[float]] = mapped_column(Float)
    corroboration_delta_t_s: Mapped[Optional[float]] = mapped_column(Float)
    corroboration_t_expected_s: Mapped[Optional[float]] = mapped_column(Float)
    corroboration_sigma_s: Mapped[Optional[float]] = mapped_column(Float)
    corroborating_camera_id: Mapped[Optional[str]] = mapped_column(String(36))
    corroboration_status: Mapped[Optional[str]] = mapped_column(String(32))
    
    # Phase 3 Step 8: Multi-Camera Appearance Signals
    appearance_similarity: Mapped[Optional[float]] = mapped_column(Float)
    representation_type: Mapped[Optional[str]] = mapped_column(String(64))

    camera: Mapped["Camera"] = relationship("Camera", back_populates="events")
    zone: Mapped[Optional["Zone"]] = relationship("Zone", back_populates="events")
    evidence_package: Mapped[Optional["EvidencePackage"]] = relationship(
        "EvidencePackage", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    alert: Mapped[Optional["Alert"]] = relationship(
        "Alert", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# EvidencePackage
# ---------------------------------------------------------------------------

class EvidencePackage(Base):
    __tablename__ = "evidence_packages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), unique=True, nullable=False)
    schema_version: Mapped[Optional[str]] = mapped_column(String(32))
    crypto_version: Mapped[Optional[str]] = mapped_column(String(32))
    kid: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    digital_signature: Mapped[str] = mapped_column(Text, nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(64))
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    verified_ok: Mapped[Optional[bool]] = mapped_column(Boolean)
    hash_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    signature_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    chain_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    chain_status: Mapped[Optional[str]] = mapped_column(String(16))
    raw_package_json: Mapped[Optional[str]] = mapped_column(Text)   # full evidence package JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    event: Mapped["Event"] = relationship("Event", back_populates="evidence_package")


# ---------------------------------------------------------------------------
# EvidenceChain — server-side chain tracking
# ---------------------------------------------------------------------------

class EvidenceChain(Base):
    __tablename__ = "evidence_chain"
    __table_args__ = (
        Index("ix_evidence_chain_edge_seq", "edge_device_id", "sequence_number"),
        Index("ix_evidence_chain_edge_analysis_seq", "edge_device_id", "analysis_session_id", "sequence_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    edge_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null is reserved for immutable legacy evidence profiles.  New crypto-v2
    # evidence stores the signed, per-replay analysis identity here.
    analysis_session_id: Mapped[Optional[str]] = mapped_column(String(36))
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_hash: Mapped[Optional[str]] = mapped_column(String(64))
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    kid: Mapped[Optional[str]] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    chain_valid: Mapped[Optional[bool]] = mapped_column(Boolean)
    chain_status: Mapped[Optional[str]] = mapped_column(String(16))


# ---------------------------------------------------------------------------
# Alert — with escalation eligibility fields (§2 correction)
# ---------------------------------------------------------------------------

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_event_id", "event_id"),
        Index("ix_alerts_blockchain_status", "blockchain_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), unique=True, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    # Escalation eligibility (§1.3 — both must be true for blockchain submission)
    crosses_jurisdiction_boundary: Mapped[bool] = mapped_column(Boolean, default=False)
    command_id_issuing: Mapped[str] = mapped_column(String(64), nullable=False)
    command_id_receiving: Mapped[Optional[str]] = mapped_column(String(64))
    # Blockchain fields
    blockchain_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    blockchain_tx_id: Mapped[Optional[str]] = mapped_column(String(256))
    blockchain_submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Acknowledgement
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(64))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # True only when this alert exists BECAUSE of cross-camera corroboration
    # boosting a MEDIUM-severity event to escalation-eligible (see
    # backend/services/escalation.py) — never set for a HIGH-severity event,
    # which was always escalation-eligible on its own. Recorded so this is
    # visible/auditable, not a silent behavior change.
    escalated_via_corroboration: Mapped[bool] = mapped_column(Boolean, default=False)
    # Real terminal close action -- shared.constants.EventState defines
    # ACKNOWLEDGED and CLOSED as the lifecycle's final two states, but
    # before this, nothing anywhere ever actually set CLOSED (confirmed by
    # grep, not assumed -- see docs/LIMITATIONS.md). Additive, alongside
    # the existing acknowledged_at/acknowledged_by (which stay unchanged) --
    # closing requires an alert to already be acknowledged first, a real
    # lifecycle constraint enforced in backend/api/alerts.py.
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    closed_by: Mapped[Optional[str]] = mapped_column(String(64))
    resolution_notes: Mapped[Optional[str]] = mapped_column(Text)
    # A real, queryable EventState value (shared.constants.EventState) --
    # ALERTED at creation, ACKNOWLEDGED/CLOSED at those real actions. Makes
    # the enum's own docstring claim ("ACKNOWLEDGED/CLOSED are set later by
    # command-center operator action") genuinely true, rather than only
    # implied by acknowledged_at/closed_at being non-null.
    lifecycle_state: Mapped[str] = mapped_column(String(16), default="ALERTED")

    event: Mapped["Event"] = relationship("Event", back_populates="alert")
    acknowledgements: Mapped[List["AlertAcknowledgement"]] = relationship(
        "AlertAcknowledgement", back_populates="alert", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# AlertAcknowledgement
# ---------------------------------------------------------------------------

class AlertAcknowledgement(Base):
    __tablename__ = "alert_acknowledgements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    alert_id: Mapped[str] = mapped_column(String(36), ForeignKey("alerts.id"), nullable=False)
    receiving_command_id: Mapped[str] = mapped_column(String(64), nullable=False)
    ack_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)    # ACKNOWLEDGED/DISMISSED
    blockchain_tx_id: Mapped[Optional[str]] = mapped_column(String(256))
    blockchain_status: Mapped[str] = mapped_column(String(16), default="PENDING")
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alert: Mapped["Alert"] = relationship("Alert", back_populates="acknowledgements")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)    # ADMIN/OPERATOR/AUDITOR
    command_id: Mapped[str] = mapped_column(String(64), default="COMMAND_A")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime)

    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# SyncQueue — server-side view of edge sync state
# ---------------------------------------------------------------------------

class SyncQueue(Base):
    __tablename__ = "sync_queue"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    edge_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sync_status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    queued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    error_message: Mapped[Optional[str]] = mapped_column(Text)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_id_ts", "user_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[str]] = mapped_column(String(36))
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[Optional["User"]] = relationship("User", back_populates="audit_logs")


# ---------------------------------------------------------------------------
# AnalysisTelemetrySnapshot — durable latest lifecycle state
# ---------------------------------------------------------------------------

class AnalysisTelemetrySnapshot(Base):
    """Latest real telemetry for a camera/stream, retained across restarts."""
    __tablename__ = "analysis_telemetry"
    __table_args__ = (
        Index("ix_analysis_telemetry_camera_stream", "camera_id", "stream_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    camera_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stream_id: Mapped[Optional[str]] = mapped_column(String(36))
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    video_time: Mapped[Optional[float]] = mapped_column(Float)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frame_width: Mapped[Optional[int]] = mapped_column(Integer)
    frame_height: Mapped[Optional[int]] = mapped_column(Integer)
    analysis_state: Mapped[Optional[str]] = mapped_column(String(16))
    tracks_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# PipelineMetricsSnapshot — real edge performance telemetry (architecture v4 §15)
# ---------------------------------------------------------------------------

class PipelineMetricsSnapshot(Base):
    """
    A periodic real performance snapshot from one edge device
    (edge/instrumentation/metrics.py's PipelineMetrics.summary(), pushed by
    edge/main.py's _report_metrics()). Before this table existed, this real,
    already-measured data (perf_counter() latency per stage, measured FPS,
    real psutil CPU/RSS) was written only to a local JSON file on the edge
    device and never reached the backend at all — the Performance dashboard
    page had nothing to show. Same "compute it for real, then actually wire
    it somewhere" gap this project has closed before (camera health was the
    same shape of problem).

    Per-stage breakdowns (frames/events) are stored as JSON rather than
    exploded into individual columns, since the stage set itself is owned by
    PipelineMetrics.FRAME_STAGES/EVENT_STAGES in edge code — this table
    shouldn't need a migration if that set ever changes.
    """
    __tablename__ = "pipeline_metrics"
    __table_args__ = (
        Index("ix_pipeline_metrics_edge_ts", "edge_device_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    edge_device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    uptime_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    fps: Mapped[float] = mapped_column(Float, nullable=False)
    alerts_generated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cumulative counters from EdgePipeline's bounded telemetry producer.
    # Nullable preserves the truth for snapshots stored before these were
    # transported to the backend.
    telemetry_produced: Mapped[Optional[int]] = mapped_column(Integer)
    telemetry_dropped: Mapped[Optional[int]] = mapped_column(Integer)
    telemetry_errors: Mapped[Optional[int]] = mapped_column(Integer)
    cpu_percent: Mapped[Optional[float]] = mapped_column(Float)
    rss_mb: Mapped[Optional[float]] = mapped_column(Float)
    psutil_available: Mapped[bool] = mapped_column(Boolean, default=False)
    frames_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    events_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    adaptive_gate_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ---------------------------------------------------------------------------
# Watchlist (SIH PS 26187 — "support facial recognition", not detection
# alone). Real, honestly-scoped: OpenCV's classical LBPH face recognizer
# (edge/detection/face_recognition.py), trained on admin-enrolled reference
# photos — NOT a production-grade deep-learning FRS. Sensitive to lighting/
# pose/expression, no liveness detection, not appropriate for legal or
# large-scale 1:N identification. See docs/LIMITATIONS.md for the full
# honest account of scope.
# ---------------------------------------------------------------------------

class WatchlistPerson(Base):
    __tablename__ = "watchlist_persons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # Semi-colon separated list of known aliases / alternate identities.
    # Stored as a plain string rather than a child table for simplicity;
    # the UI splits on ";" for display.
    aliases: Mapped[Optional[str]] = mapped_column(String(512))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Threat classification: ELEVATED | SEVERE | CRITICAL
    # Displayed as Yellow / Orange / Red in the watchlist grid.
    threat_level: Mapped[Optional[str]] = mapped_column(
        String(16), default="ELEVATED"
    )
    # Category / role (e.g. "Smuggler", "Suspected militant", "Person of interest")
    category: Mapped[Optional[str]] = mapped_column(String(64))
    # Last known location as a free-text string ("Sector 7, Post Alpha")
    last_known_location: Mapped[Optional[str]] = mapped_column(String(256))
    # Timestamp of last observed sighting (updated when a face-match event fires)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Linked camera_id where last sighting occurred
    last_seen_camera_id: Mapped[Optional[str]] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    face_images: Mapped[List["WatchlistFaceImage"]] = relationship(
        "WatchlistFaceImage", back_populates="person", cascade="all, delete-orphan"
    )


class WatchlistFaceImage(Base):
    """
    One real, admin-uploaded reference photo for a watchlist person. LBPH
    (unlike embedding-based recognizers) trains directly on labeled face
    images rather than precomputed vectors, so the raw image itself is what
    gets synced to and trained on at the edge (GET /watchlist/sync) —
    multiple images per person, ideally varied lighting/angle, real-world
    improve real match robustness against this recognizer's own real
    limitations.
    """
    __tablename__ = "watchlist_face_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("watchlist_persons.id"), nullable=False)
    # Base64-encoded JPEG bytes of a cropped face image — small enough
    # (single face crops, not full frames) to store inline rather than as a
    # file path, and simpler to sync to the edge over the existing REST API.
    image_base64: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    person: Mapped["WatchlistPerson"] = relationship("WatchlistPerson", back_populates="face_images")


# ---------------------------------------------------------------------------
# External C2 integration (SIH PS 26187 — "support integration with
# existing command and control systems"). Real, admin-registered outbound
# webhook subscriptions — this dashboard is itself a real command center
# (real events, real alerts, real evidence), but nothing before this let a
# genuinely EXTERNAL system (a different agency's own C2 platform) receive
# real-time notifications. See backend/services/webhook_delivery.py for the
# real delivery mechanism and its honest scope.
# ---------------------------------------------------------------------------

class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    # Only alerts at or above this severity are delivered — LOW is the
    # real default (deliver everything) so a subscriber must opt IN to
    # filtering, not silently miss real alerts by an unset default.
    min_severity: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Real, observable delivery health — the same "don't just claim it
    # works, show the real last outcome" posture as this project's chain-
    # integrity/sync-status panels.
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_delivery_status: Mapped[Optional[str]] = mapped_column(String(16))  # "SUCCESS" | "FAILED"
    last_delivery_error: Mapped[Optional[str]] = mapped_column(String(512))


# ---------------------------------------------------------------------------
# Phase 4 WP-2: Edge Identity Model
# ---------------------------------------------------------------------------

class EdgeIdentity(Base):
    """
    Edge device identity and revocation registry.
    Ties the edge device securely to its mTLS client certificate.
    """
    __tablename__ = "edge_identities"

    edge_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    certificate_fingerprint: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    certificate_serial: Mapped[Optional[str]] = mapped_column(String(128))
    
    # Status: ACTIVE, SUSPENDED, REVOKED, EXPIRED, UNKNOWN
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    device_metadata: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
