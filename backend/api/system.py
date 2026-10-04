"""
NETRAKSH — System / health / sync status router.
GET  /health           — liveness (no auth)
GET  /system/status    — system overview (authenticated)
GET  /sync/status      — edge sync queue status
POST /system/metrics   — periodic real edge performance telemetry
GET  /system/metrics   — latest performance snapshot per edge device
"""

import asyncio
import base64
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response as PlainResponse
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import (
    Alert, Camera, Event, PipelineMetricsSnapshot, SyncQueue, AuditLog,
    CameraHealth, AnalysisTelemetrySnapshot, AnalysisRunSummary,
)
from backend.security.auth import require_edge_auth
from backend.security.auth import require_any_role
from backend.services.video_storage import promote_active_session
from shared.schemas import PipelineMetricsReport, PipelineMetricsResponse, LiveTelemetryPayload, TelemetryFramePayload
from backend.api.websocket import broadcast_telemetry

logger = logging.getLogger(__name__)
router = APIRouter(tags=["system"])


@router.get("/metrics")
async def prometheus_metrics():
    """
    Prometheus metrics endpoint.
    Returns metrics in the Prometheus text exposition format.
    This endpoint does NOT require authentication so that a Prometheus server
    running in the same network segment can scrape it without a bearer token.
    In production, restrict access at the network level (firewall, VPC).
    """
    return PlainResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@router.get("/health")
async def health_check():
    """Liveness probe — no authentication required."""
    return {
        "status": "ok",
        "service": "NETRAKSH Command Center",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
    }


@router.get("/ready")
async def readiness_check(db: Session = Depends(get_db)):
    """Readiness probe — verifies required dependencies (DB + storage config) are reachable."""
    checks = {}
    ready = True

    # 1. Database
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        logger.error(f"Readiness check: DB unavailable: {e}")
        checks["database"] = "unavailable"
        ready = False

    # 2. Storage configuration (not a live ping — just proves config is present)
    storage_provider = settings.OBJECT_STORAGE_PROVIDER or "local"
    checks["storage_provider"] = storage_provider
    storage_durable = storage_provider == "s3" and bool(settings.OBJECT_STORAGE_BUCKET)
    if storage_provider == "s3" and not settings.OBJECT_STORAGE_BUCKET:
        checks["storage"] = "misconfigured_missing_bucket"
        ready = False
    elif storage_provider == "local":
        checks["storage"] = "non_durable_local"
    else:
        checks["storage"] = "configured"
    checks["storage_durable"] = storage_durable

    if not ready:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "checks": checks},
        )

    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat(),
        **checks,
    }


