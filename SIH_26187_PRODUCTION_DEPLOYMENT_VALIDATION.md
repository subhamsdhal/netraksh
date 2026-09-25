# Executive Summary

Static deployment validation was completed without changing the validated
application pipelines. Docker Desktop/Engine is unavailable on this machine,
so the integrated PostgreSQL + MinIO + backend + frontend + edge acceptance bar
was not claimed. Native Python syntax/import checks and Alembic inspection
passed.

# Deployment Architecture

`docker-compose.yml` is the intended production-like path: PostgreSQL,
Alembic migration stage, backend, MinIO, frontend Nginx image, and one edge
worker. `docker-compose.edge.yml` and `docker-compose.test.yml` are classified
as legacy/test profiles and were not used as production evidence.

# Docker Tooling

**CONFIGURED:** Yes. **BUILT:** BLOCKED BY TOOLING. **STARTED:** BLOCKED BY
TOOLING. **HEALTHY:** BLOCKED BY TOOLING. **FUNCTIONALLY VERIFIED:** No.
`docker` was not found by `where.exe`, `docker version`, or `docker compose
version`.

# Images

Backend, edge, and frontend Dockerfiles are present with non-root runtime users
and pinned/declared dependencies. Image builds and in-container imports were
not executable without Docker.

# PostgreSQL

Compose defines a persistent PostgreSQL 15 volume and readiness healthcheck.
**CONFIGURED:** Yes. **BUILT/STARTED/HEALTHY/FUNCTIONALLY VERIFIED:** BLOCKED
BY TOOLING.

# Alembic Migrations

**CONFIGURED:** Yes. **BUILT:** Native tooling available. **STARTED:** Native
SQLite inspection completed. **HEALTHY:** Current native head is `9d4e6b2f1a88`.
**FUNCTIONALLY VERIFIED against fresh PostgreSQL:** BLOCKED BY TOOLING.

# MinIO / Object Storage

Compose defines persistent MinIO storage and a healthcheck; bucket creation and
real object flow were not executed. **STATUS:** BLOCKED BY TOOLING.

# Backend

Dockerfile includes FastAPI, Alembic, Prometheus, HTTPX, boto3, PostgreSQL
driver, and runtime source. Native compile/import checks passed. Container
build/start/readiness: BLOCKED BY TOOLING.

# Frontend

Production multi-stage Nginx image and SPA fallback are configured. Build was
previously verified natively; image/browser validation: BLOCKED BY TOOLING.

# Reverse Proxy

No integrated backend/WebSocket reverse-proxy configuration is present in the
authoritative Compose path; frontend Nginx currently serves static assets only.
**STATUS:** PARTIAL.

# Edge Worker 1

Dockerfile includes YOLO, ByteTrack, OpenCV contrib/LBPH, EasyOCR, YuNet/ONNX,
HTTPX, and crypto dependencies. Container execution: BLOCKED BY TOOLING.

# Edge Worker 2

The authoritative Compose file currently provisions one edge service; an
independent second worker is not yet configured. **STATUS:** NOT IMPLEMENTED.

# Model Assets

The edge model is intentionally host-mounted through `DETECTOR_MODEL_HOST_PATH`;
this avoids baking a large artifact but requires explicit clean-machine setup.
**STATUS:** CONFIGURED, runtime unverified.

# Authentication

Production settings reject placeholder secrets and require edge credentials.
Container auth flow: BLOCKED BY TOOLING.

# Edge Identity

Existing mTLS/edge binding controls remain in source. Compose currently uses a
shared `EDGE_AUTH_TOKEN` environment variable for the single demo worker.
**STATUS:** MITIGATED; per-device container provisioning remains.

# Evidence Flow

Local and S3-compatible storage abstractions are configured; MinIO object
write/retrieval was not executed. **STATUS:** BLOCKED BY TOOLING.

# Offline Recovery

Native SQLite outbox recovery was previously verified. Container volume and
restart persistence: BLOCKED BY TOOLING.

# Webhook Delivery

Webhook SSRF/signing hardening is present. Durable delivery across backend
restart remains partial and was not container-tested. **STATUS:** PARTIAL.

# Retention

Retention configuration is not yet a complete deployment cleanup service.
**STATUS:** PARTIAL.

# Security Regression

Native security tests passed previously; deployed-stack media, traversal,
upload, webhook, and WebSocket checks: BLOCKED BY TOOLING.

# Night Event Closure

Native edge/outbox night fallback evidence exists; PostgreSQL/WebSocket/browser
container closure: BLOCKED BY TOOLING.

# ANPR Container Validation

Dependency/image import validation inside the edge container: BLOCKED BY
TOOLING. Native ANPR path remains validated separately.

# Face Container Validation

OpenCV contrib/LBPH container import and watchlist sync: BLOCKED BY TOOLING.

# Restart / Persistence

PostgreSQL, MinIO, and edge volume restart tests: BLOCKED BY TOOLING.

# Resource Usage

NOT MEASURED; `docker stats` unavailable.

# Startup Time

NOT MEASURED for containers.

# Failure Testing

Container failure/degradation scenarios: BLOCKED BY TOOLING.

# Automated Tests

Native Alembic head inspection and Python compile checks passed. Prior validated
backend regression was 157 passed; frontend tests 13 passed and frontend build
passed. Container-specific tests were not runnable.

# Clean Machine Procedure

1. Install Docker Desktop with Compose.
2. Copy `.env.example` to `.env`; set strong database, JWT, edge, MinIO, and
   model-path values.
3. Run `docker compose config` and resolve all required-variable errors.
4. Run `docker compose up -d --build`.
5. Confirm `db` healthy, `migrate` completed, backend ready, MinIO healthy,
   frontend reachable, then execute the two-camera and persistence checks.
6. Shut down normally with `docker compose down`; reserve `down -v` for an
   intentional destructive fresh-database test.

# Remaining Limitations

- Docker runtime unavailable, so production deployment is BLOCKED BY TOOLING.
- PostgreSQL/MinIO integration, container image builds, reverse-proxy WebSocket,
  two independent edge workers, restart persistence, and resource measurements
  remain unverified.
- Compose still exposes direct backend/MinIO development ports and uses a
  single edge token; production deployment should place them behind a trusted
  proxy and provision per-device credentials.
