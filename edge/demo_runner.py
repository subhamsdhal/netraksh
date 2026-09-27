"""
NETRAKSH Edge — Demo Runner (SIH 2026 prototype).

A thin wrapper around EdgePipeline that:
  1. Reads CAMERA_ID / VIDEO_SOURCE / BACKEND_URL from env vars
     (or --camera-id / --video-source CLI args), so start_netraksh.cmd
     can launch two separate, named camera processes without a config file.
  2. Polls GET /demo/scenario every 5 s and applies scenario effects to
     the live pipeline — using ONLY the existing CameraAdapter flags and
     SyncClient behaviour, no new queuing or detection logic.

Scenario reactions (honest scope — what each one actually does):

  normal  → no modifications; simulation flags cleared on next 5s poll.

  fog     → inject a Gaussian-blurred, contrast-reduced copy of each frame
             into the pipeline so SceneConditionClassifier naturally reads
             low contrast_std and classifies FOG_RAIN → S drops → R may
             fall below RELIABILITY_R_THRESHOLD (0.75) → UNCERTAIN.
             The original frame is not modified for evidence snapshots —
             fog simulation only affects detection/health inputs.

  failure → set a module-level flag that makes the adapter's next ~60s of
             frames appear frozen (all identical single grey value).
             CameraHealthMonitor's own frozen-frame detector (pixel-variance
             check in edge/health/camera_health.py) fires health_state=FAILED
             → Gate 1 hard-override → ABSTAIN.
             We do NOT manually write health_state — the existing monitor
             decides on its own, from the frame data.

  offline → calls sync_client.set_simulate_offline(True), which already
             exists on SyncClient (edge/sync/sync_client.py:265).  The sync
             loop continues running and events continue to be enqueued, but
             outbound POST /events calls are skipped → /sync/status shows
             BUFFERING.  Calling set_simulate_offline(False) on scenario
             'normal' resumes draining the queue.

None of these flags retroactively alter already-signed evidence packages.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import cv2
import numpy as np

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edge.main import EdgePipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level scenario state — set by the polling thread, read by
# _process_frame in the main thread.  Python dict writes are atomic under
# the GIL for single-key updates.
# ---------------------------------------------------------------------------
_scenario: dict = {
    "current": "normal",
    "video_source": None,
    "video_session_id": None,
    "should_restart": False,
    "initialized": False,
}

# How long (seconds) a single 'failure' trigger keeps frozen frames active
# before auto-resetting so the demo doesn't get permanently stuck.
_FAILURE_DURATION_S = 60.0
_failure_until: float = 0.0


def _is_resolvable_edge_source(source: object) -> bool:
    """Return whether a dashboard-requested source can be opened by this edge.

    Dashboard uploads are stored on the control-plane filesystem.  Their
    repository-relative paths are meaningful to Render, but not necessarily to
    an independently running edge device.  A local CLI source therefore stays
    authoritative unless the requested replacement is a file on this edge, a
    local capture device, or a supported stream URL.
    """
    value = str(source or "").strip()
    if not value:
        return False
    if value.lower() in {"0", "1", "2", "webcam", "usb", "usb_camera"}:
        return True
    if urlparse(value).scheme.lower() in {"http", "https", "rtsp", "rtsps"}:
        return True
    return Path(value).is_file()


def _runtime_state_paths(
    camera_id: str,
    backend_url: str,
    session_id: Optional[str] = None,
) -> dict[str, str]:
    """Build backend-scoped durable state paths for one edge camera.

    A retry outbox is durable only for the deployment that accepted its
    records.  Namespace it by a stable digest of the configured backend origin
    so records created for localhost or another deployment cannot be replayed
    to a newly selected backend.
    """
    parsed = urlparse(backend_url.strip())
    origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    scope = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:12]
    session_suffix = f"_{session_id}" if session_id else ""
    runtime_root = Path(os.environ.get("EDGE_RUNTIME_DIR", "edge/data"))
    return {
        "chain_db_path": str(runtime_root / f"chain_{camera_id}_{scope}.db"),
        "sync_db_path": str(runtime_root / f"sync_{camera_id}_{scope}{session_suffix}.db"),
        "clip_dir": str(runtime_root / "clips" / f"{camera_id}_{scope}"),
        "metrics_json_path": str(runtime_root / f"metrics_{camera_id}_{scope}.json"),
    }


def _materialize_remote_source(data: dict, camera_id: str) -> dict:
    """Download a signed object URL into the worker's durable source cache.

    The logical object reference remains server-side state.  A deterministic
    per-session filename prevents a newly generated signed URL on each poll
    from looking like a new source and restarting the pipeline.
    """
    if data.get("source_mode") == "bundled":
        bundled = dict(data)
        bundled["video_source"] = "demo/videos/uploaded_demo.mp4"
        bundled["video_session_id"] = None
        bundled.pop("download_url", None)
        return bundled
    download_url = str(data.get("download_url") or "").strip()
    session_id = str(data.get("video_session_id") or "").strip()
    if not download_url or not session_id:
        return data
    try:
        session_id = str(__import__("uuid").UUID(session_id))
    except (ValueError, AttributeError):
        logger.warning("[DemoRunner] Ignoring remote source with invalid session ID")
        return data
    safe_source_name = str(data.get("source_name") or "normalized upload").replace("\r", " ").replace("\n", " ")[:160]

    logical_source = str(data.get("video_source") or "").removeprefix("object://")
    parsed = urlparse(download_url)
    suffix = Path(logical_source).suffix.lower() or Path(parsed.path).suffix.lower()
    if suffix not in {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}:
        suffix = ".video"
    cache_root = Path(
        os.environ.get(
            "EDGE_SOURCE_CACHE_DIR",
            str(Path(os.environ.get("EDGE_RUNTIME_DIR", "edge/data")) / "sources"),
        )
    )
    destination = cache_root / camera_id / f"{session_id}{suffix}"
    if destination.is_file() and destination.stat().st_size > 0:
        hydrated = dict(data)
        hydrated["video_source"] = str(destination)
        logger.info(
            "[DemoRunner] Durable source cache ready camera_id=%s session=%s source=%s",
            camera_id,
            session_id[:8],
            safe_source_name,
        )
        return hydrated

    destination.parent.mkdir(parents=True, exist_ok=True)
    part_path = destination.with_suffix(destination.suffix + ".part")
    max_bytes = int(os.environ.get("EDGE_MAX_SOURCE_BYTES", str(500 * 1024 * 1024)))
    try:
        import httpx

        timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        total = 0
        with httpx.stream("GET", download_url, timeout=timeout, follow_redirects=True) as response:
            response.raise_for_status()
            with open(part_path, "wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("remote video exceeds EDGE_MAX_SOURCE_BYTES")
                    handle.write(chunk)
        if total == 0:
            raise ValueError("remote video is empty")
        os.replace(part_path, destination)
    except Exception as exc:
        part_path.unlink(missing_ok=True)
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning(
            "[DemoRunner] Remote source download failed: %s%s",
            type(exc).__name__,
            f" (HTTP {status_code})" if status_code is not None else "",
        )
        unavailable = dict(data)
        unavailable["source_unavailable"] = True
        unavailable["video_source"] = None
        unavailable.pop("download_url", None)
        return unavailable
    hydrated = dict(data)
    hydrated["video_source"] = str(destination)
    logger.info(
        "[DemoRunner] Durable source downloaded camera_id=%s session=%s source=%s",
        camera_id,
        session_id[:8],
        safe_source_name,
    )
    return hydrated


def _control_seek_target(
    requested_time: object,
    source_kind: str,
    duration_seconds: Optional[float],
) -> Optional[float]:
    """Return a valid explicit control-plane seek target, if any.

    The browser reports an absolute media position every few seconds; it is
    not a durable wall-clock from which an edge process may extrapolate after
    the browser stops reporting.  Finite media additionally cannot accept an
    out-of-range seek.  ``None`` means wait for a fresh, valid control update
    while local decoding continues from its current position.
    """
    try:
        target = float(requested_time)
    except (TypeError, ValueError):
        return None
    if target < 0:
        return None
    if source_kind == "LOCAL_FINITE_FILE":
        if duration_seconds is None:
            return None
        if target >= duration_seconds:
            return None
    return target


def _apply_control_sync(data: dict) -> bool:
    """Atomically apply a resolvable control-plane video session.

    Playback time and pause state belong to the session that supplied the
    source.  If that source cannot exist on this edge, none of its session
    state may steer the configured local source.
    """
    source_mode = data.get("source_mode")
    new_source = data.get("video_source")
    new_session_id = None if source_mode == "bundled" else data.get("video_session_id")
    rejected_key = (str(new_source), str(new_session_id))

    if source_mode == "durable" and data.get("source_unavailable"):
        if _scenario.get("rejected_source_session") != rejected_key:
            logger.warning(
                "[DemoRunner] Durable source is unavailable; pausing instead of processing a fallback source"
            )
            _scenario["rejected_source_session"] = rejected_key
        _scenario["current"] = "paused"
        _scenario["video_session_id"] = new_session_id
        return False

    if new_source and not _is_resolvable_edge_source(new_source):
        if _scenario.get("rejected_source_session") != rejected_key:
            logger.warning(
                "[DemoRunner] Ignoring unavailable control-plane source/session; "
                "no source change applied"
            )
            _scenario["rejected_source_session"] = rejected_key
        return False

    if new_session_id and not new_source:
        if _scenario.get("rejected_source_session") != rejected_key:
            logger.warning(
                "[DemoRunner] Ignoring control-plane session without a resolvable source"
            )
            _scenario["rejected_source_session"] = rejected_key
        return False

    _scenario.pop("rejected_source_session", None)
    new_scenario = data.get("scenario", "normal")
    new_video_time = data.get("video_time")

    if new_scenario != _scenario.get("current"):
        logger.info("[DemoRunner] Scenario changed: %s → %s", _scenario.get("current"), new_scenario)
        _scenario["current"] = new_scenario
    if new_video_time is not None:
        _scenario["video_time"] = float(new_video_time)
    if "video_time_updated_at" in data:
        _scenario["video_time_updated_at"] = float(data["video_time_updated_at"])
    elif new_video_time is not None:
        _scenario["video_time_updated_at"] = time.time()

    had_source = bool(_scenario.get("video_source"))
    if new_source and (
        new_source != _scenario.get("video_source")
        or (new_session_id and new_session_id != _scenario.get("video_session_id"))
    ):
        if had_source:
            logger.info("[DemoRunner] Video source/session changed; triggering restart")
            _scenario["should_restart"] = True
        _scenario["video_source"] = new_source
    if source_mode == "bundled":
        _scenario["video_session_id"] = None
    elif new_session_id:
        _scenario["video_session_id"] = new_session_id
    return True


def _poll_scenario(backend_url: str, camera_id: str, interval: float = 5.0) -> None:
    """
    Background thread: poll GET /demo/scenario every `interval` seconds
    and update _scenario["current"].  Non-fatal on any network error.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("[DemoRunner] httpx not installed — scenario poll disabled")
        return
    while True:
        try:
            token = os.environ.get("EDGE_AUTH_TOKEN", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            resp = httpx.get(
                f"{backend_url}/api/dashboard/video/internal-sync",
                params={"camera_id": camera_id},
                headers=headers,
                timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            )
            if resp.status_code == 200:
                _apply_control_sync(_materialize_remote_source(resp.json(), camera_id))
                _scenario["initialized"] = True
        except Exception as exc:
            logger.debug(f"[DemoRunner] Scenario poll failed (non-fatal): {exc}")
        time.sleep(interval)


def apply_fog(frame: np.ndarray) -> np.ndarray:
    """
    Apply realistic fog simulation to a frame so SceneConditionClassifier
    naturally reads FOG_RAIN (low contrast_std, reduced brightness mean).

    Step 1: Gaussian blur reduces Laplacian variance (SceneConditionClassifier
            uses contrast_std from the blurred LAB L-channel).
    Step 2: Blend with a grey haze to further reduce contrast_std and pull
            brightness_mean toward a mid-grey, away from the clear-day ideal.

    No OpenCV functions beyond GaussianBlur/addWeighted — existing dependencies.
    """
    blurred = cv2.GaussianBlur(frame, (25, 25), 0)
    haze = np.full_like(frame, 180, dtype=np.uint8)
    fogged = cv2.addWeighted(blurred, 0.55, haze, 0.45, 0)
    return fogged


class DemoAwareEdgePipeline(EdgePipeline):
    """
    Subclass of EdgePipeline that intercepts _process_frame to apply
    scenario effects.  Everything else — reliability, evidence packaging,
    evidence chain, sync — is inherited untouched from EdgePipeline.
    """

    def __init__(self, config: dict):
        super().__init__(config)

        self._vtest_cache = None
        self._cache_cursor = 0
        if "vtest.mp4" in config.get("video_source", ""):
            cache_path = Path("demo/videos/vtest_telemetry.json")
            if cache_path.exists():
                import json
                try:
                    with open(cache_path, "r") as f:
                        self._vtest_cache = json.load(f)
                    logger.info(f"[DemoRunner] Loaded {len(self._vtest_cache)} frames of deterministic telemetry for vtest.mp4")
                    
                    # self._original_detect = self.detector.detect_and_track
                    # def _mock_detect(frame, condition, confidence_threshold, existing_trajectories=None):
                    #     return self._get_cached_tracks()
                    # self.detector.detect_and_track = _mock_detect
                except Exception as e:
                    logger.error(f"[DemoRunner] Failed to load vtest telemetry cache: {e}")

    def _get_cached_tracks(self):
        browser_time = _scenario.get("video_time", 0.0)
        browser_updated = _scenario.get("video_time_updated_at", time.time())
        is_paused = _scenario.get("current") == "paused"

        if is_paused:
            video_time = browser_time
        else:
            video_time = browser_time + (time.time() - browser_updated)
        
        if not self._vtest_cache:
            return []
            
        # Fast linear search from cursor since time moves forward monotonically mostly
        closest = self._vtest_cache[self._cache_cursor]
        min_diff = abs(closest["video_time"] - video_time)
        
        for i in range(self._cache_cursor, len(self._vtest_cache)):
            diff = abs(self._vtest_cache[i]["video_time"] - video_time)
            if diff < min_diff:
                min_diff = diff
                closest = self._vtest_cache[i]
                self._cache_cursor = i
            elif diff > min_diff:
                # Diff is increasing, we passed the minimum
                break
                
        # If time wrapped around (seek backwards), reset cursor
        if video_time < closest["video_time"] - 1.0:
            self._cache_cursor = 0
            
        from shared.schemas import TrackData, BoundingBox
        from shared.constants import DetectionClass
        
        tracks = []
        for t in closest["tracks"]:
            cls_map = {"person": DetectionClass.PERSON, "vehicle": DetectionClass.VEHICLE}
            det_class = cls_map.get(t["detection_class"], DetectionClass.UNKNOWN)
            
            w = getattr(self, "_last_frame_width", 768)
            h = getattr(self, "_last_frame_height", 576)
            
            bbox = BoundingBox(
                x1=t["bbox_x"] * w,
                y1=t["bbox_y"] * h,
                x2=(t["bbox_x"] + t["bbox_w"]) * w,
                y2=(t["bbox_y"] + t["bbox_h"]) * h
            )
            
            traj = []
            if hasattr(self, "_trajectories") and t["track_id"] in self._trajectories:
                traj = list(self._trajectories[t["track_id"]])
            traj.append(bbox.centroid)
            if len(traj) > 50:
                traj = traj[-50:]
            
            tracks.append(TrackData(
                track_id=t["track_id"],
                detection_class=det_class,
                bbox=bbox,
                confidence=t["confidence"],
                trajectory=traj
            ))
            
        return tracks

    def _notify_backend_normal(self) -> None:
        try:
            import httpx
            import os
            headers = {}
            token = self.config.get("edge_auth_token", os.environ.get("EDGE_AUTH_TOKEN"))
            if token:
                headers["Authorization"] = f"Bearer {token}"
            httpx.post(f"{self.config['backend_url']}/demo/scenario", json={"scenario": "normal"}, headers=headers, timeout=1.0)
        except Exception as exc:
            logger.debug(f"[DemoRunner] Auto-reset POST failed (non-fatal): {exc}")

    def _process_frame(self, frame: np.ndarray, meta) -> None:
        """
        Apply scenario effects before delegating to the real pipeline.

        failure: replace frame with a constant grey so the pixel-variance
                 check in CameraHealthMonitor (edge/health/camera_health.py)
                 reads near-zero variance → FAILED → Gate 1 → ABSTAIN.
                 We do not set health_state manually.

        fog:     replace frame with a fog-blurred+hazed copy.
                 SceneConditionClassifier computes low contrast_std → FOG_RAIN
                 → S component of R drops → R may fall below 0.75 → UNCERTAIN.

        offline: frame passes through unchanged.  Offline effect is on the
                 sync layer, not the frame layer (see start() below).

        normal:  frame passes through unchanged.
        """
        global _failure_until
        scenario = _scenario["current"]

        # -------------------------------------------------------------
        # SYNCHRONIZATION FIX:
        # Override OpenCV's internal video_time with the authoritative
        # extrapolated browser clock so that telemetry payloads match exactly.
        # -------------------------------------------------------------
        if os.environ.get("DEMO_LOOP_VIDEO", "true").lower() != "true":
            browser_time = _scenario.get("video_time", 0.0)
            browser_updated = _scenario.get("video_time_updated_at", time.time())
            if scenario == "paused":
                current_time = browser_time
            else:
                current_time = browser_time + (time.time() - browser_updated)
            meta.video_time_seconds = current_time

        if scenario == "failure":
            now = time.time()
            if _failure_until == 0.0:
                _failure_until = now + _FAILURE_DURATION_S
                logger.info(
                    "[DemoRunner] scenario=failure — injecting frozen grey frames "
                    "for ~60s so CameraHealthMonitor detects FAILED"
                )
            
            if now > _failure_until:
                logger.info("[DemoRunner] Auto-resetting failure scenario to normal after 60s")
                _scenario["current"] = "normal"
                _failure_until = 0.0
                threading.Thread(target=self._notify_backend_normal, daemon=True).start()
                super()._process_frame(frame, meta)
            else:
                # Constant grey → near-zero pixel variance → CameraHealthMonitor
                # detects frozen stream → health_state=FAILED → Gate 1 → ABSTAIN
                frozen = np.full_like(frame, 80, dtype=np.uint8)
                super()._process_frame(frozen, meta)

        elif scenario == "fog":
            _failure_until = 0.0
            fog_frame = apply_fog(frame)
            # fog_frame is used for detection/health — evidence snapshot uses
            # the ORIGINAL frame via the real packager (same as CLAHE branch
            # in edge/main.py::_process_frame, which keeps original frame for
            # evidence while using detection_frame for YOLO).
            super()._process_frame(fog_frame, meta)

        elif scenario == "paused":
            _failure_until = 0.0
            # Frame passes through, but adapter is paused so it just spins on old frames
            # or doesn't produce any new ones. We skip YOLO/tracking and telemetry here
            # so that no new events are generated while the video is paused.
            pass

        else:
            _failure_until = 0.0
            # normal / offline — pass frame through unchanged
            super()._process_frame(frame, meta)

    def start(self) -> None:
        """
        Override start() to additionally:
        - Watch _scenario and drive sync_client.set_simulate_offline()
          so the 'offline' scenario uses the existing sync API, not a hack.
        """
        # Monitor scenario changes and update the sync client's offline flag.
        # This runs in a daemon thread alongside the real sync loop thread
        # that EdgePipeline.start() itself will spawn.
        def _offline_watcher():
            # Wait for EdgePipeline to flip _running to True during its start()
            # instead of exiting during the small startup window.
            while not getattr(self, "_running", False):
                time.sleep(0.05)

            last = None
            last_applied_target = None
            last_rejected_seek = None
            while getattr(self, "_running", True):
                s = _scenario["current"]
                if s != last:
                    want_offline = (s == "offline")
                    try:
                        self.sync_client.set_simulate_offline(want_offline)
                        if hasattr(self, 'adapter'):
                            self.adapter.paused = (s == "paused")
                        logger.info(
                            f"[DemoRunner] sync_client.simulate_offline → {want_offline}, adapter.paused → {s == 'paused'}"
                        )
                    except Exception as exc:
                        logger.error(f"[DemoRunner] offline watcher error during scenario={s}: {exc}", exc_info=True)
                    last = s
                
                # If paused, do not seek or advance time
                if s == "paused":
                    time.sleep(1.0)
                    continue

                # Check for explicit seek requests
                target_time = _scenario.get("video_time")

                if target_time is not None and hasattr(self, 'adapter'):
                    source_kind = getattr(self.adapter, "source_kind", "OTHER")
                    duration_seconds = getattr(self.adapter, "duration_seconds", None)
                    seek_target = _control_seek_target(
                        target_time, source_kind, duration_seconds
                    )
                    if seek_target is None:
                        if source_kind == "LOCAL_FINITE_FILE" and duration_seconds:
                            rejected_seek = (target_time, duration_seconds)
                            if rejected_seek != last_rejected_seek:
                                logger.warning(
                                    "[DemoRunner] Ignoring out-of-range control-plane seek for finite source "
                                    "(requested=%s, duration=%.3fs)",
                                    target_time,
                                    duration_seconds,
                                )
                                last_rejected_seek = rejected_seek
                        time.sleep(1.0)
                        continue

                    last_rejected_seek = None

                    # Only seek if the difference is significant (> 2.0s) to avoid micro-stutters
                    current_edge_time = getattr(self.adapter, "_last_video_time", 0.0)
                    drift = seek_target - current_edge_time
                    if abs(drift) > 2.0 and target_time != last_applied_target:
                        logger.info(f"[DemoRunner] Seeking Edge to match Browser time: {seek_target}s (drift: {drift:.2f}s)")
                        self.adapter.seek_to(seek_target)
                        last_applied_target = target_time
                    # DO NOT clear _scenario["video_time"] so we can continue tracking drift

                time.sleep(1.0)

        t = threading.Thread(target=_offline_watcher, daemon=True, name="offline-watcher")
        t.start()

        def _restart_watcher():
            # DemoAwareEdgePipeline starts this watcher immediately before
            # EdgePipeline flips _running to True. Wait for that transition
            # instead of exiting during the small startup window.
            while not getattr(self, "_running", False):
                time.sleep(0.05)
            while True:
                if getattr(self, "_running", False) and _scenario.get("should_restart"):
                    logger.info("[DemoRunner] Restart requested by scenario state. Stopping pipeline...")
                    self.stop()
                    break
                if not getattr(self, "_running", False):
                    break
                time.sleep(1.0)
        
        t_restart = threading.Thread(target=_restart_watcher, daemon=True, name="restart-watcher")
        t_restart.start()

        # Delegate to the real EdgePipeline.start(), which handles YOLO load,
        # sync thread, frame loop, etc.
        super().start()


def run_demo_pipeline(
    camera_id: str,
    video_source: str,
    backend_url: str,
    zones_config_path: str = "demo/scripts/zones_config.json",
) -> None:
    """
    Build and run a DemoAwareEdgePipeline for one named camera.
    Called directly by __main__ below.
    """
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s | %(levelname)-8s | [{camera_id}] %(name)s | %(message)s",
    )
    logger.info(
        f"[DemoRunner] Starting demo pipeline: camera={camera_id} "
        f"source={video_source} backend={backend_url}"
    )

    # Establish the CLI fallback before polling. Then allow the first poll
    # to hydrate the current backend session before constructing a pipeline;
    # otherwise a short-lived legacy pipeline starts against the old shared
    # outbox and immediately has to restart.
    _scenario["video_source"] = video_source
    poll_thread = threading.Thread(
        target=_poll_scenario,
        args=(backend_url, camera_id, float(os.environ.get("SYNC_INTERVAL_SECONDS", 1.0))),
        daemon=True,
        name=f"scenario-poll-{camera_id}",
    )
    poll_thread.start()
    initialization_deadline = time.time() + 3.0
    while not _scenario.get("initialized") and time.time() < initialization_deadline:
        time.sleep(0.05)
    _scenario["should_restart"] = False

    while True:
        # The CLI replay is the fallback, but an explicit browser upload must
        # take precedence so Start/Analyze uses the selected local file.
        uploaded_source = _scenario.get("video_source")
        uploaded_session = _scenario.get("video_session_id")
        use_uploaded_source = bool(uploaded_source and uploaded_session and uploaded_source != video_source)
        current_source = uploaded_source if use_uploaded_source else video_source
        current_session = uploaded_session if use_uploaded_source else None
        state_paths = _runtime_state_paths(camera_id, backend_url, current_session)
        config = {
            "camera_id": camera_id,
            "camera_name": camera_id,
            "stream_id": current_session,
            "video_source": current_source,
            # User-uploaded sessions are finite jobs. Only explicit demo mode
            # enables local finite-file replay; physical/network sources are
            # classified by CameraAdapter and never receive loop semantics.
            "loop_video": (os.environ.get("DEMO_LOOP_VIDEO", "true").lower() == "true") and not bool(current_session),
            "backend_url": backend_url,
            "auth_token": os.environ.get("EDGE_AUTH_TOKEN", ""),
            "zones_config_path": zones_config_path,
            "key_dir": os.environ.get("EDGE_KEY_DIR", "certs/edge"),
            "allow_key_generation": os.environ.get("EDGE_ALLOW_KEY_GENERATION", "false").lower() == "true",
            # Per-camera chain/sync DBs so two simultaneous pipelines don't collide
            "chain_db_path": state_paths["chain_db_path"],
            # A finite upload gets its own durable outbox. This preserves old
            # unsent evidence without allowing a large legacy backlog to
            # starve the active operator session.
            "sync_db_path": state_paths["sync_db_path"],
            "clip_dir": state_paths["clip_dir"],
            "metrics_json_path": state_paths["metrics_json_path"],
            "fps_declared": 30.0,
            "simulate_frozen": False,
            "simulate_night": False,
        }

        logger.info(f"[DemoRunner] Instantiating pipeline with source {current_source}")
        pipeline = DemoAwareEdgePipeline(config)

        # start() blocks until the pipeline stops (e.g. video ends, interrupted, or restarted)
        pipeline.start()

        pipeline_exit_time = time.time()

        if _scenario.get("should_restart"):
            # The pipeline was stopped by the restart watcher, continue loop to recreate
            logger.info("[DemoRunner] Pipeline stopped for restart. Recreating...")
            # Consume the restart request only after the blocking pipeline exits.
            _scenario["should_restart"] = False
            time.sleep(1.0)
        else:
            # A completed upload should leave the worker alive so the next
            # uploaded session can be picked up without restarting the OS
            # process. The polling thread sets should_restart on a new ID.
            if _scenario.get("video_session_id"):
                logger.info("[DemoRunner] Uploaded video completed; waiting for the next session...")
                while not _scenario.get("should_restart"):
                    # Only restart if scenario is normal AND video_time explicitly returns to 0 (replay)
                    if _scenario.get("current") == "normal" and _scenario.get("video_time", -1) == 0:
                        updated_at = _scenario.get("video_time_updated_at", 0)
                        if updated_at > pipeline_exit_time:
                            logger.info("[DemoRunner] Resume requested on a completed session. Restarting pipeline to replay...")
                            break
                    time.sleep(0.25)
                _scenario["should_restart"] = False
                continue
            logger.info("[DemoRunner] Pipeline exited normally. Ending loop.")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "NETRAKSH Demo Runner — launches one edge pipeline for a named camera. "
            "Use CAMERA_ID / VIDEO_SOURCE / BACKEND_URL env vars or CLI flags."
        )
    )
    parser.add_argument(
        "--camera-id",
        default=os.environ.get("CAMERA_ID", "cam-border-01"),
        help="Camera ID (must match a registered camera in the backend DB)",
    )
    parser.add_argument(
        "--video-source",
        default=os.environ.get("VIDEO_SOURCE", "demo/videos/vtest.mp4"),
        help="OpenCV video source: path to .avi/.mp4, 'webcam', or RTSP URL",
    )
    parser.add_argument(
        "--backend-url",
        default=os.environ.get("BACKEND_URL", "http://localhost:8443"),
        help="NETRAKSH backend URL",
    )
    parser.add_argument(
        "--zones-config",
        default=os.environ.get("ZONES_CONFIG_PATH", "demo/scripts/zones_config.json"),
        help="Path to zones_config.json",
    )
    args = parser.parse_args()

    run_demo_pipeline(
        camera_id=args.camera_id,
        video_source=args.video_source,
        backend_url=args.backend_url,
        zones_config_path=args.zones_config,
    )
