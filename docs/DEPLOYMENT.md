# NETRAKSH — Deploying to Render

This is the actual walkthrough for the deployment this project is configured for
(`backend/Dockerfile`, `render.yaml`, `requirements-backend.txt`). Render hosts the
FastAPI command-center backend/control plane only. The frontend is a static build on
Firebase Hosting or Vercel, and the edge AI pipeline runs on camera-side compute.

## Supported Deployment Matrix

The application supports multiple deployment environments using the exact same codebase. The frontend remains agnostic and selects the backend via `VITE_BACKEND_URL`, while the backend relies on `DATABASE_URL` for PostgreSQL.

### SUPPORTED NOW

**A. Firebase Hosting → Render → Supabase PostgreSQL**
- Frontend is hosted on Firebase (`https://netraksh-35030.web.app`).
- Communicates with the Render FastAPI backend (`https://netraksh.onrender.com`).
- Render connects to Supabase PostgreSQL.

**B. Vercel → Render → Supabase PostgreSQL**
- Frontend is hosted on Vercel (`https://netraksh.vercel.app`).
- Communicates with the Render FastAPI backend (`https://netraksh.onrender.com`).
- Render connects to Supabase PostgreSQL.

**C. Local Frontend → Local/Render Backend → PostgreSQL**
- Frontend running locally (`http://localhost:5173`).
- Connects to a local backend (`http://localhost:8443`) or remote Render backend.
- Backend connects to SQLite or Supabase PostgreSQL.

### FUTURE / NOT IMPLEMENTED

**D. Firebase Native Stack (Firebase-Only)**
- Firebase Hosting → Firebase Auth → Firestore / Realtime Database.
- *Status:* **NOT CURRENTLY IMPLEMENTED**. 
- *Note:* If built in the future, this should be treated as a separate backend/data implementation profile, not interleaved within the current standard React logic.

## Prerequisites

- A GitHub repository containing this project (push it there first if it isn't already).
- A Render account (render.com — free to create, no credit card required for the free tier
  used here).

## Steps

1. **Push this repo to GitHub** if you haven't already:
   ```bash
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin master
   ```

2. **On Render: New → Blueprint.** Connect your GitHub account if this is your first time,
   then select this repository. Render will detect render.yaml at the repo root.
   Keep the service pointed at backend/Dockerfile; do not select the legacy root
   Dockerfile.

3. **Click Apply.** Render builds and deploys the backend image. Set DATABASE_URL to a
   managed PostgreSQL connection string in the Render Environment tab; SQLite is for
   local/demo use only and is not durable on an ephemeral web service.

4. **Retrieve the generated admin password.** `render.yaml` has Render generate real random
   values for `SECRET_KEY`, `ADMIN_PASSWORD`, `INITIAL_OPERATOR_PASSWORD`, and
   `INITIAL_AUDITOR_PASSWORD` at deploy time — never the `CHANGE_ME_*` placeholders
   `backend/config.py` defaults to locally, and never committed anywhere. To log in:
   Render dashboard → the `netraksh` service → **Environment** tab → find `ADMIN_PASSWORD`
   → reveal it. Username is `admin`. 
   
   *(Note: These are seed-time values only. Existing users in Supabase PostgreSQL remain the source of truth.)*

5. **Build the frontend separately.** From frontend/, set VITE_BACKEND_URL to the
   public HTTPS Render URL and VITE_WS_URL to its WSS dashboard URL, then run npm run
   build. Publish frontend/dist to Firebase Hosting or Vercel with an SPA fallback to
   index.html.

## Deployment responsibilities

### Local SIH mode

- Backend: python -m uvicorn backend.main:app --host 127.0.0.1 --port 8443.
- Frontend: Vite development server on port 5173.
- Edge: local camera workers and AI models, using the full edge requirements.

### Cloud control-plane mode

- Static frontend: Firebase Hosting or Vercel, built with npm run build.
- Render: one backend Uvicorn process from backend/Dockerfile, using the Render PORT.
- Edge: external/local camera compute; Render does not launch YOLO, ByteTrack, EasyOCR,
  face/night processing, demo_runner.py, or camera workers.

The static host must rewrite unknown SPA routes to /index.html. Production browser
traffic must use HTTPS for the backend and WSS for the dashboard WebSocket.

## What this does NOT deploy

- **The edge pipeline** (`edge/`) — YOLOv8n detection, the Reliability Engine, evidence
  encryption/signing, the offline sync queue. That code runs on a camera-side machine in
  the real architecture and was deliberately excluded from this container (see the
  Dockerfile's own comments and `requirements-backend.txt`) — installing
  `ultralytics`/`opencv`/`easyocr`/`retina-face` into a service that never imports any of
  it would multiply build time and image size for nothing. To see real edge-generated
  events on the live deployment, either run `edge/main.py` locally pointed at
  `BACKEND_URL=https://<your-render-url>`, or POST a synthetic event directly to
  `POST /events` (see any of this project's own verification steps in
  `docs/ARCHITECTURE.md` for the exact payload shape) to demo the dashboard live.
- **A real blockchain network.** `BLOCKCHAIN_MODE` stays `mock` — Fabric needs
  Docker/WSL2, unavailable on the dev machine this was built on, and out of scope for a
  free web-service deploy target too.

## Known limitation: unverified against a real Postgres instance

Docker was never available on the machine this was built on, so the Postgres code path
(`psycopg2-binary`, the `postgres://` → `postgresql://` URL-scheme fix in
`backend/config.py`, `pool_pre_ping`/`pool_size` engine settings in
`backend/database/session.py`) was written and reasoned through carefully but **could not
be exercised against a real running Postgres server before this deployment** — every
verification in this project up to now has been against real SQLite. The schema-creation
and migration logic (`init_db()`, `_migrate_add_missing_columns()`) is written to be
database-agnostic via SQLAlchemy's `inspect()`, not SQLite-specific, but "written to be"
and "verified to be" are different claims — this is the first time it's actually true.
