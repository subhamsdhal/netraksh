"""
NETRAKSH Edge — Store-and-Forward Sync Client.
Implements offline-first operation: buffers events locally in SQLite,
uploads them in priority order on reconnection.

Key properties:
  - Events are NEVER lost even if backend is unreachable.
  - On reconnect: events are synced in (severity DESC, sequence_number ASC)
    order (architecture v4 §10) — a HIGH-severity event queued behind older
    LOW-severity ones syncs first once bandwidth returns. This does NOT
    affect hash-chain integrity: the chain (edge/evidence/packager.py) is
    a strictly sequential, append-only local ledger tied together by each
    record's embedded `previous_hash`, verified independently of arrival
    order at the backend — chain order and network delivery order are two
    different things, and only the former needs to be strictly sequential.
  - SIMULATE_OFFLINE=true env var forces offline mode for demo.
  - Batch size is configurable (SYNC_BATCH_SIZE env var).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from typing import List, Optional, Tuple

import httpx

from shared.constants import ErrorCategory
from shared.schemas import EventCreateRequest, EvidencePackage

logger = logging.getLogger(__name__)

_QUEUE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sequence_number INTEGER NOT NULL UNIQUE,
    event_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    queued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt TEXT,
    error TEXT,
    severity_rank INTEGER NOT NULL DEFAULT 0
);
"""

