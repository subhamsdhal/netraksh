"""Durable, exact-run edge ownership and conservative stale-run reconciliation."""
from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from backend.models.orm import AnalysisRunSummary, AnalysisWorkerLease
from backend.security.auth import audit
from backend.services.video_storage import complete_active_session, interrupt_active_session

logger = logging.getLogger(__name__)

# A network partition must not immediately revoke a worker that is still
# analyzing. A newly registered idle process is stronger evidence, but still
# requires the original run's accepted telemetry to have stopped.
REPLACEMENT_GRACE_SECONDS = 45.0
LEASE_EXPIRY_SECONDS = 180.0
MISSING_LEASE_GRACE_SECONDS = 300.0


def interruption_reason(
    control: dict[str, Any],
    lease: AnalysisWorkerLease | None,
    summary: AnalysisRunSummary | None,
    *,
    now: float,
) -> str | None:
    if not control or str(control.get("analysis_state") or "").upper() not in {"WAKING", "ACTIVE"}:
        return None
    if str(control.get("scenario") or "").lower() != "normal" or summary is None:
        return None
    if summary.completed_at is not None or summary.interrupted_at is not None:
        return None
    identity = (
        str(control.get("session_id") or ""),
        int(control.get("analysis_generation") or 0),
        str(control.get("latest_analysis_session_id") or ""),
    )
    if identity != (summary.stream_id, summary.analysis_generation, summary.analysis_session_id):
        return None
    last_real_sample = float(summary.last_telemetry_at or 0)
    if lease is None:
        return "worker_lease_missing" if now - last_real_sample > MISSING_LEASE_GRACE_SECONDS else None
    if (lease.phase == "FAILED_EOF"
            and (lease.stream_id, lease.analysis_generation, lease.analysis_session_id) == identity
            and now - last_real_sample > REPLACEMENT_GRACE_SECONDS):
        return "completion_not_persisted"
    same_worker_run = (
        lease.stream_id,
        lease.analysis_generation,
        lease.analysis_session_id,
    ) == identity and lease.phase in {"STARTING", "RUNNING", "FINALIZING"}
    if same_worker_run:
        if now - float(lease.last_heartbeat_at) > LEASE_EXPIRY_SECONDS \
                and now - last_real_sample > LEASE_EXPIRY_SECONDS:
            return "worker_lease_expired"
        return None
    if lease.phase == "IDLE" and now - last_real_sample > REPLACEMENT_GRACE_SECONDS:
        # A boot recorded on the historical run is stronger than arrival
        # ordering: delayed telemetry may reach Postgres after replacement.
        if summary.worker_boot_id and summary.worker_boot_id != lease.boot_id:
            return "edge_instance_terminated"
        if summary.worker_boot_id == lease.boot_id and lease.last_heartbeat_at > last_real_sample:
            return "worker_exited_during_analysis"
        # Pre-lease runs have no historical boot ID. A newly booted idle edge
        # plus the grace period is the only safe legacy ownership proof.
        if summary.worker_boot_id is None and float(lease.registered_at) > last_real_sample:
            return "edge_instance_terminated"
    return None


