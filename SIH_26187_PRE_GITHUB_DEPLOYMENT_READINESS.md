# SIH 26187 — Pre-GitHub + Render Backend-Only Deployment Readiness

Scope: repository preparation and local validation only. No GitHub push, Render deployment, remote deletion, history rewrite, or edge inference on Render was performed. Existing user work was preserved; no reset or clean operation was used.

## Render architecture

The authoritative Render service is a Docker web service using backend/Dockerfile. It runs one FastAPI control-plane process and uses Render's PORT value. It does not copy or launch edge/, camera workers, demo_runner.py, or a frontend development server.

Cloud responsibilities:

- Static frontend: Firebase Hosting or Vercel.
- Render: FastAPI API, WebSocket, authentication, database/control-plane services, and health/readiness endpoints.
- Edge machine: camera ingestion, YOLO/ByteTrack, ANPR/EasyOCR, face/night processing, evidence packaging, and offline sync.

The legacy root Dockerfile remains only as a compatibility artifact and is not the Render target.

## Backend dependencies

requirements-backend.txt is the control-plane manifest. It contains FastAPI/Uvicorn, SQLAlchemy/PostgreSQL, authentication/security, HTTP, rate limiting, metrics, NumPy, Alembic, boto3, and one OpenCV package. It does not contain torch, torchvision, ultralytics, easyocr, onnxruntime, retina-face, or edge model packages.

OpenCV was added as exactly one server-safe package:

    opencv-contrib-python-headless==4.10.0.84

The contrib headless wheel is used because backend/api/watchlist.py imports cv2 unconditionally and the watchlist path may use cv2.face. The full edge requirements remain separate. Duplicate OpenCV wheels were removed from edge/requirements.txt so pip cannot install overlapping distributions.

## Dockerfile and Render config

backend/Dockerfile:

- Python 3.12 slim base.
- Backend-only requirements.
- Copies backend, shared, and Alembic runtime files.
- Creates deployment-specific certificate directories without copying private TLS material.
- Runs one process: python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}.

render.yaml:

- type: web, runtime docker, plan free as declared in the repository.
- dockerfilePath: ./backend/Dockerfile.
- healthCheckPath: /health.
- Uses environment-variable references for DATABASE_URL and EDGE_AUTH_TOKEN.
- Contains no literal live credential and no VIDEO_SOURCE/edge simulator command.
- Keeps explicit production CORS origins.

A real Render account plan, RAM limit, service logs, and service metrics were not available because the dashboard required authentication.

.dockerignore now excludes local environments, frontend dependencies/build output, demo videos, model weights, edge data, databases, certificates, artifacts, logs, caches, archives, and temporary files while retaining backend/shared/Alembic source required by the backend image.

Docker was not installed on this host, so an actual image build was not claimed.

## Backend-only import and start validation

A disposable clean virtual environment was created, installed only from requirements-backend.txt, and removed after testing.

Results:

- import backend.main: PASS
- import uvicorn: PASS
- cv2 import: PASS, version 4.10.0
- torch/torchvision/ultralytics/easyocr/onnxruntime/retina-face loaded during backend import: NONE
- temporary Render-style backend process: PASS
- GET /health: HTTP 200
- GET /ready: HTTP 200
- no edge subprocess started

## Memory measurement

The remediated backend-only process was measured without camera workers:

- startup RSS: approximately 117.5 MiB
- stable RSS after 3 seconds: approximately 117.5 MiB
- after 20 health/readiness requests: approximately 118.4 MiB

This is a local Windows RSS measurement, not a Render guarantee. It shows no obvious short-run growth and does not claim that every free-tier configuration has adequate margin.

## Frontend static deployment

The frontend continues to use VITE_BACKEND_URL and VITE_WS_URL. Development may use localhost/127.0.0.1; production builds must supply a public HTTPS backend URL and a WSS dashboard URL. No production localhost fallback is used when Vite is building in production mode.

Validated with:

- frontend tests: 9 files, 23 tests passed
- production build with HTTPS/WSS Render-style variables: PASS
- build output: frontend/dist

Static hosting must rewrite unknown SPA routes to index.html. No frontend deployment was performed.

## CORS and HTTPS/WSS

render.yaml retains explicit Vercel/Firebase origins and FRONTEND_ORIGIN. The backend rejects wildcard CORS with credentials; localhost origins remain available in development. Production frontend traffic must use HTTPS and the dashboard socket must use WSS. The actual deployed origin still requires confirmation in the Render/static-host dashboards.