@router.get("/system/diagnostic")
async def diagnostic_snapshot(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Safe aggregate operational diagnostic view.
    Never exposes passwords, keys, tokens, or raw evidence payloads.
    """
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        db_status = "HEALTHY"
    except Exception as e:
        logger.error(f"Diagnostic DB check failed: {e}")
        db_status = "FAILED"

    # Count cameras by health state
    total_cameras = db.query(Camera).count()
    degraded = db.query(CameraHealth).filter(CameraHealth.health_state == "DEGRADED").count()
    failed = db.query(CameraHealth).filter(CameraHealth.health_state == "FAILED").count()
    healthy = total_cameras - (degraded + failed)

    # Sync status
    queued = db.query(SyncQueue).filter(SyncQueue.sync_status == "QUEUED").count()
    failed_sync = db.query(SyncQueue).filter(SyncQueue.sync_status == "FAILED").count()

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "backend_readiness": "HEALTHY" if db_status == "HEALTHY" else "FAILED",
        "database_status": db_status,
        "cameras": {
            "total": total_cameras,
            "healthy": healthy,
            "degraded": degraded,
            "failed": failed,
        },
        "sync_queue": {
            "queued": queued,
            "failed": failed_sync,
        }
    }



@router.get("/system/status")
async def system_status(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    camera_count = db.query(Camera).filter(Camera.is_active == True).count()
    event_count = db.query(Event).count()
    alert_count = db.query(Alert).count()
    pending_acks = db.query(Alert).filter(Alert.acknowledged_at.is_(None)).count()
    queued_sync = db.query(SyncQueue).filter(SyncQueue.sync_status == "QUEUED").count()

    return {
        "status": "operational",
        "command_id": settings.COMMAND_ID,
        "blockchain_mode": settings.BLOCKCHAIN_MODE,
        "blockchain_label": settings.BLOCKCHAIN_MOCK_LABEL if settings.BLOCKCHAIN_MODE == "mock" else "FABRIC",
        "cameras_active": camera_count,
        "total_events": event_count,
        "total_alerts": alert_count,
        "pending_acknowledgements": pending_acks,
        "queued_for_sync": queued_sync,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/system/capabilities")
async def system_capabilities(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Safe runtime configuration/capability facts for authenticated UI clients."""
    storage_provider = settings.OBJECT_STORAGE_PROVIDER or "local"
    storage_durable = storage_provider == "s3" and bool(settings.OBJECT_STORAGE_BUCKET)
    return {
        "command_id": settings.COMMAND_ID,
        "registered_camera_count": db.query(Camera).filter(Camera.is_active == True).count(),
        "corroboration": {
            "temporal_spatial": True,
            "cross_camera_reid": settings.CROSS_CAMERA_REID != "disabled",
        },
        "evidence": {
            "cryptographic_chain": True,
            "storage_provider": storage_provider,
            "durable_storage": storage_durable,
            "status": "CONFIGURED" if storage_durable else "BLOCKED_NON_DURABLE_LOCAL",
        },
        "blockchain": {
            "mode": settings.BLOCKCHAIN_MODE,
            "label": settings.BLOCKCHAIN_MOCK_LABEL if settings.BLOCKCHAIN_MODE == "mock" else "FABRIC",
            "simulated": settings.BLOCKCHAIN_MODE == "mock",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/sync/status")
async def sync_status(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    # Read the latest metric snapshot to get the real edge queue depth
    latest_metrics = (
        db.query(PipelineMetricsSnapshot)
        .order_by(desc(PipelineMetricsSnapshot.timestamp))
        .first()
    )
    
    metrics_events = latest_metrics.events_json if latest_metrics and latest_metrics.events_json else {}
    edge_queued = int(metrics_events.get("queue_depth", 0) or 0)

    # For 'synced' and 'failed', we can either use the metrics or keep using the backend DB 
    # to show the overall backend-to-chain status as well, but the instruction specifically 
    # said: "Propagate the true edge queue depth... UI must show the edge's actual outbound queue size."
    backend_queued = db.query(SyncQueue).filter(SyncQueue.sync_status == "QUEUED").count()
    backend_failed = db.query(SyncQueue).filter(SyncQueue.sync_status == "FAILED").count()
    backend_synced = db.query(SyncQueue).filter(SyncQueue.sync_status == "SYNCED").count()
    last_sync = db.query(SyncQueue).order_by(desc(SyncQueue.queued_at)).first()
    metric_sent = metrics_events.get("sent", {})
    metric_failed = metrics_events.get("failed", {})
    metric_sent_count = int(metric_sent.get("count", 0) if isinstance(metric_sent, dict) else metric_sent or 0)
    metric_failed_count = int(metric_failed.get("count", 0) if isinstance(metric_failed, dict) else metric_failed or 0)
    synced = max(metric_sent_count, backend_synced)
    failed = max(metric_failed_count, backend_failed)
    queued = max(edge_queued, backend_queued)
    metrics_has_sync_activity = bool(edge_queued or metric_sent_count or metric_failed_count)
    # A worker process snapshot is not evidence that any event/evidence sync
    # occurred.  Keep the control plane IDLE until a queue row or a non-zero
    # queue/sent/failed counter proves real synchronization activity.
    has_activity = bool(last_sync or queued or synced or failed)
    return {
        "queued": queued,
        "edge_queued": edge_queued,
        "backend_queued": backend_queued,
        "synced": synced,
        "failed": failed,
        "has_activity": has_activity,
        "last_activity_at": (
            latest_metrics.timestamp.isoformat()
            if latest_metrics and metrics_has_sync_activity
            else (last_sync.queued_at.isoformat() if last_sync else None)
        ),
        "observed_at": datetime.utcnow().isoformat(),
    }


@router.get("/system/verify-chain")
async def verify_chain(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    from backend.models.orm import EvidencePackage
    evidence_list = db.query(EvidencePackage).order_by(EvidencePackage.id).all()
    if not evidence_list:
        return {"is_valid": True, "message": "No evidence on chain yet."}
    
    invalid_count = sum(1 for ev in evidence_list if ev.chain_status == 'INVALID')
    pending_count = sum(1 for ev in evidence_list if ev.chain_status == 'PENDING')
    
    if invalid_count > 0:
        return {"is_valid": False, "message": f"{invalid_count} block(s) failed integrity verification. Chain compromised."}
    elif pending_count > 0:
        return {"is_valid": True, "message": f"Verified {len(evidence_list) - pending_count} blocks. {pending_count} blocks pending chain sync."}
    else:
        return {"is_valid": True, "message": f"Successfully verified {len(evidence_list)} blocks across all edge hash chains."}


_telemetry_requests = 0
_latest_telemetry: Dict[str, Dict[str, Any]] = {}
_latest_frames: Dict[str, OrderedDict] = {}
# WebSocket telemetry is deliberately batched, so an authenticated browser can
# receive a snapshot a few inference ticks after its paired JPEG was posted.
# Keep a small bounded identity cache long enough to bridge that normal delay;
# the frontend still rejects any frame whose session/frame/count headers do not
# exactly match the telemetry snapshot.
_MAX_FRAMES_PER_CAMERA = 64


def _telemetry_is_newer(current: Optional[dict], incoming: dict) -> bool:
    if current is None:
        return True
    current_session = current.get("analysis_session_id") or current.get("stream_id")
    incoming_session = incoming.get("analysis_session_id") or incoming.get("stream_id")
    if current_session != incoming_session:
        return float(incoming.get("processed_timestamp") or incoming.get("timestamp") or 0) > float(
            current.get("processed_timestamp") or current.get("timestamp") or 0
        )
    if current_session is None and incoming_session is None:
        return float(incoming.get("processed_timestamp") or incoming.get("timestamp") or 0) > float(
            current.get("processed_timestamp") or current.get("timestamp") or 0
        )
    current_frame = current.get("frame_index")
    incoming_frame = incoming.get("frame_index")
    if current_frame is not None and incoming_frame is not None and incoming_frame != current_frame:
        return int(incoming_frame) > int(current_frame)
    return int(incoming.get("sequence") or 0) > int(current.get("sequence") or 0)


_SUMMARY_FIELDS = (
    "frame_width", "frame_height", "person_count", "vehicle_count",
    "track_count", "scene_condition", "lighting_state", "detection_method",
)


def _record_run_summary(db: Session, payload: LiveTelemetryPayload) -> Optional[AnalysisRunSummary]:
    if not (payload.stream_id and payload.analysis_session_id and payload.analysis_generation is not None):
        return None
    observed_at = float(payload.processed_timestamp or payload.timestamp)
    summary = db.query(AnalysisRunSummary).filter(
        AnalysisRunSummary.analysis_session_id == payload.analysis_session_id,
    ).first()
    if summary is None:
        summary = AnalysisRunSummary(
            analysis_session_id=payload.analysis_session_id,
            camera_id=payload.camera_id,
            stream_id=payload.stream_id,
            analysis_generation=payload.analysis_generation,
            first_telemetry_at=observed_at,
            last_telemetry_at=observed_at,
        )
        db.add(summary)
    elif (summary.camera_id, summary.stream_id, summary.analysis_generation) != (
        payload.camera_id, payload.stream_id, payload.analysis_generation
    ):
        raise HTTPException(status_code=409, detail="analysis_session_id identity conflict")
    summary.last_telemetry_at = max(float(summary.last_telemetry_at), observed_at)
    if payload.frame_index is not None:
        summary.final_frame_index = payload.frame_index
    if payload.video_time is not None:
        summary.final_video_time = payload.video_time
    if payload.processing_fps is not None:
        summary.processing_fps = payload.processing_fps
    reported_source_fps = payload.source_fps if payload.source_fps is not None else payload.fps_declared
    if reported_source_fps is not None:
        summary.source_fps = reported_source_fps
    for field in _SUMMARY_FIELDS:
        value = getattr(payload, field)
        if value is not None:
            setattr(summary, field, value)
    if str(payload.analysis_state or "").upper() == "COMPLETED":
        summary.completed_at = observed_at
    return summary


def _completed_telemetry_view(db: Session, telemetry: dict, previous: Optional[dict] = None) -> dict:
    """Restore the final real sample behind a sparse EOF lifecycle marker."""
    if str(telemetry.get("analysis_state") or "").upper() != "COMPLETED":
        return telemetry
    analysis_session_id = telemetry.get("analysis_session_id")
    if not analysis_session_id:
        return telemetry
    summary = db.get(AnalysisRunSummary, analysis_session_id)
    if summary is None:
        return telemetry
    telemetry_identity = (
        telemetry.get("camera_id"),
        telemetry.get("stream_id"),
        telemetry.get("analysis_generation"),
    )
    summary_identity = (summary.camera_id, summary.stream_id, summary.analysis_generation)
    if telemetry_identity != summary_identity:
        return telemetry
    hydrated = dict(telemetry)
    summary_fields = {
        "frame_index": summary.final_frame_index,
        "video_time": summary.final_video_time,
        "processing_fps": summary.processing_fps,
        "source_fps": summary.source_fps,
        "frame_width": summary.frame_width,
        "frame_height": summary.frame_height,
        "person_count": summary.person_count,
        "vehicle_count": summary.vehicle_count,
        "track_count": summary.track_count,
        "scene_condition": summary.scene_condition,
        "lighting_state": summary.lighting_state,
        "detection_method": summary.detection_method,
    }
    for field, value in summary_fields.items():
        if value is not None:
            hydrated[field] = value
    final_frame_index = hydrated.get("frame_index")
    frame_key = (analysis_session_id, int(final_frame_index)) if final_frame_index is not None else None
    camera_frames = _latest_frames.get(str(telemetry.get("camera_id") or ""), {})
    hydrated["preview_available"] = bool(frame_key and frame_key in camera_frames)
    previous_frame_index = previous.get("frame_index") if previous else None
    previous_frame_key = (
        (analysis_session_id, int(previous_frame_index))
        if previous_frame_index is not None else None
    )
    previous_identity = (
        previous.get("camera_id"),
        previous.get("stream_id"),
        previous.get("analysis_generation"),
        previous.get("analysis_session_id"),
    ) if previous else None
    expected_identity = (*summary_identity, analysis_session_id)
    if not hydrated["preview_available"] and previous_identity == expected_identity \
            and previous_frame_key in camera_frames:
        # EOF may arrive as a sparse lifecycle marker one tick after the last
        # JPEG. Preserve that exact telemetry/image pair and apply only the
        # terminal lifecycle fields; never label a different frame as final.
        exact_sample = dict(previous)
        for field in ("analysis_state", "timestamp", "processed_timestamp", "sequence"):
            if telemetry.get(field) is not None:
                exact_sample[field] = telemetry[field]
        exact_sample["analysis_state"] = "COMPLETED"
        exact_sample["preview_available"] = True
        return exact_sample
    return hydrated


@router.post("/system/telemetry/frame", status_code=202)
async def post_telemetry_frame(
    payload: TelemetryFramePayload,
    edge_identity=Depends(require_edge_auth),
):
    """Keep a bounded set of exact analyzed JPEGs for authenticated viewers."""
    if edge_identity and edge_identity.edge_id != payload.camera_id:
        raise HTTPException(status_code=403, detail="Authenticated edge identity does not match camera_id")
    try:
        clean_jpeg = base64.b64decode(payload.clean_jpeg_base64, validate=True)
        annotated_jpeg = base64.b64decode(payload.annotated_jpeg_base64, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid analyzed-frame JPEG")
    if any(not jpeg.startswith(b"\xff\xd8") or len(jpeg) > 2_000_000 for jpeg in (clean_jpeg, annotated_jpeg)):
        raise HTTPException(status_code=400, detail="Invalid or oversized analyzed-frame JPEG")
    session_id = payload.analysis_session_id or ""
    frame_index = int(payload.frame_index or 0)
    camera_frames = _latest_frames.setdefault(payload.camera_id, OrderedDict())
    camera_frames[(session_id, frame_index)] = {
        "clean_jpeg": clean_jpeg,
        "annotated_jpeg": annotated_jpeg,
        "source_timestamp": payload.source_timestamp,
        "processed_timestamp": payload.processed_timestamp,
        "person_count": payload.person_count,
        "vehicle_count": payload.vehicle_count,
        "track_count": payload.track_count,
    }
    camera_frames.move_to_end((session_id, frame_index))
    while len(camera_frames) > _MAX_FRAMES_PER_CAMERA:
        camera_frames.popitem(last=False)
    return {"status": "ok"}


@router.get("/system/telemetry/frame/{camera_id}")
async def get_telemetry_frame(
    camera_id: str,
    analysis_session_id: str,
    frame_index: int,
    hud: bool = True,
    _user=Depends(require_any_role),
):
    frame = _latest_frames.get(camera_id, {}).get((analysis_session_id, frame_index))
    if frame is None:
        raise HTTPException(status_code=404, detail="Analyzed frame is no longer available")
    return PlainResponse(
        content=frame["annotated_jpeg"] if hud else frame["clean_jpeg"],
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "ETag": f'"{analysis_session_id}:{frame_index}:{int(hud)}"',
            "X-Analysis-Session": analysis_session_id,
            "X-Frame-Index": str(frame_index),
            "X-Person-Count": str(frame["person_count"]),
            "X-Vehicle-Count": str(frame["vehicle_count"]),
            "X-Track-Count": str(frame["track_count"]),
            # The dashboard is served from Vite (5173) while this image is
            # served by FastAPI (8443). Explicitly expose the coherence
            # contract so browser JavaScript can validate the paired sample.
            "Access-Control-Expose-Headers": (
                "ETag, X-Analysis-Session, X-Frame-Index, X-Person-Count, "
                "X-Vehicle-Count, X-Track-Count"
            ),
        },
    )

@router.post("/system/telemetry", status_code=202)
async def post_telemetry(
    payload: LiveTelemetryPayload,
    db: Session = Depends(get_db),
    edge_identity=Depends(require_edge_auth)
):
    """
    Ingest live track telemetry from the edge pipeline.
    This is an operational snapshot, kept in memory and broadcast to clients.
    Keeping the latest item per camera lets a browser reload restore the real
    PROCESSING/COMPLETED lifecycle without inventing status client-side.
    """
    if edge_identity and edge_identity.edge_id != payload.camera_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Authenticated edge identity does not match camera_id")

    global _telemetry_requests
    _telemetry_requests += 1
    if _telemetry_requests % 100 == 0:
        logger.info(f"[Telemetry] Received {_telemetry_requests} payloads from edge")
        
    telemetry = payload.model_dump()
    current = _latest_telemetry.get(payload.camera_id)
    if current is None:
        persisted_current = (
            db.query(AnalysisTelemetrySnapshot)
            .filter(AnalysisTelemetrySnapshot.camera_id == payload.camera_id)
            .order_by(desc(AnalysisTelemetrySnapshot.timestamp))
            .first()
        )
        if persisted_current is not None:
            current = {
                "stream_id": persisted_current.stream_id,
                "analysis_session_id": persisted_current.analysis_session_id,
                "timestamp": persisted_current.timestamp,
                "processed_timestamp": persisted_current.timestamp,
                "sequence": persisted_current.sequence,
            }
    if not _telemetry_is_newer(current, telemetry):
        return {"status": "ignored", "reason": "out_of_order"}
    # The control record becomes ACTIVE only after a telemetry packet from the
    # exact durable source and replay generation has been accepted. Timers and
    # stale generations must never advance the lifecycle.
    if (
        payload.stream_id
        and payload.analysis_session_id
        and payload.analysis_generation is not None
    ):
        promote_active_session(
            payload.camera_id,
            payload.stream_id,
            payload.analysis_generation,
            payload.analysis_session_id,
        )
    # Keep one durable latest snapshot per camera/session. This is intentionally
    # not a telemetry history table: it provides restart restoration without
    # turning high-frequency live telemetry into unbounded database growth.
    query = db.query(AnalysisTelemetrySnapshot).filter(
        AnalysisTelemetrySnapshot.camera_id == payload.camera_id,
    )
    if payload.stream_id is None:
        query = query.filter(AnalysisTelemetrySnapshot.stream_id.is_(None))
    else:
        query = query.filter(AnalysisTelemetrySnapshot.stream_id == payload.stream_id)
    snapshot = query.first()
    snapshot_values = {
        "camera_id": payload.camera_id,
        "stream_id": payload.stream_id,
        "analysis_session_id": payload.analysis_session_id,
        "analysis_generation": payload.analysis_generation,
        "frame_index": payload.frame_index,
        "timestamp": payload.timestamp,
        "video_time": payload.video_time,
        "sequence": payload.sequence,
        "frame_width": payload.frame_width,
        "frame_height": payload.frame_height,
        "analysis_state": payload.analysis_state,
        "tracks_json": [track.model_dump() for track in payload.tracks],
    }
    if snapshot is None:
        db.add(AnalysisTelemetrySnapshot(**snapshot_values))
    else:
        for key, value in snapshot_values.items():
            setattr(snapshot, key, value)
    _record_run_summary(db, payload)
    db.commit()
    telemetry = _completed_telemetry_view(db, telemetry, current)
    _latest_telemetry[payload.camera_id] = telemetry
    await broadcast_telemetry(telemetry)
    return {"status": "ok"}


@router.get("/system/telemetry/latest")
async def latest_telemetry(
    camera_id: Optional[str] = None,
    stream_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user=Depends(require_any_role),
    analysis_session_id: Optional[str] = None,
    analysis_generation: Optional[int] = None,
):
    """Return real last-seen telemetry snapshots matching the active context."""
    in_memory = [item for item in _latest_telemetry.values() if (
        (not camera_id or item.get("camera_id") == camera_id)
        # stream_id is the durable/source session used by dashboard scoping.
        # analysis_session_id identifies the concrete analyzed-frame generation
        # and must not be substituted here.
        and (not stream_id or item.get("stream_id") == stream_id)
        and (not analysis_session_id or item.get("analysis_session_id") == analysis_session_id)
        and (analysis_generation is None or item.get("analysis_generation") == analysis_generation)
    )]
    if in_memory:
        return sorted(
            (_completed_telemetry_view(db, item) for item in in_memory),
            key=lambda item: item.get("processed_timestamp") or item.get("timestamp") or 0,
            reverse=True,
        )

    query = db.query(AnalysisTelemetrySnapshot)
    if camera_id:
        query = query.filter(AnalysisTelemetrySnapshot.camera_id == camera_id)
    if stream_id:
        query = query.filter(AnalysisTelemetrySnapshot.stream_id == stream_id)
    if analysis_session_id:
        query = query.filter(AnalysisTelemetrySnapshot.analysis_session_id == analysis_session_id)
    if analysis_generation is not None:
        query = query.filter(AnalysisTelemetrySnapshot.analysis_generation == analysis_generation)
    persisted = query.order_by(desc(AnalysisTelemetrySnapshot.timestamp)).all()
    return [
        _completed_telemetry_view(db, {
            "camera_id": item.camera_id,
            "timestamp": item.timestamp,
            "video_time": item.video_time,
            "sequence": item.sequence,
            "frame_width": item.frame_width,
            "frame_height": item.frame_height,
            "stream_id": item.stream_id,
            "analysis_session_id": item.analysis_session_id,
            "analysis_state": item.analysis_state,
            "analysis_generation": item.analysis_generation,
            "frame_index": item.frame_index,
            "source_timestamp": None,
            "processed_timestamp": item.timestamp,
            "processing_fps": None,
            "expected_interval_ms": None,
            "raw_detection_count": None,
            "tracker_output_count": None,
            "person_count": None,
            "vehicle_count": None,
            "track_count": None,
            "active_track_ids": sorted({track.get("track_id") for track in (item.tracks_json or []) if track.get("track_id") is not None}),
            "tracker_output_ids": [track.get("track_id") for track in (item.tracks_json or []) if track.get("track_id") is not None],
            "raw_detections": [],
            "preview_available": False,
            "tracks": item.tracks_json or [],
        })
        for item in persisted
    ]


@router.get("/system/analysis-runs/{analysis_session_id}")
async def analysis_run_summary(
    analysis_session_id: str,
    camera_id: Optional[str] = None,
    stream_id: Optional[str] = None,
    analysis_generation: Optional[int] = None,
    db: Session = Depends(get_db),
    _user=Depends(require_any_role),
):
    query = db.query(AnalysisRunSummary).filter(
        AnalysisRunSummary.analysis_session_id == analysis_session_id,
    )
    if camera_id:
        query = query.filter(AnalysisRunSummary.camera_id == camera_id)
    if stream_id:
        query = query.filter(AnalysisRunSummary.stream_id == stream_id)
    if analysis_generation is not None:
        query = query.filter(AnalysisRunSummary.analysis_generation == analysis_generation)
    summary = query.one_or_none()
    if summary is None:
        raise HTTPException(status_code=404, detail="Run summary not recorded")
    return {column.name: getattr(summary, column.name) for column in AnalysisRunSummary.__table__.columns}


@router.post("/system/metrics", status_code=201)
async def report_metrics(
    payload: PipelineMetricsReport,
    db: Session = Depends(get_db),
    edge_identity = Depends(require_edge_auth),
):
    """
    Periodic real performance telemetry push from the edge
    (edge/main.py's EdgePipeline._report_metrics, every
    metrics_report_interval_seconds — default 10s).

    Before this endpoint existed, edge/instrumentation/metrics.py's real,
    perf_counter()-measured latency/FPS/CPU/RSS was written only to a local
    JSON file on the edge device (edge/data/metrics_*.json) and never
    reached the backend at all — there was nothing for a Performance
    dashboard page to show. This is what actually connects the two.
    """
    if edge_identity and edge_identity.edge_id != payload.edge_device_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Authenticated edge identity does not match edge_device_id")

    record = PipelineMetricsSnapshot(
        edge_device_id=edge_identity.edge_id if edge_identity else payload.edge_device_id,
        timestamp=payload.timestamp,
        uptime_seconds=payload.uptime_seconds,
        fps=payload.fps,
        frames_json=payload.frames,
        events_json=payload.events,
        alerts_generated=payload.alerts_generated,
        telemetry_produced=payload.telemetry_produced,
        telemetry_dropped=payload.telemetry_dropped,
        telemetry_errors=payload.telemetry_errors,
        cpu_percent=payload.cpu_percent,
        rss_mb=payload.rss_mb,
        psutil_available=payload.psutil_available,
        adaptive_gate_json=payload.adaptive_gate,
    )
    db.add(record)
    db.commit()

    from backend.api.websocket import broadcast_metrics
    asyncio.create_task(broadcast_metrics(_metrics_to_response(record).model_dump(mode="json")))

    return {"edge_device_id": payload.edge_device_id, "fps": payload.fps}


@router.get("/system/metrics", response_model=List[PipelineMetricsResponse])
async def list_latest_metrics(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    The single latest snapshot per distinct edge device that has ever
    reported — real "current status of every known edge process", the
    same "one row per known X" shape as GET /cameras.
    """
    device_ids = [row[0] for row in db.query(PipelineMetricsSnapshot.edge_device_id).distinct().all()]
    latest = []
    for device_id in device_ids:
        snap = (
            db.query(PipelineMetricsSnapshot)
            .filter(PipelineMetricsSnapshot.edge_device_id == device_id)
            .order_by(desc(PipelineMetricsSnapshot.timestamp))
            .first()
        )
        if snap:
            latest.append(_metrics_to_response(snap))
    return latest


@router.get("/system/metrics/history", response_model=List[PipelineMetricsResponse])
async def metrics_history(
    edge_device_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """Recent snapshots for one edge device, oldest first — for a trend line."""
    rows = (
        db.query(PipelineMetricsSnapshot)
        .filter(PipelineMetricsSnapshot.edge_device_id == edge_device_id)
        .order_by(desc(PipelineMetricsSnapshot.timestamp))
        .limit(min(limit, 500))
        .all()
    )
    return [_metrics_to_response(r) for r in reversed(rows)]


def _metrics_to_response(snap: PipelineMetricsSnapshot) -> PipelineMetricsResponse:
    return PipelineMetricsResponse(
        edge_device_id=snap.edge_device_id,
        timestamp=snap.timestamp,
        uptime_seconds=snap.uptime_seconds,
        fps=snap.fps,
        frames=snap.frames_json,
        events=snap.events_json,
        alerts_generated=snap.alerts_generated,
        telemetry_produced=snap.telemetry_produced,
        telemetry_dropped=snap.telemetry_dropped,
        telemetry_errors=snap.telemetry_errors,
        cpu_percent=snap.cpu_percent,
        rss_mb=snap.rss_mb,
        psutil_available=snap.psutil_available,
        adaptive_gate=snap.adaptive_gate_json,
    )

@router.get("/api/nodes/health")
async def nodes_health(
    db: Session = Depends(get_db),
    _user = Depends(require_any_role),
):
    """
    Consolidated operational health of all registered sensors (Phase 6).
    Aggregates CameraHealth and PipelineMetricsSnapshot.
    """
    cameras = db.query(Camera).filter(Camera.is_active == True).all()
    results = []
    
    for cam in cameras:
        # Get latest health record
        latest_health = (
            db.query(CameraHealth)
            .filter(CameraHealth.camera_id == cam.id)
            .order_by(desc(CameraHealth.timestamp))
            .first()
        )
        
        # Get latest metrics snapshot matching this camera's edge_device_id. 
        # (Assuming edge_device_id maps 1:1 to camera_id for this demo, or we can just fetch metrics by camera_id if they are the same)
        # The schema uses edge_device_id. For demo, edge_device_id == camera_id typically.
        latest_metrics = (
            db.query(PipelineMetricsSnapshot)
            .filter(PipelineMetricsSnapshot.edge_device_id == cam.id)
            .order_by(desc(PipelineMetricsSnapshot.timestamp))
            .first()
        )
        
        results.append({
            "camera_id": cam.id,
            "name": cam.name,
            "health_state": latest_health.health_state if latest_health else "UNKNOWN",
            # Missing measurements are not zero measurements.  Consumers use
            # null together with last_ping freshness to render N/A/OFFLINE.
            "uptime_seconds": latest_metrics.uptime_seconds if latest_metrics else None,
            "cpu_percent": latest_metrics.cpu_percent if latest_metrics else None,
            "fps": latest_metrics.fps if latest_metrics else None,
            "last_ping": (latest_metrics.timestamp.isoformat() + "Z") if latest_metrics else ((latest_health.timestamp.isoformat() + "Z") if latest_health else None),
        })
        
    return results