# Split from table creation: the priority index references severity_rank,
# which must exist BEFORE this runs — for a pre-v4 database, that column is
# added by _migrate_add_severity_rank_if_missing() between the table script
# and this one, not before it (CREATE TABLE IF NOT EXISTS is a no-op against
# an existing table, so the column would otherwise not exist yet here).
_QUEUE_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_queue_status ON sync_queue(status, sequence_number);
CREATE INDEX IF NOT EXISTS idx_queue_priority ON sync_queue(status, severity_rank, sequence_number);
"""

# HIGH syncs before MEDIUM before LOW; an unset/unrecognized severity sorts
# last of all — hand-picked ordering, not itself a calibrated value (there's
# nothing to calibrate here, it's a strict ranking, not a threshold).
_SEVERITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def severity_rank(severity) -> int:
    """Maps a Severity enum, its string value, or None to a sortable rank.
    Unrecognized/missing severity ranks below every known level (0)."""
    if severity is None:
        return 0
    key = severity.value if hasattr(severity, "value") else str(severity)
    return _SEVERITY_RANK.get(key, 0)


class SyncClient:
    """
    Edge-side sync client.
    Handles offline buffering and ordered reconnect upload.
    """

    def __init__(
        self,
        edge_device_id: str,
        backend_url: str,
        db_path: str,
        auth_token: str,
        batch_size: int = 50,
        retry_interval_seconds: float = 30.0,
        ca_cert_path: Optional[str] = None,
        client_cert_path: Optional[str] = None,
        client_key_path: Optional[str] = None,
    ):
        import re
        if not edge_device_id or not re.match(r"^[A-Za-z0-9_-]+$", edge_device_id):
            raise ValueError(f"Invalid edge_device_id '{edge_device_id}': must contain only alphanumeric characters, dashes, and underscores.")

        self.edge_device_id = edge_device_id
        self.backend_url = backend_url.rstrip("/")
        self.db_path = db_path
        self.auth_token = auth_token
        self.batch_size = int(os.environ.get("SYNC_BATCH_SIZE", str(batch_size)))
        self.retry_interval = float(os.environ.get("SYNC_INTERVAL_SECONDS", str(retry_interval_seconds)))
        self.simulate_offline = os.environ.get("SIMULATE_OFFLINE", "").lower() == "true"
        self._ca_cert = ca_cert_path
        self._client_cert = (client_cert_path, client_key_path) if client_cert_path else None

        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_db()
        self._is_online = False
        self._running = True

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.executescript(_QUEUE_TABLE_SCHEMA)
            self._migrate_add_severity_rank_if_missing(conn)
            conn.executescript(_QUEUE_INDEX_SCHEMA)

    @staticmethod
    def _migrate_add_severity_rank_if_missing(conn: sqlite3.Connection) -> None:
        """
        A sync_queue.db created before architecture v4 §10 won't have the
        severity_rank column — CREATE TABLE IF NOT EXISTS is a no-op against
        an existing table, so this ALTER TABLE guard is what actually adds
        it to a pre-existing database rather than silently failing to order
        by a column that doesn't exist there.
        """
        cols = [row[1] for row in conn.execute("PRAGMA table_info(sync_queue)").fetchall()]
        if "severity_rank" not in cols:
            logger.info("[Sync] Migrating sync_queue: adding severity_rank column")
            conn.execute("ALTER TABLE sync_queue ADD COLUMN severity_rank INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def enqueue(self, package: EvidencePackage, sequence_number: int) -> None:
        """Add a packaged event to the local outbox (thread-safe)."""
        request = EventCreateRequest(
            evidence_package=package,
            edge_device_id=self.edge_device_id,
            sequence_number=sequence_number,
        )
        payload = request.model_dump_json()
        rank = severity_rank(package.severity)
        with self._get_conn() as conn:
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO sync_queue
                       (sequence_number, event_id, payload_json, queued_at, status, severity_rank)
                       VALUES (?,?,?,?,?,?)""",
                    (sequence_number, package.event_id, payload, datetime.utcnow().isoformat(), "QUEUED", rank),
                )
            except Exception as exc:
                logger.error(f"[Sync] Enqueue failed for seq={sequence_number}: {exc}")

        logger.debug(f"[Sync] Enqueued event {package.event_id} (seq={sequence_number}, severity_rank={rank})")

    def get_queue_depth(self) -> int:
        with self._get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status='QUEUED'").fetchone()
        return row[0] if row else 0

    def get_diagnostics(self) -> dict:
        """
        Read-only diagnostic snapshot of the sync queue.
        NEVER mutates the queue or blocks fairness.
        """
        with self._get_conn() as conn:
            queued = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status='QUEUED'").fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status='FAILED'").fetchone()[0]
            synced = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status='SYNCED'").fetchone()[0]
            
            oldest_queued_row = conn.execute(
                "SELECT sequence_number, queued_at FROM sync_queue WHERE status='QUEUED' ORDER BY queued_at ASC LIMIT 1"
            ).fetchone()
            
            oldest_seq = oldest_queued_row[0] if oldest_queued_row else None
            oldest_queued_at = oldest_queued_row[1] if oldest_queued_row else None
            
            severity_dist = {}
            for row in conn.execute("SELECT severity_rank, COUNT(*) FROM sync_queue WHERE status='QUEUED' GROUP BY severity_rank").fetchall():
                severity_dist[row[0]] = row[1]
                
            last_failed_row = conn.execute(
                "SELECT error, last_attempt FROM sync_queue WHERE status IN ('FAILED', 'QUEUED') AND error IS NOT NULL ORDER BY last_attempt DESC LIMIT 1"
            ).fetchone()
            last_error = last_failed_row[0] if last_failed_row else None
            
            last_synced_row = conn.execute(
                "SELECT last_attempt FROM sync_queue WHERE status='SYNCED' ORDER BY last_attempt DESC LIMIT 1"
            ).fetchone()
            last_synced_at = last_synced_row[0] if last_synced_row else None
            
            total_retries = conn.execute("SELECT SUM(attempts) FROM sync_queue WHERE attempts > 1").fetchone()[0] or 0
            
        return {
            "queued_count": queued,
            "failed_count": failed,
            "synced_count": synced,
            "severity_distribution": severity_dist,
            "oldest_sequence": oldest_seq,
            "oldest_queued_at": oldest_queued_at,
            "last_error": last_error,
            "last_synced_at": last_synced_at,
            "total_retries": total_retries,
            "is_online": self.is_online
        }

    def sync_once(self) -> dict:
        """
        Attempt one sync cycle: fetch pending, upload in order.
        Returns a status dict.
        """
        if self.simulate_offline:
            logger.info("[Sync] SIMULATE_OFFLINE=true — skipping upload")
            return {"status": "simulated_offline", "queued": self.get_queue_depth()}

        pending = self._fetch_pending()
        if not pending:
            return {"status": "nothing_to_sync", "queued": 0}

        logger.info(f"[Sync] Uploading {len(pending)} queued events to {self.backend_url}")
        successes = 0
        failures = 0

        for row_id, seq_num, event_id, payload_json in pending:
            success, is_permanent, error = self._upload(payload_json, seq_num)
            self._mark(row_id, success, error, is_permanent=is_permanent)
            if success:
                successes += 1
            else:
                failures += 1
                if is_permanent:
                    logger.warning(f"[Sync] Upload permanently failed at seq={seq_num} (Error: {error}) — skipping item but continuing batch")
                    continue
                else:
                    # Stop batch on first transient failure — inherited tradeoff.
                    # Retries next cycle.
                    logger.warning(f"[Sync] Upload transiently failed at seq={seq_num} (Error: {error}) — stopping batch")
                    break

        self._is_online = failures == 0
        return {
            "status": "synced" if failures == 0 else "partial",
            "uploaded": successes,
            "failed": failures,
            "remaining": self.get_queue_depth(),
        }

    def stop(self) -> None:
        """Signal the background sync loop to terminate."""
        self._running = False
        logger.info("[Sync] Stop requested. Sync loop will exit after current sleep/batch.")

    def run_sync_loop(self) -> None:
        """Background sync loop — runs indefinitely until stopped."""
        logger.info(f"[Sync] Background sync loop started (interval={self.retry_interval}s)")
        while self._running:
            try:
                result = self.sync_once()
                if result.get("uploaded", 0) > 0:
                    logger.info(f"[Sync] Result: {result}")
            except Exception as exc:
                logger.error(f"[Sync] Unexpected error in sync loop: {exc}")
            time.sleep(self.retry_interval)

    def _fetch_pending(self) -> list:
        """
        Priority-ordered (architecture v4 §10) with Bounded Fairness:
        For batch_size >= 2, reserves 1 slot for the absolute oldest QUEUED record
        (by queued_at ASC, sequence_number ASC) to prevent starvation of lower
        priority events. The remaining slots use strict priority 
        (severity_rank DESC, sequence_number ASC).
        """
        if self.batch_size <= 1:
            prio_limit = self.batch_size
            fair_limit = 0
        else:
            prio_limit = self.batch_size - 1
            fair_limit = 1

        with self._get_conn() as conn:
            prio_rows = conn.execute(
                """SELECT id, sequence_number, event_id, payload_json
                   FROM sync_queue
                   WHERE status='QUEUED'
                   ORDER BY severity_rank DESC, sequence_number ASC
                   LIMIT ?""",
                (prio_limit,),
            ).fetchall()

            if fair_limit > 0:
                prio_ids = [r[0] for r in prio_rows]
                if prio_ids:
                    placeholders = ",".join("?" for _ in prio_ids)
                    fair_rows = conn.execute(
                        f"""SELECT id, sequence_number, event_id, payload_json
                            FROM sync_queue
                            WHERE status='QUEUED' AND id NOT IN ({placeholders})
                            ORDER BY queued_at ASC, sequence_number ASC
                            LIMIT ?""",
                        prio_ids + [fair_limit],
                    ).fetchall()
                else:
                    fair_rows = conn.execute(
                        """SELECT id, sequence_number, event_id, payload_json
                           FROM sync_queue
                           WHERE status='QUEUED'
                           ORDER BY queued_at ASC, sequence_number ASC
                           LIMIT ?""",
                        (fair_limit,),
                    ).fetchall()
            else:
                fair_rows = []

        return prio_rows + fair_rows
    def _upload(self, payload_json: str, seq_num: int) -> tuple[bool, bool, Optional[str]]:
        """Upload a single event to the backend in two stages. Returns (success, is_permanent, error_message)."""
        import json
        import hashlib
        
        try:
            print(f"DEBUG: STARTING UPLOAD seq_num={seq_num}")
            payload_dict = json.loads(payload_json)
            ep_dict = payload_dict.get("evidence_package", {})
            event_id = ep_dict.get("event_id")
            evidence_clip_ref = ep_dict.get("evidence_clip_ref")
        except json.JSONDecodeError:
            return False, True, f"[{ErrorCategory.EVIDENCE_ERROR.value}] Failed to decode payload_json"

        try:
            # PHASE 4 WP-2: Enforce strict TLS. verify=False is FORBIDDEN.
            verify: object = self._ca_cert if self._ca_cert else True
            if verify is False:
                raise ValueError("Strict TLS enforcement: verify=False is forbidden")
                
            cert = self._client_cert
            headers = {"Content-Type": "application/json"}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"
                
            # STEP 1: Upload Metadata
            with httpx.Client(verify=verify, cert=cert, timeout=30.0) as client:
                response = client.post(
                    f"{self.backend_url}/events",
                    content=payload_json,
                    headers=headers,
                )
            if response.status_code not in (200, 201):
                # 408/425/429 are client-visible but transient conditions.
                # Marking a rate-limited evidence event FAILED permanently
                # loses real detections during bursts instead of retrying
                # after the server's window clears.
                transient_client_statuses = {408, 425, 429}
                is_permanent = (
                    400 <= response.status_code < 500
                    and response.status_code not in transient_client_statuses
                )
                category = (
                    ErrorCategory.BACKEND_4XX.value
                    if is_permanent
                    else ErrorCategory.NETWORK_TRANSIENT.value
                )
                return False, is_permanent, f"[{category}] Metadata HTTP {response.status_code}: {response.text[:200]}"
                
            # STEP 2: Upload Evidence Binary (WP-3.3)
            if evidence_clip_ref and os.path.exists(evidence_clip_ref):
                try:
                    with open(evidence_clip_ref, "rb") as f:
                        binary_data = f.read()
                        
                    binary_hash = hashlib.sha256(binary_data).hexdigest()
                    files = {
                        "file": (os.path.basename(evidence_clip_ref), binary_data, "application/octet-stream")
                    }
                    data = {
                        "expected_hash": binary_hash
                    }
                    
                    # We do not send Content-Type header manually here; httpx sets it for multipart/form-data
                    auth_headers = {}
                    if self.auth_token:
                        auth_headers["Authorization"] = f"Bearer {self.auth_token}"
                        
                    with httpx.Client(verify=verify, cert=cert, timeout=60.0) as client:
                        ev_response = client.post(
                            f"{self.backend_url}/events/{event_id}/evidence",
                            data=data,
                            files=files,
                            headers=auth_headers,
                        )
                    if ev_response.status_code not in (200, 201):
                        logger.error(f"[Sync] Evidence upload failed for {event_id}: HTTP {ev_response.status_code}")
                        transient_client_statuses = {408, 425, 429}
                        is_permanent = (
                            400 <= ev_response.status_code < 500
                            and ev_response.status_code not in transient_client_statuses
                        )
                        category = (
                            ErrorCategory.BACKEND_4XX.value
                            if is_permanent
                            else ErrorCategory.NETWORK_TRANSIENT.value
                        )
                        return False, is_permanent, f"[{category}] Evidence HTTP {ev_response.status_code}: {ev_response.text[:200]}"
                except Exception as e:
                    logger.error(f"[Sync] Failed to read or upload evidence file {evidence_clip_ref} for {event_id}: {e}")
                    return False, False, f"[{ErrorCategory.CAMERA_READ_ERROR.value}] Evidence file error: {str(e)}"
            elif evidence_clip_ref:
                logger.warning(f"[Sync] Evidence file {evidence_clip_ref} for event {event_id} not found locally.")
                # We do not fail the upload loop if the physical file is permanently missing from the edge,
                # otherwise the queue would jam forever. The backend will reconcile this as MISSING.
                
            return True, False, None
            
        except httpx.ConnectError as exc:
            return False, False, f"[{ErrorCategory.NETWORK_TRANSIENT.value}] Connection refused — backend may be offline: {exc}"
        except Exception as exc:
            return False, False, f"[{ErrorCategory.UNKNOWN.value}] {str(exc)}"

    def _mark(self, row_id: int, success: bool, error: Optional[str], is_permanent: bool = False) -> None:
        if success:
            status = "SYNCED"
        elif is_permanent:
            status = "FAILED"
        else:
            status = "QUEUED"  # Keep QUEUED so it retries
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE sync_queue
                   SET status=?, attempts=attempts+1, last_attempt=?, error=?
                   WHERE id=?""",
                (status, datetime.utcnow().isoformat(), error, row_id),
            )

    @property
    def is_online(self) -> bool:
        return self._is_online and not self.simulate_offline

    def set_simulate_offline(self, value: bool) -> None:
        """Allow demo script to toggle offline mode at runtime."""
        self.simulate_offline = value
        logger.info(f"[Sync] simulate_offline set to {value}")