def reconcile_stale_run(
    db: Session,
    camera_id: str,
    control: dict[str, Any] | None,
    *,
    now: float | None = None,
) -> dict[str, Any] | None:
    """Settle only an exact, incomplete run after durable ownership proof.

    The run summary and tracking samples remain untouched except for explicit
    interruption metadata. The source control stays usable for REANALYZE.
    """
    if not control or not control.get("latest_analysis_session_id"):
        return control
    observed_at = time.time() if now is None else now
    lease = db.get(AnalysisWorkerLease, camera_id)
    summary = db.get(AnalysisRunSummary, control["latest_analysis_session_id"])
    if summary is not None and summary.completed_at is not None and summary.interrupted_at is None \
            and (summary.camera_id, summary.stream_id, summary.analysis_generation) == (
                camera_id, control.get("session_id"), int(control.get("analysis_generation") or 0),
            ) and summary.tracking_sample_count and summary.final_frame_index is not None \
            and observed_at - summary.completed_at >= 10:
        # The edge's genuine terminal telemetry and durable frame timeline are
        # enough to recover a lost EOF control acknowledgement. Never infer
        # completion from a worker exit or from elapsed wall time alone.
        recovered = complete_active_session(
            camera_id, summary.stream_id, summary.analysis_generation, {
                "latest_analysis_session_id": summary.analysis_session_id,
                "final_frame_index": summary.final_frame_index,
                "video_time": summary.final_video_time,
                "video_time_updated_at": observed_at,
            },
        )
        if recovered is not None:
            logger.warning(
                "[WorkerLease] recovered acknowledged EOF camera_id=%s generation=%s run_id=%s final_frame=%s",
                camera_id, summary.analysis_generation, summary.analysis_session_id, summary.final_frame_index,
            )
            audit(
                db, "ANALYSIS_COMPLETION_RECOVERED", resource_type="analysis_generation",
                resource_id=f"{camera_id}:{summary.analysis_generation}",
                detail=f"camera_id={camera_id}; analysis_session_id={summary.analysis_session_id}; final_frame={summary.final_frame_index}",
            )
            return recovered
    reason = interruption_reason(control, lease, summary, now=observed_at)
    if reason is None:
        return control
    settled = interrupt_active_session(
        camera_id, control["session_id"], int(control["analysis_generation"]),
        reason=reason, analysis_session_id=summary.analysis_session_id,
    )
    if settled is None:
        return control
    summary.interrupted_at = observed_at
    summary.interruption_reason = reason
    logger.warning(
        "[WorkerLease] interrupted stale run camera_id=%s generation=%s run_id=%s reason=%s last_frame=%s",
        camera_id, summary.analysis_generation, summary.analysis_session_id,
        reason, summary.final_frame_index,
    )
    audit(
        db, "ANALYSIS_INTERRUPTED", resource_type="analysis_generation",
        resource_id=f"{camera_id}:{summary.analysis_generation}",
        detail=(f"camera_id={camera_id}; analysis_session_id={summary.analysis_session_id}; "
                f"reason={reason}; last_frame={summary.final_frame_index}"),
    )
    db.commit()
    return settled


def record_heartbeat(db: Session, payload: dict[str, Any], *, now: float | None = None) -> AnalysisWorkerLease:
    observed_at = time.time() if now is None else now
    camera_id = payload["camera_id"]
    lease = db.get(AnalysisWorkerLease, camera_id)
    if lease is None:
        lease = AnalysisWorkerLease(camera_id=camera_id, registered_at=observed_at)
        db.add(lease)
    elif lease.boot_id != payload["boot_id"]:
        # A late request from a terminated/rolling-over process cannot reclaim
        # ownership from a newer process. Both times are edge wall-clock UTC.
        if float(payload["worker_started_at"]) <= float(lease.worker_started_at):
            return lease
        lease.registered_at = observed_at
        logger.warning(
            "[WorkerLease] process replaced camera_id=%s old_boot=%s new_boot=%s",
            camera_id, lease.boot_id, payload["boot_id"],
        )
    lease.boot_id = payload["boot_id"]
    lease.instance_id = payload.get("instance_id")
    lease.worker_started_at = float(payload["worker_started_at"])
    lease.last_heartbeat_at = observed_at
    lease.phase = payload["phase"]
    lease.analysis_session_id = payload.get("analysis_session_id")
    lease.stream_id = payload.get("stream_id")
    lease.analysis_generation = payload.get("analysis_generation")
    lease.last_frame_index = payload.get("last_frame_index")
    lease.last_video_time = payload.get("last_video_time")
    if lease.analysis_session_id:
        summary = db.get(AnalysisRunSummary, lease.analysis_session_id)
        if summary is not None and (
            summary.camera_id, summary.stream_id, summary.analysis_generation,
        ) == (camera_id, lease.stream_id, lease.analysis_generation):
            summary.worker_boot_id = lease.boot_id
            summary.worker_instance_id = lease.instance_id
            summary.worker_started_at = lease.worker_started_at
            summary.last_worker_heartbeat = observed_at
    db.commit()
    return lease
