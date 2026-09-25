"""
NETRAKSH — WebSocket router (Phase 5 hardened).

Changes vs. original:
  1. Payload batching — telemetry frames are queued and flushed every 100ms
     instead of on every frame. This prevents 60-FPS edge nodes from flooding
     the React render cycle and the WebSocket send queue.
  2. Heartbeat / ping-pong — the server sends a real ping every 20s and
     expects a pong within 5s. Clients that don't respond are cleaned up
     immediately without waiting for a TCP timeout (which can take minutes).
  3. Per-client send queue — each client has an asyncio.Queue so slow clients
     are back-pressured (dropped frames) instead of blocking fast clients.
  4. Dead client cleanup — a background task sweeps disconnected sockets
     without needing every broadcaster to handle the exception.

SECURITY:
  - The WS endpoint requires a valid JWT. Browser clients send it in the
    Sec-WebSocket-Protocol header so credentials do not appear in request URLs
    or routine access logs. The legacy query parameter remains accepted only
    for backward compatibility with older edge/dashboard clients.
  - We do not echo back client messages — this is a strict server→client
    push channel. Any client message is silently discarded (no eval, no exec).
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.encoders import jsonable_encoder

from backend.security.auth import decode_token, get_command_filter
from shared.constants import UserRole

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


# ─── Constants ────────────────────────────────────────────────────────────────

# How often (seconds) the telemetry batcher flushes queued frames to clients.
TELEMETRY_BATCH_INTERVAL = 0.10   # 100ms → max 10 UI renders/sec regardless of FPS

# Heartbeat interval — server pings clients every N seconds.
HEARTBEAT_INTERVAL = 20.0

# Time client has to respond to ping before being considered dead.
PONG_TIMEOUT = 5.0

# Max queued messages per client before back-pressure drops oldest.
CLIENT_QUEUE_DEPTH = 32


# ─── Connection Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Thread-safe (asyncio-safe) manager for all active WebSocket connections.

    DESIGN:
      Each connected client gets:
        - An asyncio.Queue for outbound messages (back-pressure isolation)
        - A background send-task that drains the queue without blocking the
          main event loop or other clients
        - A liveness flag updated by the heartbeat task

      The telemetry batcher holds the LATEST frame per camera_id, not a queue
      of all frames. This means a slow client never receives "stale" frames
      from 500ms ago — it always gets the most current state when the batch
      flushes. This is correct for real-time surveillance overlays.
    """

    def __init__(self):
        # client websocket → outbound asyncio.Queue
        self._clients: Dict[WebSocket, asyncio.Queue] = {}
        # client websocket → asyncio.Task (send loop)
        self._send_tasks: Dict[WebSocket, asyncio.Task] = {}
        # client websocket → last pong received timestamp
        self._last_pong: Dict[WebSocket, float] = {}
        # client websocket → command scope (None means global ADMIN/AUDITOR)
        self._client_commands: Dict[WebSocket, Optional[str]] = {}
        # Lock protecting _clients dict mutations
        self._lock = asyncio.Lock()

        # Pending telemetry frames: camera_id → latest telemetry dict.
        # The batcher replaces, not appends — only the latest frame per
        # camera matters for a live overlay.
        self._pending_telemetry: Dict[str, dict] = {}
        self._telemetry_lock = asyncio.Lock()

        # Background tasks
        self._batcher_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def start_background_tasks(self):
        """Called once at app startup (lifespan). Starts the batcher and heartbeat."""
        if self._batcher_task is None or self._batcher_task.done():
            self._batcher_task = asyncio.create_task(
                self._telemetry_batch_loop(), name="ws-telemetry-batcher"
            )
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="ws-heartbeat"
            )
        logger.info("[WS] Background tasks started (batcher + heartbeat)")

    async def connect(
        self,
        websocket: WebSocket,
        command_filter: Optional[str],
        subprotocol: Optional[str] = None,
    ) -> None:
        """Accept a new client and register it with its command scope."""
        await websocket.accept(subprotocol=subprotocol)
        queue: asyncio.Queue = asyncio.Queue(maxsize=CLIENT_QUEUE_DEPTH)
        send_task = asyncio.create_task(
            self._client_send_loop(websocket, queue),
            name=f"ws-send-{id(websocket)}"
        )
        async with self._lock:
            self._clients[websocket] = queue
            self._send_tasks[websocket] = send_task
            self._last_pong[websocket] = asyncio.get_event_loop().time()
            self._client_commands[websocket] = command_filter
        logger.info(f"[WS] Client connected. Total: {len(self._clients)}")

    async def disconnect(self, websocket: WebSocket) -> None:
        """Clean up a disconnected or dead client."""
        async with self._lock:
            if websocket not in self._clients:
                return
            queue = self._clients.pop(websocket)
            task = self._send_tasks.pop(websocket, None)
            self._last_pong.pop(websocket, None)
            self._client_commands.pop(websocket, None)

        if task and not task.done():
            task.cancel()

        # Drain the queue so the send task unblocks if it's waiting
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        logger.info(f"[WS] Client disconnected. Remaining: {len(self._clients)}")

    def update_pong(self, websocket: WebSocket) -> None:
        """Record that we just heard from this client (pong or any message)."""
        self._last_pong[websocket] = asyncio.get_event_loop().time()

    async def _client_send_loop(self, websocket: WebSocket, queue: asyncio.Queue) -> None:
        """
        Per-client coroutine that drains the outbound queue and sends messages.
        Runs as a background task for the lifetime of the connection.
        Back-pressure: if the queue is full, the enqueue call drops the oldest
        message (telemetry) instead of blocking.
        """
        try:
            while True:
                message = await queue.get()
                if message is None:
                    # Sentinel — time to stop
                    break
                try:
                    await websocket.send_text(message)
                except Exception:
                    # Socket died — let the main receive loop detect it
                    break
        except asyncio.CancelledError:
            pass

    async def _enqueue(self, message: str, drop_if_full: bool = False, target_command_id: Optional[str] = None) -> None:
        """
        Enqueue a message for all connected clients.

        Args:
            message: JSON string to send.
            drop_if_full: If True, overwrite the oldest item in a full queue
                          rather than blocking. Use for telemetry (real-time
                          stale frames are worthless); False for critical events.
            target_command_id: If set, only enqueue for clients that have global access or match this command_id.
        """
        dead: Set[WebSocket] = set()
        async with self._lock:
            clients = list(self._clients.items())

        for ws, queue in clients:
            if target_command_id is not None:
                client_cmd = self._client_commands.get(ws)
                if client_cmd is not None and client_cmd != target_command_id:
                    continue
                    
            try:
                if drop_if_full and queue.full():
                    try:
                        queue.get_nowait()  # Drop oldest
                    except asyncio.QueueEmpty:
                        pass
                await asyncio.wait_for(queue.put(message), timeout=0.1)
            except (asyncio.TimeoutError, asyncio.QueueFull):
                logger.warning(f"[WS] Client queue full — dropping message for {id(ws)}")
            except Exception:
                dead.add(ws)

        for ws in dead:
            await self.disconnect(ws)

    # ── Telemetry batcher ────────────────────────────────────────────────────

    async def queue_telemetry(self, telemetry_data: dict) -> None:
        """
        Called by the telemetry ingest API on every frame.
        We store only the LATEST frame per camera; the batcher loop flushes
        all pending cameras every TELEMETRY_BATCH_INTERVAL seconds.

        60 FPS → 60 calls/s → batcher fires 10×/s → React renders at most 10×/s.
        """
        camera_id = telemetry_data.get("camera_id", "unknown")
        async with self._telemetry_lock:
            self._pending_telemetry[camera_id] = telemetry_data

    async def _telemetry_batch_loop(self) -> None:
        """
        Background task: every 100ms, flush the latest telemetry frame per
        camera to all connected clients as a single batched message.
        """
        global _telemetry_broadcasts
        while True:
            await asyncio.sleep(TELEMETRY_BATCH_INTERVAL)
            async with self._telemetry_lock:
                if not self._pending_telemetry:
                    continue
                batch = dict(self._pending_telemetry)
                self._pending_telemetry.clear()

            if not self._clients:
                continue

            _telemetry_broadcasts += len(batch)
            if _telemetry_broadcasts % 500 == 0:
                logger.info(f"[WS] Telemetry batched: {_telemetry_broadcasts} frames total, "
                            f"{len(self._clients)} clients")

            # One message per camera, tagged as live_telemetry
            for camera_id, tel in batch.items():
                message = json.dumps({
                    "type": "live_telemetry",
                    "telemetry": jsonable_encoder(tel),
                })
                # We need the owning_command_id of the camera to filter.
                camera_cmd = get_camera_command(camera_id)
                # drop_if_full=True: stale telemetry is worthless
                await self._enqueue(message, drop_if_full=True, target_command_id=camera_cmd)

    # ── Heartbeat / ping-pong ────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """
        Background task: every HEARTBEAT_INTERVAL seconds, ping all clients.
        Clients that haven't responded within PONG_TIMEOUT are killed.

        This detects dead TCP connections that haven't fired a WebSocketDisconnect
        (e.g. a mobile network going away mid-session, or a browser tab crash).
        Without this, dead clients accumulate indefinitely.
        """
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            now = asyncio.get_event_loop().time()

            async with self._lock:
                clients = list(self._clients.items())
                pong_times = dict(self._last_pong)

            dead: Set[WebSocket] = set()
            for ws, queue in clients:
                last_pong = pong_times.get(ws, now)
                if now - last_pong > HEARTBEAT_INTERVAL + PONG_TIMEOUT:
                    logger.warning(f"[WS] Client {id(ws)} timed out — no pong in "
                                   f"{now - last_pong:.1f}s. Disconnecting.")
                    dead.add(ws)
                else:
                    # Send ping
                    ping_msg = json.dumps({
                        "type": "ping",
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    try:
                        await asyncio.wait_for(queue.put(ping_msg), timeout=0.5)
                    except (asyncio.TimeoutError, asyncio.QueueFull):
                        dead.add(ws)

            for ws in dead:
                await self.disconnect(ws)


# ─── Singleton manager ───────────────────────────────────────────────────────

manager = ConnectionManager()
_telemetry_broadcasts = 0

_camera_command_cache: Dict[str, str] = {}
def get_camera_command(camera_id: str) -> Optional[str]:
    if camera_id in _camera_command_cache:
        return _camera_command_cache[camera_id]
    try:
        from backend.database.session import SessionLocal
        from backend.models.orm import Camera
        db = SessionLocal()
        cam = db.query(Camera).filter(Camera.id == camera_id).first()
        if cam:
            _camera_command_cache[camera_id] = cam.owning_command_id
            return cam.owning_command_id
        db.close()
    except Exception:
        pass
    return None


# ─── WebSocket endpoint ──────────────────────────────────────────────────────

@router.websocket("/ws/dashboard")
async def ws_dashboard(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """
    Live event stream for the NETRAKSH dashboard.
    Authentication is required. Browser clients provide the JWT as the second
    Sec-WebSocket-Protocol value after ``netraksh.jwt``. The query parameter is
    retained for compatibility, but the shipped frontend never uses it.
    
    Push-only: server → client. Any client message (e.g. pong) updates the
    liveness timestamp and is otherwise discarded.
    """
    offered_protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    negotiated_protocol = "netraksh.jwt" if "netraksh.jwt" in offered_protocols else None
    if token is None and negotiated_protocol is not None:
        protocol_index = offered_protocols.index("netraksh.jwt")
        if protocol_index + 1 < len(offered_protocols):
            token = offered_protocols[protocol_index + 1]

    if not token:
        await websocket.accept(subprotocol=negotiated_protocol)
        await websocket.send_text(json.dumps({"type": "auth_error", "detail": "Missing token"}))
        await websocket.close(code=4001)
        return

    try:
        # Validate JWT signature and expiration.
        payload = decode_token(token)
        role = payload.get("role")
        if role not in ("ADMIN", "OPERATOR", "AUDITOR"):
            raise ValueError("Insufficient privileges")
            
        command_filter = None
        if role == "OPERATOR":
            from backend.models.orm import User
            from backend.database.session import SessionLocal
            db = SessionLocal()
            try:
                # /auth/token stores the username in JWT ``sub``.  Looking it
                # up as a UUID made every valid operator token fail only after
                # login, causing the frontend's WebSocket auth-error handler
                # to clear an otherwise valid session.
                user = db.query(User).filter(User.username == payload.get("sub")).first()
                if user:
                    command_filter = get_command_filter(user)
                else:
                    raise ValueError("User not found")
            finally:
                db.close()
    except Exception as exc:
        await websocket.accept(subprotocol=negotiated_protocol)
        await websocket.send_text(json.dumps({"type": "auth_error", "detail": "Invalid or expired token"}))
        await websocket.close(code=4001)
        return

    await manager.connect(websocket, command_filter, subprotocol=negotiated_protocol)
    try:
        while True:
            try:
                # Receive and discard — updates pong timestamp so heartbeat
                # knows the client is alive. Timeout drives ping cadence.
                await asyncio.wait_for(websocket.receive_text(), timeout=HEARTBEAT_INTERVAL)
                manager.update_pong(websocket)
            except asyncio.TimeoutError:
                # No message from client — that's fine for a push-only channel.
                # The heartbeat loop will ping and track liveness independently.
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"[WS] Unexpected client error: {exc}")
    finally:
        await manager.disconnect(websocket)


# ─── Broadcast helpers (called by other routers) ─────────────────────────────

async def broadcast_event(event_data: dict) -> None:
    """Called when a new detection event is ingested."""
    message = json.dumps({
        "type": "new_event",
        "payload": jsonable_encoder(event_data),
        "timestamp": datetime.utcnow().isoformat(),
    })
    camera_id = event_data.get("camera_id")
    target_cmd = get_camera_command(camera_id) if camera_id else None
    await manager._enqueue(message, drop_if_full=False, target_command_id=target_cmd)


async def broadcast_alert(alert_data: dict) -> None:
    """Called by escalation service on a new alert."""
    message = json.dumps({
        "type": "new_alert",
        "alert": jsonable_encoder(alert_data),
        "timestamp": datetime.utcnow().isoformat(),
    })
    target_cmd = alert_data.get("command_id_receiving")
    await manager._enqueue(message, drop_if_full=False, target_command_id=target_cmd)


async def broadcast_camera_health(health_data: dict) -> None:
    """Called when camera health changes."""
    message = json.dumps({
        "type": "camera_health",
        "health": jsonable_encoder(health_data),
        "timestamp": datetime.utcnow().isoformat(),
    })
    await manager._enqueue(message, drop_if_full=False)


async def broadcast_metrics(metrics_data: dict) -> None:
    """Called when edge performance snapshot arrives."""
    message = json.dumps({
        "type": "pipeline_metrics",
        "metrics": jsonable_encoder(metrics_data),
        "timestamp": datetime.utcnow().isoformat(),
    })
    await manager._enqueue(message, drop_if_full=True)  # Metrics: drop if slow


async def broadcast_telemetry(telemetry_data: dict) -> None:
    """
    Called on every telemetry frame from the edge.
    DOES NOT send immediately — queues for the 100ms batcher instead.
    This is the primary performance improvement over the original implementation.
    """
    await manager.queue_telemetry(telemetry_data)


async def broadcast_correlation(correlation_data: dict) -> None:
    """Push a typed corroboration state change to dashboard clients."""
    message = json.dumps({
        "type": "correlation",
        "data": jsonable_encoder(correlation_data),
        "timestamp": datetime.utcnow().isoformat(),
    })
    await manager._enqueue(message, drop_if_full=False)
