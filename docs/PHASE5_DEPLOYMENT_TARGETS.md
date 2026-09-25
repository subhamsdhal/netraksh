# Phase 5: Deployment Targets

## 1. DEVELOPMENT
**Purpose:** Local developer environment.
**Topology:** Runs via local Python processes (`python backend/main.py`, `python edge/main.py`) or lightweight `docker-compose` bridging local directories for rapid iteration.
**Secrets:** Mocked `.env` files. Not intended for real camera exposure.

## 2. STAGING
**Purpose:** CI/CD Integration validation. **MUST BE EXECUTABLE.**
**Topology:** 
- Central: FastAPI, PostgreSQL, MinIO, Prometheus, Frontend.
- Edge: At least 1 Edge container with persistent volume mounts, injected test mTLS credentials, and a simulated/synthetic RTSP stream.
**Validation Goal:** Validates the unbroken chain from ingestion to DB storage and failure recovery.

## 3. PRODUCTION TARGET
**Purpose:** Real-world physical deployment.
**Status:** DESIGNED / NOT DEPLOYED / NOT VALIDATED.
**Topology:** Refer to `PHASE5_PRODUCTION_TARGET.md` for architectural design specs.
