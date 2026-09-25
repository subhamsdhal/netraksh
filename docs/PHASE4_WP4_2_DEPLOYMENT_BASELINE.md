# Phase 4 WP-4.2: Deployment Baseline Audit

An audit of the current deployment architecture reveals a prototype-oriented monolithic configuration that must be separated for a real-world edge-to-cloud topology.

## 1. Current `Dockerfile` (Monolith)
- **Path**: `/Dockerfile`
- **Architecture**: Single-container deploy image originally created for a hosted prototype (Render).
- **Behavior**: It uses a multi-stage build to compile the React frontend, then copies it into a Python runtime. It installs full edge ML dependencies (OpenCV `libgl1`) alongside backend dependencies.
- **Startup**: Uses `/start.sh` to run `edge/demo_runner.py` in the background and `uvicorn backend.main:app` in the foreground.
- **Flaws for Production**: 
  - Edge compute (AI inference) and Central compute (API/DB) compete for resources in the same container.
  - Secrets and configurations are intertwined.
  - A crash in the Edge pipeline could impact the Central API's reliability.
  - Does not reflect a true distributed edge-to-cloud topology.

## 2. Current `backend/Dockerfile`
- **Path**: `/backend/Dockerfile`
- **Architecture**: Slim Python container for the backend.
- **Flaws for Production**:
  - Exposes port 8000 but lacks explicit production hardening (non-root user).
  - Depends on `requirements-backend.txt` which lacks strict lockfiles (e.g. poetry).

## 3. Current `docker-compose.yml`
- **Architecture**: Defines `db`, `backend`, and `frontend`.
- **Environment**: Injects default development passwords (`secure_password_here`).
- **Flaws for Production**: 
  - Mixes local development defaults directly into the compose file without failing closed.
  - Does not provision an Edge container (relies on local execution).
  - Does not define an object storage (MinIO) dependency required for WP-3.3.

## 4. Dependencies
- **Edge**: Requires OpenCV (`libgl1`, `libglib2.0`), heavy PyTorch/Ultralytics models, and TLS certificates for mTLS.
- **Central**: Requires PostgreSQL headers (`libpq-dev`), FastAPI, Boto3, and database credentials.
- **Intersection**: Both share the `shared/` python module (constants, schemas).

## 5. Storage / Volumes
- **Edge**: Needs `/app/edge/data` for offline event queues and evidence staging.
- **Central**: Needs external Object Storage (S3/MinIO) and PostgreSQL. Currently relies on a local mounted `/var/lib/postgresql/data`.

## Conclusion
The baseline architecture must be split. The Edge components must be isolated into a dedicated Edge Container with its own resource limits, storage mounts, and outbound-only network configuration. The Central components must be hardened into a cloud-ready topology.
