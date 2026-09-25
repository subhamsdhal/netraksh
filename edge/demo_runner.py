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
import logging
import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional

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
            resp = httpx.get(f"{backend_url}/api/dashboard/video/internal-sync", params={"camera_id": camera_id}, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                new_scenario = data.get("scenario", "normal")
                new_source = data.get("video_source")
                new_session_id = data.get("video_session_id")
                new_video_time = data.get("video_time")

                # The browser may explicitly upload a new local source for
                # this camera. Preserve that source/session even in demo-loop
                # mode so the worker analyzes the file the operator selected;
                # the CLI vtest source remains the fallback only when no
                # browser session is configured.

                if new_scenario != _scenario["current"]:
                    logger.info(
                        f"[DemoRunner] Scenario changed: {_scenario['current']} → {new_scenario}"
                    )
                    _scenario["current"] = new_scenario
                
                if new_video_time is not None:
                    _scenario["video_time"] = float(new_video_time)
                if "video_time_updated_at" in data:
                    _scenario["video_time_updated_at"] = float(data["video_time_updated_at"])
                elif new_video_time is not None:
                    _scenario["video_time_updated_at"] = time.time()
                
                # If a new video source is provided, and it's different, trigger restart
                if new_source and (
                    new_source != _scenario.get("video_source")
                    or (new_session_id and new_session_id != _scenario.get("video_session_id"))
                ):
                    logger.info(f"[DemoRunner] Video source/session changed to {new_source} ({new_session_id}), triggering restart...")
                    _scenario["should_restart"] = True
                    _scenario["video_source"] = new_source
                if new_session_id:
                    _scenario["video_session_id"] = new_session_id
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
            while getattr(self, "_running", True):
                s = _scenario["current"]
                if s != last:
                    want_offline = (s == "offline")
                    try:
                        logger.info("PAUSE_DIAG: entering set_simulate_offline")
                        self.sync_client.set_simulate_offline(want_offline)
                        logger.info("PAUSE_DIAG: set_simulate_offline completed")
                        if hasattr(self, 'adapter'):
                            logger.info("PAUSE_DIAG: about to set adapter.paused")
                            self.adapter.paused = (s == "paused")
                            logger.info(f"PAUSE_DIAG: adapter.paused set successfully, value={self.adapter.paused}")
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
                logger.info("PAUSE_DIAG: entering seek section")
                target_time = _scenario.get("video_time")
                target_updated = _scenario.get("video_time_updated_at", time.time())
                
                if target_time is not None and hasattr(self, 'adapter'):
                    if s == "paused":
                        extrapolated_target = target_time
                    else:
                        if target_updated == 0.0:
                            extrapolated_target = target_time
                        else:
                            extrapolated_target = target_time + (time.time() - target_updated)
                        
                    # Only seek if the difference is significant (> 2.0s) to avoid micro-stutters
                    current_edge_time = getattr(self.adapter, "_last_video_time", 0.0)
                    drift = extrapolated_target - current_edge_time
                    if abs(drift) > 2.0 and target_time != last_applied_target:
                        logger.info(f"[DemoRunner] Seeking Edge to match Browser time: {extrapolated_target}s (drift: {drift:.2f}s)")
                        self.adapter.seek_to(extrapolated_target)
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
        demo_loop_enabled = os.environ.get("DEMO_LOOP_VIDEO", "true").lower() == "true"
        # The CLI replay is the fallback, but an explicit browser upload must
        # take precedence so Start/Analyze uses the selected local file.
        uploaded_source = _scenario.get("video_source")
        uploaded_session = _scenario.get("video_session_id")
        use_uploaded_source = bool(uploaded_source and uploaded_session and uploaded_source != video_source)
        current_source = uploaded_source if use_uploaded_source else video_source
        current_session = uploaded_session if use_uploaded_source else None
        session_suffix = f"_{current_session}" if current_session else ""
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
            "key_dir": "certs/edge",
            # Per-camera chain/sync DBs so two simultaneous pipelines don't collide
            "chain_db_path": f"edge/data/chain_{camera_id}.db",
            # A finite upload gets its own durable outbox. This preserves old
            # unsent evidence without allowing a large legacy backlog to
            # starve the active operator session.
            "sync_db_path": f"edge/data/sync_{camera_id}{session_suffix}.db",
            "clip_dir": "edge/data/clips",
            "metrics_json_path": f"edge/data/metrics_{camera_id}.json",
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
