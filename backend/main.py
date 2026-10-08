"""
NETRAKSH — FastAPI application entrypoint.
Boots the backend: database init, user bootstrap, routers, CORS, WebSocket.
"""
from __future__ import annotations

import logging
import sys
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from backend.api import alerts, analytics, audit, auth, cameras, dashboard, demo, events, integrations, system, watchlist, websocket
from backend.api.rate_limit import limiter, RateLimitExceeded, _rate_limit_exceeded_handler
from backend.config import settings
from backend.database.session import SessionLocal, init_db
from backend.observability.middleware import RequestCorrelationMiddleware, PrometheusMiddleware
from backend.security.auth import bootstrap_users

# Configure logging — JSON in production/staging, human-readable in dev/test.
if settings.ENV in ("production", "staging"):
    from backend.observability.logging import configure_json_logging
    configure_json_logging(level=settings.LOG_LEVEL)
else:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("NETRAKSH backend starting up...")
    # Initialize database tables
    init_db()
    # Bootstrap default users
    db = SessionLocal()
    try:
        bootstrap_users(db)
        # Seed a demo camera if none exist
        _seed_demo_data(db)
    finally:
        db.close()
    logger.info(f"Command Center ready. Command ID: {settings.COMMAND_ID}")
    logger.info(f"Blockchain mode: {settings.BLOCKCHAIN_MODE.upper()}")
    if settings.BLOCKCHAIN_MODE == "mock":
        logger.warning(f"  -> {settings.BLOCKCHAIN_MOCK_LABEL}")
    if settings.RUN_STORAGE_SMOKE_TEST_ON_STARTUP:
        from backend.services.storage_smoke import run_startup_storage_smoke_test
        run_startup_storage_smoke_test()
    # Start WebSocket background tasks (telemetry batcher + heartbeat).
    # Must be called inside the async lifespan context so the asyncio
    # event loop is running when create_task is called.
    await websocket.manager.start_background_tasks()
    
    # Phase 6: Start Async Webhook Worker
    from backend.services.escalation import start_webhook_worker
    start_webhook_worker()
    from backend.services.camera1_liveness import monitor_camera1_active_analysis
    camera1_liveness_task = asyncio.create_task(monitor_camera1_active_analysis())

    try:
        yield
    finally:
        camera1_liveness_task.cancel()
        try:
            await camera1_liveness_task
        except asyncio.CancelledError:
            pass
    logger.info("NETRAKSH backend shutting down.")


def _seed_demo_data(db) -> None:
    """Seed demo cameras and zones if the database is empty."""
    from backend.models.orm import Camera, Zone
    import json

    if db.query(Camera).count() > 0:
        return

    logger.info("Seeding demo camera and zone data...")

    # Seed cameras intentionally have no coordinates.  A geospatial command
    # map must not present plausible demo coordinates as deployed hardware;
    # an administrator supplies the real site position through the location
    # endpoint when one is genuinely known.
    # Command A — main camera
    cam_a = Camera(
        id="cam-border-01",
        name="Border Post Alpha - Camera 1",
        location="Sector 7, Border Post Alpha",
        rtsp_url=None,
        owning_command_id="COMMAND_A",
        latitude=None,
        longitude=None,
    )
    cam_b = Camera(
        id="cam-checkpoint-01",
        name="Checkpoint Bravo - Camera 1",
        location="Main checkpoint, Sector 7",
        rtsp_url=None,
        owning_command_id="COMMAND_A",
        latitude=None,
        longitude=None,
    )
    db.add_all([cam_a, cam_b])
    db.flush()

    # Fence zone on cam_a — crosses jurisdiction to COMMAND_B
    fence_zone = Zone(
        id="zone-fence-01",
        camera_id="cam-border-01",
        name="Border Fence Zone",
        zone_type="fence",
        polygon_json=json.dumps([
            {"x": 0.05, "y": 0.1}, {"x": 0.95, "y": 0.1},
            {"x": 0.95, "y": 0.9}, {"x": 0.05, "y": 0.9}
        ]),
        owning_command_id="COMMAND_A",
        adjacent_command_id="COMMAND_B",  # → cross-command escalation eligible
    )
    # Checkpoint zone — ANPR
    checkpoint_zone = Zone(
        id="zone-checkpoint-01",
        camera_id="cam-checkpoint-01",
        name="Checkpoint Entry Zone",
        zone_type="checkpoint",
        polygon_json=json.dumps([
            {"x": 0.2, "y": 0.2}, {"x": 0.8, "y": 0.2},
            {"x": 0.8, "y": 0.8}, {"x": 0.2, "y": 0.8}
        ]),
        owning_command_id="COMMAND_A",
        adjacent_command_id=None,
    )
    db.add_all([fence_zone, checkpoint_zone])
    db.commit()
    logger.info("Demo seed complete: 2 cameras, 2 zones")


