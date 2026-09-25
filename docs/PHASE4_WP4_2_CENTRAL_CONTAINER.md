# Phase 4 WP-4.2: Central Container

## Build Configuration
- **Dockerfile**: `backend/Dockerfile`
- **Base Image**: `python:3.12-slim`
- **Entrypoint**: `CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]`

## Security Profile
- **Non-Root Execution**: Runs under the `netraksh` user (`USER netraksh`).
- **Configuration Validation**: The backend implements strict startup checks via `config.py`. In `ENV=production`, it will hard-fail on startup if:
  1. `SECRET_KEY` is the default "CHANGE_ME" value.
  2. Any of the three default RBAC passwords (admin, operator, auditor) are left as their insecure defaults.
  3. `OBJECT_STORAGE_PROVIDER=s3` is defined but AWS S3 credentials are not set.
- **Dependency Scope**: Only the dependencies defined in `requirements-backend.txt` are installed. No Edge ML libraries are packaged in the Central container.

## Storage and Persistence
- **Ephemeral Image**: The container filesystem is explicitly ephemeral.
- **Data Persistence**: Postgres handles structured metadata. S3/MinIO handles evidence binaries. The Backend container does not require any long-term persistent local filesystem mounts.

## Health / Readiness
- Liveness is managed via standard FastAPI runtime checks.
- Readiness depends on successful connection to PostgreSQL (and optionally MinIO depending on object storage mode). `docker-compose.yml` models this with explicit `depends_on: service_healthy` directives.
