# NETRAKSH Border Intelligence Unit

**NETRAKSH** is a defense-grade, low-latency border intelligence and tamper-evident command dashboard. It is designed to ingest high-frequency edge telemetry, perform cryptographic verification of evidence, and facilitate tactical decision-making with zero-trust security principles.

## 🛡️ System Overview

NETRAKSH aggregates data from remote, edge-deployed camera nodes and applies near-real-time threat analysis. Its core capabilities include:
- **Tamper-Evident Evidence Vault:** All evidence clips and detection metadata are hashed and signed at the edge (Ed25519) and cryptographically verified by the backend to ensure zero tampering.
- **Geospatial Command Map:** Live tracking of detected subjects across sector zones using an interactive cartographic interface.
- **Threat Escalation & Watchlist:** Automated identification of high-value targets via face-matching, coupled with rapid webhook escalation and cross-camera corroboration.
- **Audit Trail:** All critical operator actions (Watchlist modifications, evidence decryption) are logged to a PostgreSQL database. Evidence integrity is provided through SHA-256 hashing and Ed25519 signatures.
- **Network Resilience:** The dashboard features a robust WebSocket pipeline that handles server disconnects gracefully with exponential backoff and tactical UI overlays.

## 🏗️ Architecture Topology

NETRAKSH is orchestrated via Docker Compose into a strict 3-tier architecture:

1. **Frontend (Nginx / React & Vite)**
   - Serves the static compiled React application.
   - Communicates with the backend via REST (JWT Auth) and secure WebSockets.
2. **Backend (FastAPI / Python 3.10)**
   - High-concurrency async API server managing event ingestion, verification logic, and WebSocket broadcasting.
   - Minimal dependency footprint (avoids heavy ML libraries like PyTorch; expects edge nodes to perform the inference).
3. **Database (PostgreSQL / Alpine)**
   - Relational data store for structured intelligence and audit logging.

## 🔒 Security Posture

NETRAKSH implements defense-in-depth across the entire stack:
- **Cryptographic Signatures:** Evidence packages are protected by Ed25519 signatures and SHA-256 hashing.
- **Audit Trail:** Comprehensive API event logging ensures operator actions are tracked in the database.
- **Rate Limiting:** Edge ingestion endpoints are protected by `slowapi` to mitigate DDoS and brute-force attacks.
- **Debounce Logic:** Webhook escalation prevents alert fatigue and spam by enforcing time-based suppression for duplicate threat matches.
- **RBAC & Zero Trust:** Endpoints require strict JWT validation. Evidence is encrypted via AES-256-GCM.

## 🚀 Quickstart Guide

### Prerequisites
- Docker and Docker Compose
- Node.js 20+ (for local development only)
- Python 3.10+ (for local development only)

### Deployment
1. **Configure Environment:**
   Copy the provided template and populate the production secrets.
   ```bash
   cp .env.example .env
   ```
2. **Build and Spin Up Containers:**
   Launch the system in detached mode.
   ```bash
   docker-compose up --build -d
   ```
3. **Access the Dashboard:**
   Navigate to http://localhost:80 in your browser. Use credentials provisioned in the
   local environment; no default production password is documented here.

## Deployment modes

### Local SIH mode

Run the FastAPI backend locally, the Vite frontend locally, and the edge workers on
camera-side compute. Local development may use SQLite and localhost URLs.

### Cloud control-plane mode

The Render web service uses backend/Dockerfile and runs one backend Uvicorn process on
Render's PORT. It does not run YOLO, ByteTrack, EasyOCR, face/night inference,
demo_runner.py, or camera workers. Build the frontend with npm run build and host
frontend/dist on Firebase Hosting or Vercel, configured with public HTTPS/WSS URLs.
Edge AI remains on separate local or provisioned camera compute.

SQLite is not durable on an ephemeral Render web service; production uses a managed
PostgreSQL DATABASE_URL. A live PostgreSQL deployment, Fabric network, and physical
CCTV validation are not claimed by this repository.

## ⚔️ Red Team Validation

To verify the integrity of the live deployment, execute the automated Red Team Simulation script. This script stress-tests rate limiting, unauthorized access, debounce logic, and signature forgery protections.

1. Ensure the backend is running.
2. Execute the script:
   ```bash
   python scripts/red_team_sim.py
   ```
3. Review the terminal output for `[PASS]` / `[FAIL]` assertions. All tests are expected to pass under normal production conditions.
