# NETRAKSH — Phase 4 WP-3.2 SQLite Baseline Forensic Audit

## Overview
This document audits the edge SQLite offline buffer (`sync_queue.db`) implementation before attempting encryption in WP-3.2. 

## Storage Artifacts
- **Database Path:** Configured via `db_path` (e.g., `edge_data/sync_queue.db`)
- **Initialization:** Handled in `edge/sync/sync_client.py` via `_init_db()`.
- **Table:** `sync_queue` (id, sequence_number, event_id, payload_json, queued_at, status, attempts, last_attempt, error, severity_rank).
- **Indexes:** `idx_queue_status`, `idx_queue_priority`.

## Operations
- **Writes:** `enqueue()` inserts events with a `QUEUED` status and specific `severity_rank`.
- **Reads:** `_fetch_pending()` selects pending events prioritized by `severity_rank DESC`, `sequence_number ASC`.
- **Status Transitions:** Events transition from `QUEUED` to `SYNCED` upon HTTP success. Failures retain `QUEUED` and increment the `attempts` counter.
- **Priority/Ordering:** Strict multi-key priority ordering ensuring critical events transmit before routine events.
- **Payloads:** Cryptographic evidence (signatures, hashes, `kid`) are serialized into the `payload_json` field.
- **Crash Recovery:** Standard SQLite durability with implicit WAL/journal semantics based on environment defaults.

## Encryption Coverage Requirements
Any encryption layer MUST cover:
1. The primary database file (`sync_queue.db`).
2. Write-Ahead Logs (`sync_queue.db-wal`) and Shared Memory (`sync_queue.db-shm`).
3. Rollback journals (`sync_queue.db-journal`).
4. Any temp files spawned during SQLite operations.

## Verdict
The underlying structure handles high-value cryptographic payloads (`EvidencePackage`) asynchronously. While robust in logic, it relies on standard `sqlite3` without transparent file-level encryption.
