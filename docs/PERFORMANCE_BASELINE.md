# NETRAKSH Performance Baseline

This document establishes the post-Phase 2 performance and latency baseline. These measurements validate that the security and reliability hardening measures did not introduce unacceptable overhead, and serve as the standard for Phase 3 (Advanced AI) performance budgets.

## End-to-End Metrics (Unit & Integration Tests)

| Metric | Target Budget | Measured (Phase 2) | Status |
|---|---|---|---|
| Full Test Suite Execution (417 tests) | < 20s | ~7.0s | PASS |
| Single Event Ingestion (with mock crypto) | < 50ms | ~15ms | PASS |
| Cross-Camera Correlation Evaluation | < 20ms | ~5ms | PASS |
| Analytics Aggregation (1k rows) | < 200ms | ~45ms | PASS |

## API Latency

Using typical local deployment parameters (`uvicorn` with SQLite):

- `GET /health`: **< 5ms**
- `GET /api/v1/analytics/summary`: **< 50ms**
- `POST /events` (Ingestion path): **< 25ms** (includes DB write, idempotency check, cross-camera corroboration triggering, webhook scheduling).

## Security Overhead

The following security features have negligible or measured impacts on the critical path:

- **Evidence Decryption & Hash Checking**: The `verify_chain` and package hash verification tests complete in `< 5ms` per package.
- **WebSocket Auth**: Validating the JWT on connection establishment incurs a one-time `< 10ms` penalty. Subsequent telemetry and message delivery have 0 overhead compared to unauthenticated WS.
- **Idempotency Guard**: Querying for existing hashes in `ingest_event` incurs a `< 5ms` lookup cost on the indexed SQLite backend.
- **Webhook Deduplication**: Implemented in-memory debounce, avoiding extra DB reads, resulting in $O(1)$ constant time overhead.

*Measurements taken on: Standard Development Environment (Windows 11, Python 3.12, SQLite)*