## SQLite deployment reality

SQLite remains appropriate for local SIH/demo operation. A Render web service must use a managed PostgreSQL DATABASE_URL because local SQLite storage on an ephemeral web instance is not production-durable. The code already supports PostgreSQL through SQLAlchemy and psycopg2-binary. A live Postgres deployment was not attempted.

## Gitignore and generated artifacts

The ignore rules cover .env and .env.* while allowing .env.example; .venv/ and venv/; node_modules, Python caches, pytest/coverage output; logs and temporary runtime media; SQLite/database archives; artifacts, screenshots, JSONL/traces, and temporary binaries; private PEM/P12 patterns; and local TLS material.

Important human-readable validation reports remain available. No generated artifact was deleted.

## Secrets and historical credentials

Current tracked-file checks found:

- current live secrets: 0
- private crypto material tracked: 0
- SQLite databases tracked: 0
- tracked .env files other than the placeholder .env.example: 0

The current tree contains an untracked local private-key file from prior work; it is not tracked and is now covered by the private-key ignore pattern. Its value was not printed or copied.

Historical render.yaml commits contain one revoked database credential. The current working tree contains no live copy. Credential rotation/revocation is already reported; history cleanup remains a pending owner decision. No history rewrite was attempted.

## Models and videos

Current tracked large assets:

- demo/videos/uploaded_demo.mp4 — 53,193,629 bytes
- face_recognition_sface_2021dec.onnx — 38,696,353 bytes
- yolov8n.pt — 6,549,796 bytes
- lpd_yunet.onnx — 4,146,213 bytes

The uploaded demo video is the reproducible SIH fixture; no redundant working fixture was removed. The model files are required by local edge functionality and were retained.

Git LFS is recommended for future pushes for model and uploaded-demo patterns. .gitattributes was added for future LFS tracking; it does not migrate existing history. Git LFS is installed locally. No file exceeds GitHub's 100 MiB single-file hard limit.

Historical Git object analysis found the largest historical blob at approximately 38.7 MiB, followed by the YOLO and YuNet model blobs. No historical blob exceeded GitHub's hard limit, though binary history is still a reason to consider a clean public history or coordinated migration.

Classification:

- Keep for local SIH demo: yolov8n.pt, face_recognition_sface_2021dec.onnx, lpd_yunet.onnx, uploaded_demo.mp4.
- Prefer Git LFS for normal future repository updates: all four above.
- Do not download edge models into the Render backend image.

## Security tests

Focused security tests were run. The initial run had 48 passes and two setup errors caused by a pre-existing permission-locked pytest runtime directory. The affected security module was rerun with an isolated temporary directory: 3 tests passed. No source or test fix was made for that environmental permission issue.

## Git status and GitHub strategy

The worktree remains substantially dirty from prior user work and is intentionally not safe for an indiscriminate public push. A local backup branch named pre-github-remediation-backup-20260925 was created before deployment-file changes; it was not pushed.

Recommended strategy: CLEAN NEW HISTORY if the goal is a clean public SIH repository, because the repository has historical revoked credential material and substantial generated/binary history. HISTORY REWRITE is an alternative only if preserving the existing repository identity/history is important and the owner explicitly authorizes secret purge. NORMAL PUSH is not recommended until the owner decides how to handle historical secret and binary history and separates unrelated worktree changes.

## Exact remaining blockers before push

1. Owner decision on clean new history versus coordinated history rewrite for the revoked historical credential.
2. Owner review and staging of only the intended remediation files; the current worktree contains many unrelated prior changes and generated files.
3. Confirm the real Render environment values and service target in the authenticated dashboard.
4. Run a real Docker build when Docker is available.
5. Validate against a real managed PostgreSQL instance before production claims.
6. Choose whether to migrate the retained model/video assets to Git LFS.
7. Run a longer edge-device memory soak separately; Render must remain backend-only.

## Changes made in this preparation

Only deployment-readiness changes were made: backend OpenCV manifest correction, backend Docker command clarification, edge OpenCV de-duplication, Render comments/config cleanup, .dockerignore, .gitignore additions, .env.example placeholders, static deployment documentation, and future Git LFS attributes. No application feature was intentionally changed, and no GitHub/Render action was performed.