app = FastAPI(
    title="NETRAKSH Command Center",
    description=(
        "AI-Based Intelligent Video Analytics Platform for Border Surveillance. "
        "Reliability-qualified decisions: DETECTED / UNCERTAIN / ABSTAIN. "
        "SIH 2026, PS #187, Team SecureX."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — restricted to known frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

# Observability middlewares — added after CORS so they run inside the CORS layer
# Order (outer to inner): Prometheus → Correlation
app.add_middleware(PrometheusMiddleware)
app.add_middleware(RequestCorrelationMiddleware)

# ── Security response headers ────────────────────────────────────────────────────────
# Defense-in-depth: add standard security headers to every HTTP response.
# These do not replace proper CORS or auth, but reduce the impact of XSS
# and clickjacking against the operator's browser session.
@app.middleware("http")
async def add_security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    # Prevents browsers from MIME-sniffing a response away from the declared
    # Content-Type. Blocks CSS injection via image-upload if ever added.
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Deny embedding in any <iframe> / <frame> / <object> — anti-clickjacking.
    response.headers["X-Frame-Options"] = "DENY"
    # Legacy XSS filter (Chrome 57+, IE 8+) — belt-and-suspenders; CSP is
    # the primary protection.
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Only send the origin in the Referer header, never the full path —
    # prevents leaking event IDs to any third-party resources.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Permissions Policy: this dashboard needs no camera/microphone/geolocation
    # access from the browser (video is always server-side). Deny all.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    # Content-Security-Policy:
    # - default-src 'self': baseline allow-list
    # - script-src 'self': no inline scripts, no external script CDNs
    # - style-src 'self' 'unsafe-inline': React/Vite inject inline style tags;
    #   required for the current frontend build. Removing 'unsafe-inline'
    #   requires a full build-system change (nonce injection) — out of scope here.
    # - font-src 'self' https://fonts.gstatic.com: Google Fonts files
    # - img-src 'self' data: blob:: data URIs used for canvas exports;
    #   blob: for video object URLs from URL.createObjectURL()
    # - connect-src 'self' ws: wss:: WebSocket connections to the backend
    # - frame-ancestors 'none': supersedes X-Frame-Options: DENY
    # - object-src 'none': disables Flash/plugin embedding
    # - base-uri 'self': prevents base-tag injection
    # Note: this CSP applies to the backend-served frontend (single-container).
    # For the Vercel-hosted frontend, set CSP via vercel.json headers config.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "base-uri 'self'"
    )
    return response

# ── Rate limiter ────────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Include all routers
app.include_router(system.router)
app.include_router(auth.router)
app.include_router(cameras.router)
app.include_router(events.router)
app.include_router(alerts.router)
app.include_router(analytics.router)
app.include_router(audit.router)
app.include_router(watchlist.router)
app.include_router(integrations.router)
app.include_router(websocket.router)
# Dashboard video router — always mounted (authenticated, no scenario switching).
# Provides POST /api/dashboard/video/upload and GET /api/dashboard/video/current
# for the SIH presentation video workflow in all environments.
app.include_router(dashboard.router)

if settings.ENV == "development":
    app.include_router(demo.router)
else:
    logger.info("Demo scenario-control API is disabled outside development mode.")

@app.get("/")
async def root() -> dict[str, str]:
    """Backend control-plane entry point; the SPA is deployed separately."""
    return {
        "service": "NETRAKSH Command Center API",
        "status": "ok",
        "health": "/health",
        "ready": "/ready",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
