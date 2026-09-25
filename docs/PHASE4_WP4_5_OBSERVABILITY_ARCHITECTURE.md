# Phase 4 WP-4.5: Observability Architecture

## Overview
The NETRAKSH observability architecture embraces a strict separation of Metrics, Logs, and Traces, guaranteeing that operational telemetry is decoupled from core pipeline viability. 

### Core Tenets
1. **Failure Isolation:** The observability tier (metrics emission, log formatting, context-var propagation) MUST NOT become a single point of failure. If Prometheus is missing, or logging throws a serialization exception, the system traps the error and continues pipeline execution.
2. **Cardinality Safety:** Metrics use rigid, predefined structures. Highly varying IDs (`event_id`, `evidence_id`, `request_id`, etc.) are prohibited in Metric labels to prevent Prometheus memory exhaustion.
3. **Identifier Sanitization:** Secrets (JWT, passwords, RTSP auth strings, private keys, face embeddings) are strictly scrubbed from all logs. Edge, Camera, and Correlation IDs are contextually allowed where operational context is required.

## Stack Layout
- **Metrics:** `prometheus_client` exported natively via a protected HTTP endpoint. 
- **Logging:** Standard Python logging powered by a custom JSON `RedactingJSONFormatter` injecting `contextvars`.
- **Tracing:** OpenTelemetry abstractions are DESIGN READY but explicitly NOT DEPLOYED to minimize mandatory dependencies.
