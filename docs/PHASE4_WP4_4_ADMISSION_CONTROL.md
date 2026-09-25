# Phase 4 WP-4.4: Admission Control

## StreamAdmissionController

Admission control guarantees that an edge node is never pushed beyond its physical or configured limits by misconfiguration or unexpected camera allocations. 

Before a new camera ingestion thread/process is spawned, the central controller must request admission via `request_admission()`.

### Hard Limits
Admission is rejected outright if the node has reached `MAX_ACTIVE_STREAMS`. This value defaults to 4 and prevents unbounded capacity assumptions.

### State-Based Admission
Admission decisions vary based on the current Resource State and the requested Stream Priority (`CRITICAL`, `HIGH`, `NORMAL`, `LOW`).

- **CRITICAL State:** Rejects all new streams EXCEPT `CRITICAL` priority streams, which are admitted as `ACCEPT_DEGRADED` to force capacity sharing.
- **DEGRADED State:** Rejects `NORMAL` and `LOW` streams. Admits `HIGH`/`CRITICAL` streams as `ACCEPT_DEGRADED`.
- **WARNING State:** Rejects `LOW` priority streams. Admits others as `ACCEPT`.
- **NORMAL State:** Accepts all streams.
