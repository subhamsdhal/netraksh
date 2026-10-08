"""Unattended cloud edge worker for a free Render web service.

The HTTP listener binds immediately so Render can wake and health-check the
service. The AI pipeline starts in a separate thread after the listener is
available; no local terminal or interactive input is required.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

logger = logging.getLogger("netraksh.cloud_worker")

_state = {
    "started_at": time.time(),
    "boot_id": str(uuid.uuid4()),
    "instance_id": (os.environ.get("RENDER_INSTANCE_ID") or os.environ.get("HOSTNAME") or "")[:128],
    "analysis_phase": "IDLE",
    "pipeline": None,
    "worker_started_at": None,
    "worker_alive": False,
    "last_error": None,
    "phase": "WAITING_BACKEND",
}


def _set_run_state(phase: str, pipeline) -> None:
    _state["analysis_phase"] = phase
    _state["pipeline"] = pipeline
    logger.info(
        "[WorkerLease] run_state camera_id=%s boot_id=%s phase=%s run_id=%s generation=%s last_frame=%s",
        os.environ.get("CAMERA_ID", "unknown"), _state["boot_id"], phase,
        getattr(pipeline, "stream_id", None), getattr(pipeline, "analysis_generation", None),
        getattr(pipeline, "_last_processed_frame_index", None),
    )


def _heartbeat_payload(camera_id: str) -> dict:
    pipeline = _state["pipeline"]
    phase = _state["analysis_phase"] if pipeline is not None else "IDLE"
    payload = {
        "camera_id": camera_id,
        "boot_id": _state["boot_id"],
        "instance_id": _state["instance_id"],
        "worker_started_at": _state["started_at"],
        "phase": phase,
    }
    if pipeline is not None:
        payload.update({
            "analysis_session_id": pipeline.stream_id,
            "stream_id": pipeline.source_stream_id,
            "analysis_generation": pipeline.analysis_generation,
            "last_frame_index": getattr(pipeline, "_last_processed_frame_index", None),
            "last_video_time": getattr(pipeline, "_last_video_time", None),
        })
    return payload


def _heartbeat_loop() -> None:
    """Best-effort bounded ownership signal, independent of image inference."""
    camera_id = _required("CAMERA_ID")
    backend_url = _required("BACKEND_URL").rstrip("/")
    token = _required("EDGE_AUTH_TOKEN")
    failures = 0
    last_logged_frame = None
    with httpx.Client(timeout=httpx.Timeout(connect=3, read=5, write=5, pool=3)) as client:
        while True:
            payload = _heartbeat_payload(camera_id)
            try:
                response = client.post(
                    f"{backend_url}/api/dashboard/video/internal-worker-heartbeat",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )
                if response.status_code != 200:
                    failures += 1
                    logger.warning(
                        "[WorkerLease] heartbeat rejected camera_id=%s boot_id=%s phase=%s status=%s retry=%s",
                        camera_id, _state["boot_id"], payload["phase"], response.status_code, failures,
                    )
                else:
                    if failures or payload.get("last_frame_index") != last_logged_frame:
                        logger.info(
                            "[WorkerLease] heartbeat accepted camera_id=%s boot_id=%s instance_id=%s phase=%s run_id=%s generation=%s last_frame=%s last_video_time=%s recovered_after=%s",
                            camera_id, _state["boot_id"], _state["instance_id"], payload["phase"],
                            payload.get("analysis_session_id"), payload.get("analysis_generation"),
                            payload.get("last_frame_index"), payload.get("last_video_time"), failures,
                        )
                    last_logged_frame = payload.get("last_frame_index")
                    failures = 0
            except httpx.RequestError as exc:
                failures += 1
                logger.warning(
                    "[WorkerLease] heartbeat transport error camera_id=%s boot_id=%s phase=%s error_type=%s retry=%s",
                    camera_id, _state["boot_id"], payload["phase"], type(exc).__name__, failures,
                )
            time.sleep(min(5 * (2 ** min(failures, 3)), 30) if failures else 5)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not configured")
    return value


def _preflight(backend_url: str, camera_id: str, token: str) -> None:
    deadline_seconds = max(1.0, float(os.environ.get("EDGE_BACKEND_PREFLIGHT_DEADLINE_SECONDS", "110")))
    retry_seconds = max(0.1, float(os.environ.get("EDGE_BACKEND_PREFLIGHT_RETRY_SECONDS", "1.5")))
    deadline = time.monotonic() + deadline_seconds
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    last_error: Exception | None = None
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while True:
            _state["phase"] = "WAITING_BACKEND"
            try:
                ready_response = client.get(f"{backend_url}/ready")
                ready_response.raise_for_status()
                ready_payload = ready_response.json()
                if not (
                    isinstance(ready_payload, dict)
                    and ready_payload.get("status") == "ready"
                    and ready_payload.get("database") == "connected"
                ):
                    raise RuntimeError("Backend readiness contract is not satisfied")

                sync_response = client.get(
                    f"{backend_url}/api/dashboard/video/internal-sync",
                    params={"camera_id": camera_id},
                    headers={"Authorization": f"Bearer {token}"},
                )
                # Authentication/configuration errors are not cold-start
                # transients. Fail immediately into the existing outer loop.
                if sync_response.status_code in {401, 403}:
                    raise PermissionError("Edge backend authentication rejected")
                sync_response.raise_for_status()
                _state["phase"] = "READY"
                return
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                last_error = exc

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Backend preflight deadline exceeded") from last_error
            time.sleep(min(retry_seconds, remaining))


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

            _state["phase"] = "WAITING_BACKEND"
            _preflight(backend_url, camera_id, token)
            _state["worker_started_at"] = time.time()
            _state["worker_alive"] = True
            _state["last_error"] = None
            _state["phase"] = "READY"
            run_demo_pipeline(
                camera_id=camera_id,
                video_source=video_source,
                backend_url=backend_url,
                zones_config_path=zones,
                require_explicit_session=True,
                on_run_state=_set_run_state,
            )
            logger.warning("[CloudWorker] Edge loop exited; restarting in %.1fs", retry_seconds)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # Keep health output and logs free of credentials or signed URLs.
            _state["last_error"] = type(exc).__name__
            _state["phase"] = "RETRYING"
            logger.error("[CloudWorker] Edge cycle failed (%s); retrying in %.1fs", type(exc).__name__, retry_seconds)
        finally:
            _state["worker_alive"] = False
            _set_run_state("IDLE", None)
        time.sleep(retry_seconds)


class HealthHandler(BaseHTTPRequestHandler):
    server_version = "NETRAKSH-CloudEdge/1.0"

    def _send(self, status: int = 200) -> None:
        constrained = os.environ.get("EDGE_CONSTRAINED_CLOUD", "true").lower() == "true"
        ocr_backend = os.environ.get("ANPR_OCR_BACKEND", "disabled" if constrained else "easyocr").lower()
        payload = {
            "service": "NETRAKSH Cloud Edge",
            "status": "ok" if _state["worker_alive"] else "starting",
            "camera_id": os.environ.get("CAMERA_ID", "unknown"),
            "worker_alive": bool(_state["worker_alive"]),
            "uptime_seconds": round(time.time() - float(_state["started_at"]), 1),
            "last_error": _state["last_error"],
            "phase": _state["phase"],
            "capabilities": {
                "detector_runtime": os.environ.get("DETECTOR_RUNTIME", "unknown"),
                "tracking": "BYTE_TRACK",
                "line_and_fence_events": True,
                "anpr_localization": True,
                "anpr_ocr": ocr_backend != "disabled",
                "anpr_ocr_backend": ocr_backend,
                "face_recognition_engine": os.environ.get("FACE_RECOGNITION_ENGINE", "lbph").lower(),
                "behavior_analytics": os.environ.get("BEHAVIOR_ANALYTICS", "false").lower() == "true",
            },
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
    # httpx INFO includes full signed media URLs, which contain one-time
    # access parameters. Never expose them in production logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    port = int(os.environ.get("PORT", "10000"))
    server = CloudHealthServer(("0.0.0.0", port), HealthHandler)
    logger.info("[CloudWorker] Health listener bound on 0.0.0.0:%s", port)
    logger.info(
        "[WorkerLease] process boot camera_id=%s boot_id=%s instance_id=%s pid=%s",
        os.environ.get("CAMERA_ID", "unknown"), _state["boot_id"], _state["instance_id"], os.getpid(),
    )
    def _shutdown_signal(signum, _frame):
        pipeline = _state["pipeline"]
        logger.warning(
            "[WorkerLease] process shutdown signal=%s camera_id=%s boot_id=%s phase=%s run_id=%s last_frame=%s last_video_time=%s",
            signum, os.environ.get("CAMERA_ID", "unknown"), _state["boot_id"],
            _state["analysis_phase"], getattr(pipeline, "stream_id", None),
            getattr(pipeline, "_last_processed_frame_index", None),
            getattr(pipeline, "_last_video_time", None),
        )
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _shutdown_signal)
    signal.signal(signal.SIGINT, _shutdown_signal)
    threading.Thread(target=_heartbeat_loop, daemon=True, name="worker-lease-heartbeat").start()
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
