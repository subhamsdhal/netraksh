"""Monitor the Camera 1 edge only while it owns a real active analysis.

The Camera 1 detector processes a long finite source on Free compute. An
outbound heartbeat from the edge does not itself count as inbound activity at
the edge web service. This bounded, read-only probe has an operational purpose:
verify that the worker endpoint remains reachable during a matching live run.
It never probes an idle or completed Camera 1, nor Camera 2.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from backend.database.session import SessionLocal
from backend.models.orm import AnalysisWorkerLease

logger = logging.getLogger(__name__)

CAMERA_ID = "cam-border-01"
PROBE_INTERVAL_SECONDS = 180
LEASE_FRESH_SECONDS = 30


def lease_is_active(lease: AnalysisWorkerLease | None, *, now: float) -> bool:
    return bool(
        lease is not None
        and lease.phase == "RUNNING"
        and lease.analysis_session_id
        and lease.stream_id
        and lease.analysis_generation is not None
        and 0 <= now - lease.last_heartbeat_at <= LEASE_FRESH_SECONDS
    )


def camera1_has_active_worker() -> bool:
    db = SessionLocal()
    try:
        lease = db.get(AnalysisWorkerLease, CAMERA_ID)
        return lease_is_active(lease, now=time.time())
    finally:
        db.close()


async def monitor_camera1_active_analysis() -> None:
    """One GET /health per three minutes, only during a fresh Camera 1 run."""
    while True:
        await asyncio.sleep(PROBE_INTERVAL_SECONDS)
        url = os.environ.get("EDGE_WAKE_URL_CAM_BORDER_01", "").strip().rstrip("/")
        if not url:
            continue
        try:
            active = await asyncio.to_thread(camera1_has_active_worker)
            if not active:
                continue
            timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(f"{url}/health")
            logger.info(
                "[Camera1Liveness] active-run health probe status=%d",
                response.status_code,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Never log the configured URL, request, or response body.
            logger.warning(
                "[Camera1Liveness] active-run health probe unavailable error=%s",
                type(exc).__name__,
            )
