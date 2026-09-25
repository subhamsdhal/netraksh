# Phase 4 WP-4.5: Tracing

## Status
**DESIGN READY / NOT DEPLOYED**

## Architecture Design
To maintain strict failure-isolation, OpenTelemetry collector dependencies are NOT enforced during runtime execution.

Future implementation boundaries mapped for trace spans:
1. `edge.ingest`: Starts at frame capture.
2. `edge.inference`: Object detection + Task evaluation.
3. `edge.sync`: Evidence transmission across mTLS.
4. `backend.ingest`: Verification of Ed25519 payload.
5. `backend.storage`: Object storage persistence.
6. `webhook.delivery`: Downstream integration broadcast.

Currently, traces are simulated via `correlation_id` injection in the standard JSON Logging stack.
