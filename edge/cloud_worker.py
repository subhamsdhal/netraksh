"""NETRAKSH cloud edge wrapper for free Render web-service deployments.

The actual AI pipeline remains edge.demo_runner/EdgePipeline. This module only
adds a tiny HTTP listener so Render can host the long-running worker as a web
service and wake it on demand. Heavy imports happen in the worker thread after
the listener is bound, which keeps cold-start health checks responsive.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("netraksh.cloud_worker")

_state = {
    "started_at": time.time(),
    "worker_started_at": None,
    "worker_alive": False,
    "last_error": None,
}


def _materialize_cloud_keys(camera_id: str) -> None:
    """Write stable cloud edge keys supplied through Render secret env vars."""
    key_dir = os.environ.get("EDGE_KEY_DIR", "certs/edge")
    os.makedirs(key_dir, exist_ok=True)
    private_b64 = os.environ.get("EDGE_PRIVATE_KEY_B64", "").strip()
    aes_b64 = os.environ.get("EDGE_EVIDENCE_KEY_B64", "").strip()
    private_path = os.path.join(key_dir, f"{camera_id}.key")
    aes_path = os.path.join(key_dir, f"{camera_id}.aes")

    if private_b64 and aes_b64:
        private_bytes = base64.b64decode(private_b64)
        aes_bytes = base64.b64decode(aes_b64)
    else:
        # Free-tier fallback: derive stable, domain-separated edge key
        # material from the already-required high-entropy EDGE_AUTH_TOKEN.
        # Nothing is committed and cold starts retain the same identity.
        token = os.environ.get("EDGE_AUTH_TOKEN", "")
        if not token:
            raise RuntimeError("EDGE_AUTH_TOKEN is required")
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        seed = hashlib.sha256(("netraksh-ed25519:" + token + ":" + camera_id).encode()).digest()
        private_key = Ed25519PrivateKey.from_private_bytes(seed)
        private_bytes = private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        aes_bytes = hashlib.sha256(("netraksh-aes256:" + token + ":" + camera_id).encode()).digest()

    if len(aes_bytes) != 32:
        raise RuntimeError("Evidence key must be exactly 32 bytes")

    with open(private_path, "wb") as fh:
        fh.write(private_bytes)
    with open(aes_path, "wb") as fh:
        fh.write(aes_bytes)
    try:
        os.chmod(private_path, 0o600)
        os.chmod(aes_path, 0o600)
    except OSError:
        pass


def _run_edge() -> None:
    camera_id = os.environ.get("CAMERA_ID", "cam-border-01")
    video_source = os.environ.get("VIDEO_SOURCE", "demo/videos/uploaded_demo.mp4")
    backend_url = os.environ.get("BACKEND_URL", "https://netraksh.onrender.com")
    zones = os.environ.get("ZONES_CONFIG_PATH", "demo/scripts/zones_config.json")
    _materialize_cloud_keys(camera_id)

    while True:
        try:
            _state["worker_started_at"] = time.time()
            _state["worker_alive"] = True
            _state["last_error"] = None
            # Heavy imports intentionally happen only after the HTTP listener
            # is up, so a sleeping free Render service can wake promptly.
            from edge.demo_runner import run_demo_pipeline
            run_demo_pipeline(
                camera_id=camera_id,
                video_source=video_source,
                backend_url=backend_url,
                zones_config_path=zones,
            )
            logger.warning("[CloudWorker] Edge loop exited; restarting in 3s")
        except Exception as exc:
            _state["last_error"] = f"{type(exc).__name__}: {exc}"
            logger.exception("[CloudWorker] Edge loop failed")
        finally:
            _state["worker_alive"] = False
        time.sleep(3.0)


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "NETRAKSH-CloudEdge/1.0"

    def _send(self, status: int = 200) -> None:
        payload = {
            "service": "NETRAKSH Cloud Edge",
            "status": "ok" if _state["worker_alive"] else "starting",
            "camera_id": os.environ.get("CAMERA_ID", "cam-border-01"),
            "worker_alive": bool(_state["worker_alive"]),
            "uptime_seconds": round(time.time() - float(_state["started_at"]), 1),
            "last_error": _state["last_error"],
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in ("/", "/health", "/wake"):
            self._send(200)
        else:
            self._send(404)

    def log_message(self, fmt: str, *args) -> None:
        logger.info("[HTTP] " + fmt, *args)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    port = int(os.environ.get("PORT", "10000"))
    thread = threading.Thread(target=_run_edge, daemon=True, name="netraksh-edge")
    thread.start()

    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    logger.info("[CloudWorker] Health listener bound on 0.0.0.0:%s", port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
