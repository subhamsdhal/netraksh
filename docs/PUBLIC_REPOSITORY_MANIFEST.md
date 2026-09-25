# NETRAKSH Public Repository Manifest

This manifest defines the intended clean public tree for SIH 26187. It describes
the current filesystem; it does not authorize a GitHub push.

## Public components

- backend/ — FastAPI control plane, authentication, APIs, WebSocket, persistence, and observability.
- frontend/ — React/Vite dashboard source, tests, and production build configuration.
- edge/ — camera-side ingestion, inference, reliability, evidence, and offline synchronization.
- shared/ — schemas and shared observability helpers.
- alembic/ and alembic.ini — database migration sources.
- scripts/ — repeatable setup, validation, conversion, and benchmark utilities.
- docs/ — deployment guidance and intentionally retained human-readable engineering reports.
- tests/ — backend and frontend test sources.
- render.yaml and backend/Dockerfile — backend-only Render deployment configuration.
- requirements-backend.txt, requirements.txt, and edge/requirements.txt — separated control-plane and edge dependency manifests.
- demo/ — demo control code and the explicitly retained SIH fixture media.

## Required local/demo assets

- yolov8n.pt — local edge detector model.
- face_recognition_sface_2021dec.onnx — local face embedding model.
- lpd_yunet.onnx — local license-plate detector model.
- demo/videos/uploaded_demo.mp4 — retained reproducible demo fixture.

These assets are not copied into the Render backend image. Git LFS tracking is
declared for the large model/video patterns for future repository operations.

## Intentionally excluded

- .env, .env.local, .env.production, and all real secret-bearing environment files.
- SQLite databases, database archives, runtime evidence, uploads, and edge/data.
- .venv, venv, node_modules, frontend/dist, Python/pytest caches, logs, screenshots,
  JSONL traces, temporary artifacts, archives, and editor/OS files.
- Private PEM/P12/key material and deployment-specific TLS certificates.
- Render account secrets and the historical revoked credential.
- The legacy monolithic image is retained for reference but is not a deployment target.

The clean branch is intended to contain source, migrations, configuration templates,
required fixtures, and useful human-readable documentation—never live credentials.
