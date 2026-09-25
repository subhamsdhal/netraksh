# Phase 4 WP-4.2: Edge Container

## Build Configuration
- **Dockerfile**: `edge/Dockerfile`
- **Base Image**: `python:3.12-slim`
- **Entrypoint**: `CMD ["python", "edge/main.py"]`

## Security Profile
- **Non-Root Execution**: Runs entirely under the `netraksh` user (`USER netraksh`).
- **Secret Isolation**: Secrets (e.g., identity keys, TLS certificates) are never `COPY`'d into the image layer during `docker build`.
- **Runtime Injection**: Certificates and keys must be bind-mounted to `/app/certs/edge` at runtime.

## Operational Constraints
- **Liveness**: The container is alive if the python process is running.
- **Readiness**: The container is ready when it successfully loads its models and starts `CameraAdapter`.
- **Offline Resilience**: The Edge container operates fully detached from Central. If `BACKEND_URL` is unreachable, `SyncClient` queues events in the local SQLite buffer (`/app/edge/data/local_queue.db`).

## Excluded Components
- No web server/FastAPI.
- No PostgreSQL client (`libpq-dev`).
- No React frontend code.
- No `demo_runner.py` coupling in production builds.
