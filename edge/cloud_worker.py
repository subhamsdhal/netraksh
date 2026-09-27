"""Unattended cloud edge worker for a free Render web service.

The HTTP listener binds immediately so Render can wake and health-check the
service. The AI pipeline starts in a separate thread after the listener is
available; no local terminal or interactive input is required.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

logger = logging.getLogger("netraksh.cloud_worker")

_state = {
    "started_at": time.time(),
    "worker_started_at": None,
    "worker_alive": False,
    "last_error": None,
}


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not configured")
    return value


def _preflight(backend_url: str, camera_id: str, token: str) -> None:
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        client.get(f"{backend_url}/health").raise_for_status()
        client.get(
            f"{backend_url}/api/dashboard/video/internal-sync",
            params={"camera_id": camera_id},
            headers={"Authorization": f"Bearer {token}"},
        ).raise_for_status()


def _run_edge() -> None:
    camera_id = _required("CAMERA_ID")
    backend_url = _required("BACKEND_URL").rstrip("/")
    token = _required("EDGE_AUTH_TOKEN")
    video_source = os.environ.get("VIDEO_SOURCE", "demo/videos/uploaded_demo.mp4")
    zones = os.environ.get("ZONES_CONFIG_PATH", "demo/scripts/zones_config.json")
    retry_seconds = max(5.0, float(os.environ.get("EDGE_RESTART_DELAY_SECONDS", "10")))

    while True:
        try:
            # Delay the pipeline import until after the HTTP listener is up.
            from edge.demo_runner import run_demo_pipeline
            from edge.runtime_diagnostics import log_runtime_checkpoint
            log_runtime_checkpoint("demo_runner_imported")

            _preflight(backend_url, camera_id, token)
            _state["worker_started_at"] = time.time()
            _state["worker_alive"] = True
            _state["last_error"] = None
            run_demo_pipeline(
                camera_id=camera_id,
                video_source=video_source,
                backend_url=backend_url,
                zones_config_path=zones,
            )
            logger.warning("[CloudWorker] Edge loop exited; restarting in %.1fs", retry_seconds)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # Keep health output and logs free of credentials or signed URLs.
            _state["last_error"] = type(exc).__name__
            logger.error("[CloudWorker] Edge cycle failed (%s); retrying in %.1fs", type(exc).__name__, retry_seconds)
        finally:
            _state["worker_alive"] = False
        time.sleep(retry_seconds)


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "NETRAKSH-CloudEdge/1.0"

    def _send(self, status: int = 200) -> None:
        payload = {
            "service": "NETRAKSH Cloud Edge",
            "status": "ok" if _state["worker_alive"] else "starting",
            "camera_id": os.environ.get("CAMERA_ID", "unknown"),
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

    def do_HEAD(self) -> None:
        if self.path in ("/", "/health", "/wake"):
            self.send_response(200)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        logger.info("[HTTP] " + fmt, *args)


class CloudHealthServer(ThreadingHTTPServer):
    # Permit a clean Render restart to reclaim the service port immediately.
    allow_reuse_address = True


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s | %(levelname)-8s | [cloud-edge] %(name)s | %(message)s",
    )
    port = int(os.environ.get("PORT", "10000"))
    server = CloudHealthServer(("0.0.0.0", port), HealthHandler)
    logger.info("[CloudWorker] Health listener bound on 0.0.0.0:%s", port)
    thread = threading.Thread(target=_run_edge, daemon=True, name="netraksh-edge")
    thread.start()
    # No optional imports or inference setup are allowed between a successful
    # bind and serve_forever: Render's scanner must keep seeing this listener
    # even when the idle AI thread later fails or retries.
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
