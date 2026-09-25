# Phase 4 WP-3.3: Evidence Lifecycle

## 1. Lifecycle States
The object storage architecture introduces an explicit state machine for evidence binaries, decoupled from the core Event metadata lifecycle (which transitions through Triaged, Escalated, etc.).

Evidence Binaries transition through the following `storage_status` states:

1. **NULL**: Legacy state (pre-migration) or incomplete Stage 1 ingest.
2. **UPLOADING**: Transient state immediately after metadata ingest (Stage 1) is accepted, before the binary (Stage 2) has successfully persisted to the backend Object Storage.
3. **AVAILABLE**: Terminal success state indicating the binary was uploaded, its `content_hash` successfully verified against the edge's calculation, and the object is durably stored in the backend.
4. **FAILED**: Terminal error state indicating a mismatch in binary hash, a transmission failure, an oversized upload, or a backend storage provider error.
5. **MISSING**: Post-migration state indicating that an event's metadata exists, but the corresponding physical binary could not be found locally during migration, or was deleted from the backend store.

## 2. Decoupling Event and Evidence Availability
By separating metadata (Event) from bulky binaries (Evidence):
- Important analytical context (timestamps, zones, severity) becomes instantly available on the dashboard, even if the bulky binary takes longer to transfer on a constrained edge network.
- `EVENT_AVAILABLE` is distinct from `EVIDENCE_AVAILABLE`. Dashboards can indicate an event occurred while showing a loading state for the evidence.

## 3. Orphan Reconciliation
The two-stage sync ensures no edge data is discarded on transient failures. If Stage 1 (metadata) succeeds but Stage 2 (binary) fails:
- The edge SQLite queue retains the event as `QUEUED`, resulting in a retry on the next sync cycle.
- The backend idempotently handles the retried metadata ingest (Stage 1), ignoring it as a duplicate, and accepts the subsequent binary upload (Stage 2) when it succeeds.

## 4. Retention & Archival
With `storage_provider` abstraction (e.g., S3), evidence retention and archival policies (e.g., transition to S3 Glacier) can be configured natively at the cloud provider level, reducing database bloat and operational costs. The backend application simply references the deterministic `object_key`.
