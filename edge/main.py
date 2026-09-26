"""
NETRAKSH Edge — Main Pipeline.
Integrates all layers in the correct order:
  Layer 1: Camera ingestion (adapter)
  Layer 2: Health monitor (Gate 1) + Scene condition (Gate 2)
  Layer 3: YOLO + ByteTrack detection (Gate 3)
  Layer 4: Task modules (fence, behavior, ANPR, face)
  Layer 5: Reliability decision (3-gate)
  Layer 6: Evidence packaging + hash-chain
  Layer 7: Store-and-forward sync

Each event fired by a task module goes through the full reliability stack.
Zero detections also generate periodic health heartbeat events.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from queue import Empty, Queue
from typing import Dict, List, Optional

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from edge.condition.preprocessing import ConditionRouter, enhance_for_detection
from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.adaptive_gate import AdaptiveComputeGate
from edge.detection.calibration import CalibrationModule
from edge.detection.detector import DetectionTracker, NightMotionFallback
from edge.detection.face_recognition import sync_from_backend
from edge.evidence.packager import EdgeKeyManager, EvidenceChainStore, EvidencePackager
from edge.health.camera_health import CameraHealthMonitor
from edge.ingestion.camera_adapter import CameraAdapter
from edge.instrumentation.metrics import PipelineMetrics
from edge.reliability.decision import make_abstain, make_reliability_decision, make_uncertain
from edge.rules.modules import (
    ANPRModule,
    BehaviorModule,
    FaceDetectionModule,
    LineCrossingModule,
    VirtualFenceModule,
    load_zones,
)
from edge.sync.sync_client import SyncClient
from edge.temporal.event_verifier import EventVerifier
from edge.temporal.track_features import TrackFeatureTracker
from edge.telemetry import build_frame_snapshot, render_snapshot
from edge.tracking.continuity_guard import TrackContinuityGuard
from edge.tracking.continuity_guard import compute_histogram as compute_track_histogram
from shared.constants import (
    ABSTAIN_SNAPSHOT_INTERVAL_SECONDS,
    NIGHT_MOTION_COOLDOWN_SECONDS,
    CameraHealthState,
    DecisionState,
    DetectionClass,
    EventType,
    SceneCondition,
    Severity,
    StreamState,
)

logger = logging.getLogger(__name__)


def should_capture_abstain_snapshot(last_snapshot_time: float, now: float) -> bool:
    """
    Tiered evidence capture by condition quality (shared/constants.py's
    ABSTAIN_SNAPSHOT_INTERVAL_SECONDS docstring) — a pure, directly-testable
    function so this throttle decision doesn't require instantiating the
    full EdgePipeline (real YOLO model load and all) just to verify its
    boundary conditions.
    """
    return (now - last_snapshot_time) >= ABSTAIN_SNAPSHOT_INTERVAL_SECONDS


def determine_severity(event: dict, reliability) -> Severity:
    """Heuristic severity assignment for MVP."""
    et = str(event.get("event_type", ""))
    if "FENCE_CROSSING" in et:
        direction = str(event.get("direction", ""))
        if "OUTSIDE_TO_RESTRICTED" in direction:
            return Severity.HIGH
        return Severity.MEDIUM
    if "WRONG_DIRECTION" in et:
        # A real, admin-configured restricted_direction (ZoneSchema) fired —
        # a vehicle/person moving the wrong way past a one-way border
        # checkpoint or road is a genuine, specific security concern, not
        # just "a crossing happened" — HIGH, same tier as abandoned object.
        return Severity.HIGH
    if "LINE_CROSSING" in et:
        # Unlike a fence polygon, a line has no inherent inside/outside, so
        # neither A_TO_B nor B_TO_A can be assumed to be "the bad direction"
        # without zone-specific configuration — that configuration now
        # exists (ZoneSchema.restricted_direction, LineCrossingModule), but
        # a crossing this module didn't flag as wrong-way is still just an
        # ordinary crossing — MEDIUM reflects "a real crossing happened,"
        # not "a specific direction is confirmed dangerous."
        return Severity.MEDIUM
    if "LOITERING" in et:
        dwell = event.get("rule_value", 0)
        return Severity.HIGH if dwell > 60 else Severity.MEDIUM
    if "ABANDONED" in et:
        return Severity.HIGH
    if "ANPR" in et:
        return Severity.MEDIUM
    if "FACE" in et:
        # A real watchlist match (edge/detection/face_recognition.py) is a
        # materially different, more serious event than an ordinary,
        # unmatched face detection — HIGH, same tier as abandoned object /
        # wrong-direction. See that module's docstring for the honest
        # scope of what a "match" does and doesn't mean (never treat it as
        # a confirmed identification on its own).
        if event.get("face_match_person_id"):
            return Severity.HIGH
        return Severity.LOW
    if "MOVEMENT_UNCLASSIFIED" in et:
        # Night-motion fallback (architecture v4 §3): honestly LOW — this is
        # "something moved, class unknown," never a confirmed detection.
        return Severity.LOW
    return Severity.LOW


class EdgePipeline:
    """
    Main edge pipeline. Runs all layers per-frame.
    """

    def __init__(self, config: dict):
        self.config = config
        
        raw_id = config.get("camera_id", "")
        if not raw_id:
            raise ValueError("camera_id is required")

        import re
        if not re.match(r"^[A-Za-z0-9_-]+$", raw_id):
            raise ValueError(f"Invalid camera_id '{raw_id}': must contain only alphanumeric characters, dashes, and underscores.")
            
        self.camera_id = raw_id
        self.camera_name = config.get("camera_name", self.camera_id)
        # A new pipeline instance represents a new video stream/session.
        self.stream_id = config.get("stream_id") or str(uuid.uuid4())
        self.zone_config_path = config.get("zones_config_path", "demo/scripts/zones_config.json")
        self._running = False

        # Offline Model Readiness Validation (Batch 1 & 2)
        self.yolo_model_path = config.get("model_size", os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt"))
        if not os.path.exists(self.yolo_model_path):
            logger.error(f"[Pipeline] FATAL: Configured YOLO model not found at '{self.yolo_model_path}'")
            raise RuntimeError(f"YOLO offline model missing: {self.yolo_model_path}. Do not silently download during demo.")

        # Initialize all layers
        logger.info(f"[Pipeline] Initializing edge pipeline for camera {self.camera_id}...")

        # Layer 1: Camera adapter
        self.adapter = CameraAdapter(
            source=config.get("video_source"),
            simulate_frozen=config.get("simulate_frozen", False),
            simulate_night=config.get("simulate_night", False),
            loop_video=config.get("loop_video", os.environ.get("DEMO_LOOP_VIDEO", "false").lower() == "true"),
        )

        # Telemetry
        self.telemetry_fps = int(os.environ.get("TELEMETRY_FPS", 10))
        self.telemetry_interval = 1.0 / self.telemetry_fps if self.telemetry_fps > 0 else 0
        self._last_telemetry_time = 0.0
        self._telemetry_sequence = 0
        self._last_video_time = None
        self._last_frame_width = None
        self._last_frame_height = None
        # We need a small bounded queue so if the backend goes down or network
        # is durable/offline-capable. Telemetry is explicitly lossy.
        self.telemetry_queue = Queue(maxsize=2)
        self._telemetry_metrics = {"produced": 0, "dropped": 0, "errors": 0}

        # Layer 2: Health + Condition
        self.health_monitor = CameraHealthMonitor(
            camera_id=self.camera_id,
            fps_declared=config.get("fps_declared", 25.0),
        )
        self.condition_classifier = SceneConditionClassifier(camera_id=self.camera_id)
        self.condition_router = ConditionRouter()

        # Layer 3: Detection + calibration
        self.calibration = CalibrationModule(
            calibration_path=config.get("calibration_path")
        )
        self.detector = DetectionTracker(
            model_size=self.yolo_model_path,
            device=config.get("device", "cpu"),
        )
        self.adaptive_gate = AdaptiveComputeGate()

        # Night-motion fallback (architecture v4 §3) — was implemented but
        # never wired into the pipeline before this change; see
        # docs/ARCHITECTURE.md's changelog entry for the fix.
        self.night_motion_fallback = NightMotionFallback()
        self._last_night_motion_emit_time = 0.0
        # Tiered evidence capture (see shared/constants.py's
        # ABSTAIN_SNAPSHOT_INTERVAL_SECONDS docstring) — 0.0 so the very
        # first FAILED-health frame of a run always captures a snapshot
        # immediately, not after waiting a full interval.
        self._last_abstain_snapshot_time = 0.0
        self._last_abstain_emit_time = 0.0

        # Load zones
        self.zones = load_zones(self.zone_config_path)
        logger.info(f"[Pipeline] Loaded {len(self.zones)} zones from {self.zone_config_path}")

        # Layer 4: Task modules
        self.fence_module = VirtualFenceModule(self.zones)
        self.line_module = LineCrossingModule(self.zones)
        self.behavior_module = BehaviorModule(self.zones)
        self.anpr_module = ANPRModule(self.zones)

        self.behavior_analytics_enabled = config.get("behavior_analytics", os.environ.get("BEHAVIOR_ANALYTICS", "false").lower() == "true")

        # Real watchlist face recognition (SIH PS 26187 -- "support facial
        # recognition", not detection alone; see edge/detection/
        # face_recognition.py for the full honest scope). Synced from the
        # backend at startup and periodically thereafter (see
        # _resync_watchlist below, same cadence pattern as
        # _report_metrics). A failed sync leaves an untrained-but-real
        # recognizer -- FaceDetectionModule still runs real detection, just
        # with zero real matches possible until a later sync succeeds.
        self._backend_url = config.get("backend_url", os.environ.get("BACKEND_URL", "http://localhost:8443"))
        self._edge_auth_token = config.get("auth_token", os.environ.get("EDGE_AUTH_TOKEN", ""))
        self.face_recognizer = sync_from_backend(self._backend_url, auth_token=self._edge_auth_token)
        self.face_module = FaceDetectionModule(self.zones, recognizer=self.face_recognizer)

        # Layer 6: Evidence
        key_dir = config.get("key_dir", "certs/edge")
        self.key_manager = EdgeKeyManager(
            private_key_path=os.path.join(key_dir, f"{self.camera_id}.key"),
            public_key_path=os.path.join(key_dir, f"{self.camera_id}.pub"),
        )
        self.key_manager.load_or_generate()

        chain_path = config.get("chain_db_path", f"edge/data/chain_{self.camera_id}.db")
        self.chain_store = EvidenceChainStore(chain_path)
        self.packager = EvidencePackager(
            camera_id=self.camera_id,
            stream_id=self.stream_id,
            key_manager=self.key_manager,
            chain_store=self.chain_store,
            clip_storage_dir=config.get("clip_dir", "edge/data/clips"),
        )
        self._register_crypto_material()

        # Layer 7: Sync
        self.sync_client = SyncClient(
            edge_device_id=self.camera_id,
            backend_url=config.get("backend_url", "http://localhost:8443"),
            db_path=config.get("sync_db_path", f"edge/data/sync_{self.camera_id}.db"),
            auth_token=self._edge_auth_token,
            ca_cert_path=config.get("ca_cert_path"),
            client_cert_path=config.get("client_cert_path"),
            client_key_path=config.get("client_key_path"),
        )

        # Track trajectories for ByteTrack
        self._trajectories: Dict[int, List] = {}
        # Track last default zone for events without specific zone
        self._default_zone_id = self.zones[0].zone_id if self.zones else "zone-default"

        # Layer 4.5: Event Verification state machine (architecture v4 §9).
        # Evidence is now packaged only once a candidate is promoted to
        # VERIFIED/ALERTED here — not the instant a task module fires.
        self.event_verifier = EventVerifier()
        self._verify_tick = 0

        # Temporal Evidence Intelligence, Mode A (architecture v4 §7, ADR-001).
        # Feeds the `temporal_score` (T) input to the Hybrid Reliability
        # Engine (edge/reliability/decision.py).
        self.track_feature_tracker = TrackFeatureTracker()

        # Track Continuity Guard (architecture v4 §4) — classical-CV
        # re-association of a track lost to brief occlusion. See
        # edge/tracking/continuity_guard.py.
        self.continuity_guard = TrackContinuityGuard()
        self._known_track_ids: set = set()
        self._track_last_snapshot: Dict[int, dict] = {}
        self._track_id_map: Dict[int, int] = {}

        # Performance instrumentation (architecture v4 §15, MUST HAVE).
        # Real, locally-measured latency/FPS/resource numbers — never invented.
        self.metrics = PipelineMetrics()
        self._metrics_report_interval = config.get("metrics_report_interval_seconds", 10.0)
        self._metrics_json_path = config.get(
            "metrics_json_path", os.path.join("edge", "data", f"metrics_{self.camera_id}.json")
        )
        # Real watchlist re-sync cadence (SIH PS 26187) -- 300s default:
        # frequent enough that a newly-enrolled/removed watchlist person
        # takes effect within a few minutes without a restart, infrequent
        # enough not to hammer the backend every frame loop tick.
        self._watchlist_sync_interval = config.get("watchlist_sync_interval_seconds", 300.0)
        
        # Phase 3 Step 7: Behavioral Intelligence
        self.behavior_analytics_enabled = str(os.environ.get("BEHAVIOR_ANALYTICS", "false")).lower() == "true"
        if self.behavior_analytics_enabled:
            from edge.temporal.trajectory import TrajectoryFeatureLayer
            from edge.rules.behavior_analytics import BehaviorCorrelationEngine
            self.trajectory_layer = TrajectoryFeatureLayer()
            self.behavior_correlation = BehaviorCorrelationEngine(self.zones)
            logger.info("[Pipeline] Behavior Analytics ENABLED")

    def _register_crypto_material(self) -> None:
        """Best-effort authenticated bootstrap of the camera's current keys.

        The backend wraps the AES key immediately and stores only the public
        signing key plus wrapped decryption material.  Values are deliberately
        never logged; a later event-sync retry remains possible if startup
        races the command center coming online.
        """
        try:
            import httpx
            headers = {}
            if self._edge_auth_token:
                headers["Authorization"] = f"Bearer {self._edge_auth_token}"
            response = httpx.put(
                f"{self._backend_url}/cameras/{self.camera_id}/edge-keys",
                json={
                    "public_key_pem": self.key_manager.get_public_key_pem(),
                    "evidence_key_b64": self.packager.encryptor.get_raw_key_b64(),
                },
                headers=headers,
                timeout=10.0,
            )
            if response.status_code == 200:
                logger.info("[Pipeline] Camera cryptographic material registered")
            else:
                logger.warning("[Pipeline] Camera key registration deferred (HTTP %s)", response.status_code)
        except Exception as exc:
            logger.warning("[Pipeline] Camera key registration deferred: %s", type(exc).__name__)

    def start(self) -> None:
        """
        Start the pipeline. Loads model, opens camera, then runs frame loop.
        Sync runs in a background thread.
        """
        logger.info("[Pipeline] Loading YOLO model...")
        self.detector.load()

        # Start sync in background thread
        sync_thread = threading.Thread(
            target=self.sync_client.run_sync_loop,
            daemon=True,
            name=f"sync-{self.camera_id}",
        )
        sync_thread.start()
        logger.info("[Pipeline] Sync thread started")

        self._running = True
        logger.info(f"[Pipeline] Starting frame loop for camera {self.camera_id}")

        telemetry_thread = threading.Thread(
            target=self._run_telemetry_loop,
            daemon=True,
            name=f"telemetry-{self.camera_id}",
        )
        telemetry_thread.start()
        logger.info("[Pipeline] Telemetry thread started")

        try:
            self._run_frame_loop()
        except KeyboardInterrupt:
            logger.info("[Pipeline] Interrupted by user")
        finally:
            completed = self.adapter.eof_reached and self.adapter.state != StreamState.FAILED
            if completed:
                self._flush_event_outbox()
                # Publish one final metrics snapshot after the drain so the
                # command-center sync indicator sees the real zero queue.
                self._report_metrics()
                self._publish_analysis_state("COMPLETED")
            elif self.adapter.state == StreamState.FAILED:
                self._publish_analysis_state("FAILED")
            self._running = False
            if hasattr(self, 'sync_client') and self.sync_client:
                try:
                    self.sync_client.stop()
                except Exception:
                    pass
            self.adapter.stop()
            self.adapter.join()
            telemetry_thread.join(timeout=2.0)

    def stop(self) -> None:
        """Gracefully stop the pipeline."""
        logger.info(f"[Pipeline] Stopping frame loop for camera {self.camera_id}")
        self._running = False
        if hasattr(self, 'sync_client') and self.sync_client:
            try:
                self.sync_client.stop()
            except Exception:
                pass

    def _run_telemetry_loop(self) -> None:
        """Background thread for pushing live telemetry to the backend."""
        import httpx
        verify: object = self.sync_client._ca_cert if self.sync_client._ca_cert else True
        if verify is False:
            verify = True # Should be caught by sync_client, but enforce here
            
        timeout = httpx.Timeout(10.0, connect=5.0, read=10.0, write=10.0)
        client = httpx.Client(
            timeout=timeout,
            verify=verify,
            cert=self.sync_client._client_cert
        )
        telemetry_url = f"{self._backend_url}/system/telemetry"
        while self._running:
            try:
                payload = self.telemetry_queue.get(timeout=0.5)
                try:
                    clean_preview = payload.pop("_clean_preview_jpeg_base64", None)
                    annotated_preview = payload.pop("_annotated_preview_jpeg_base64", None)
                    if clean_preview and annotated_preview:
                        try:
                            frame_response = client.post(
                                f"{self._backend_url}/system/telemetry/frame",
                                json={
                                    "camera_id": payload["camera_id"],
                                    "analysis_session_id": payload.get("analysis_session_id"),
                                    "frame_index": payload.get("frame_index"),
                                    "source_timestamp": payload.get("source_timestamp"),
                                    "processed_timestamp": payload.get("processed_timestamp"),
                                    "person_count": payload.get("person_count", 0),
                                    "vehicle_count": payload.get("vehicle_count", 0),
                                    "track_count": payload.get("track_count", 0),
                                    "clean_jpeg_base64": clean_preview,
                                    "annotated_jpeg_base64": annotated_preview,
                                },
                                headers=self._edge_auth_headers(),
                            )
                            if not frame_response.is_success:
                                self._telemetry_metrics["errors"] += 1
                                payload["preview_available"] = False
                                logger.warning("[Telemetry] frame HTTP %s", frame_response.status_code)
                        except httpx.RequestError as exc:
                            self._telemetry_metrics["errors"] += 1
                            payload["preview_available"] = False
                            logger.warning("[Telemetry] frame %s", type(exc).__name__)
                    try:
                        snapshot_response = client.post(
                            telemetry_url,
                            json=payload,
                            headers=self._edge_auth_headers(),
                        )
                        if not snapshot_response.is_success:
                            self._telemetry_metrics["errors"] += 1
                            logger.warning("[Telemetry] snapshot HTTP %s", snapshot_response.status_code)
                    except httpx.RequestError as exc:
                        self._telemetry_metrics["errors"] += 1
                        logger.warning("[Telemetry] snapshot %s", type(exc).__name__)
                finally:
                    self.telemetry_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                self._telemetry_metrics["errors"] += 1
                logger.error("[Telemetry] Unexpected %s: %s", type(e).__name__, e)
        client.close()

    def _run_frame_loop(self) -> None:
        """Main frame processing loop."""
        frame_skip = self.config.get("frame_skip", 1)  # process every Nth frame
        frame_count = 0
        last_health_report_time = 0.0
        last_metrics_report_time = 0.0
        last_watchlist_sync_time = time.time()  # already synced once in __init__

        self.adapter.start()
        try:
            while self._running:
                frame, meta = self.adapter.get_frame(timeout=0.1)

                if frame is not None and meta is not None:
                    if getattr(meta, "replay_boundary", False):
                        self._reset_replay_state(meta.replay_cycle)
                    frame_count += 1
                    if frame_count % frame_skip == 0:
                        self._process_frame(frame, meta)
                else:
                    if self.adapter.eof_reached:
                        logger.info("[Pipeline] Video buffer drained after EOF")
                        break
                    # No frame available; update health using stream state so the backend is informed of disconnects
                    health = self.health_monitor.update(None, time.time(), self.adapter.state)
                    self._last_health = health

                if time.time() - last_health_report_time > 5.0:
                    last_health_report_time = time.time()
                    self._report_camera_health()
                if time.time() - last_metrics_report_time > self._metrics_report_interval:
                    last_metrics_report_time = time.time()
                    self._report_metrics()
                if time.time() - last_watchlist_sync_time > self._watchlist_sync_interval:
                    last_watchlist_sync_time = time.time()
                    self._resync_watchlist()
        finally:
            self.adapter.stop()
            self.adapter.join()

    def _reset_replay_state(self, replay_cycle: int) -> None:
        """Clear only timeline-bound state when a finite demo file rewinds."""
        logger.info("[Pipeline] Starting demo replay cycle %d; resetting transient tracking/rule state", replay_cycle)
        self._trajectories.clear()
        self._known_track_ids.clear()
        self._track_last_snapshot.clear()
        self._track_id_map.clear()
        if hasattr(self.continuity_guard, "_lost_pool"):
            self.continuity_guard._lost_pool.clear()
        self.track_feature_tracker = TrackFeatureTracker()
        self.event_verifier = EventVerifier()
        self.fence_module._track_zone_state.clear()
        self.line_module._track_side_state.clear()
        self.behavior_module._entry_times.clear()
        self.behavior_module._static_tracks.clear()
        self.behavior_module._disappeared_tracks.clear()
        self.behavior_module._fired_loitering.clear()
        if getattr(self.face_module, "_temporal_fusion", None) is not None:
            fusion = self.face_module._temporal_fusion
            if hasattr(fusion, "_observations"):
                fusion._observations.clear()
        tracker = getattr(self.detector, "_tracker", None)
        if tracker is not None and hasattr(tracker, "reset"): tracker.reset()
        # A replay is a new analysis session. Rotate the identifier before the
        # first frame so telemetry and newly persisted events cannot be mixed
        # with the previous pass through the file.
        self.stream_id = str(uuid.uuid4())
        self.packager.stream_id = self.stream_id
        self._telemetry_sequence = 0
        self._last_telemetry_time = 0.0
        while not self.telemetry_queue.empty():
            try:
                self.telemetry_queue.get_nowait()
                self.telemetry_queue.task_done()
            except Empty:
                break

    def _report_camera_health(self) -> None:
        """
        Push a periodic real health snapshot to the backend
        (POST /cameras/{id}/health), independent of any detection event —
        this is what actually populates the Camera Health Matrix dashboard
        page's per-camera FPS/blur/exposure/drift readings.

        Before this method existed, `last_health_report_time` was threaded
        through `_process_frame`'s signature every frame but never actually
        read there — a dead timer implying a heartbeat that was never sent,
        despite this module's docstring claiming one existed. CameraHealth
        rows were never written by any code path (see docs/LIMITATIONS.md).

        Best-effort only, same posture as SyncClient's offline tolerance —
        a failed POST here must never interrupt the frame loop. This is
        NOT routed through the offline sync queue (unlike events): it's a
        best-effort heartbeat, not evidence: losing one is fine, and the
        next one is only 5 seconds away.
        """
        health = getattr(self, "_last_health", None)
        if health is None:
            return
        try:
            import httpx
            verify: object = self.sync_client._ca_cert if self.sync_client._ca_cert else True
            httpx.post(
                f"{self.sync_client.backend_url}/cameras/{self.camera_id}/health",
                content=health.model_dump_json(),
                headers={"Content-Type": "application/json", **self._edge_auth_headers()},
                timeout=3.0,
                verify=verify,
                cert=self.sync_client._client_cert
            )
        except Exception as exc:
            logger.debug(f"[Health] Periodic health report failed (non-fatal): {exc}")

    def _apply_continuity_guard(self, tracks: List, frame) -> List:
        """
        For every track ID not seen before, ask the Continuity Guard whether
        it matches something recently lost (histogram + spatial proximity).
        On a match, the new detection's track_id AND trajectory are rewritten
        in place to the old, recognized identity — logged, not silent — so
        every downstream consumer (trajectory store, T-feature age tracking,
        VirtualFenceModule's zone-membership state, BehaviorModule's
        dwell/stationary tracking) resumes exactly where it left off.
        """
        now = time.time()
        for track in tracks:
            native_id = track.track_id
            
            if native_id in self._track_id_map:
                canonical_id = self._track_id_map[native_id]
                track.track_id = canonical_id
                self._known_track_ids.add(canonical_id)
                continue
                
            if native_id in self._known_track_ids:
                continue

            histogram = compute_track_histogram(frame, track.bbox)
            match = self.continuity_guard.resolve_new_track(histogram, track.bbox.centroid, now)
            if match is not None:
                matched_id, matched_trajectory = match
                logger.info(
                    f"[Pipeline] Track {native_id} re-associated with recently-lost "
                    f"track {matched_id} by Continuity Guard — resuming its history"
                )
                self._track_id_map[native_id] = matched_id
                track.track_id = matched_id
                track.trajectory = list(matched_trajectory) + list(track.trajectory)
                self._known_track_ids.add(matched_id)
            else:
                self._known_track_ids.add(native_id)
        return tracks

    def _process_frame(self, frame, meta) -> None:
        """Process a single frame through the full pipeline."""
        self._verify_tick += 1
        self._last_video_time = meta.video_time_seconds
        self._last_frame_width = meta.width
        self._last_frame_height = meta.height

        # --- Performance instrumentation: t0 (frame received) ---
        t_frame_start = time.perf_counter()

        # === Layer 2: Gate 1 — Camera Health ===
        health = self.health_monitor.update(frame, meta.timestamp, self.adapter.state)
        self._last_health = health

        # === Layer 2: Gate 2 — Scene Condition ===
        condition = self.condition_classifier.classify(frame)

        t_health_condition = time.perf_counter()

        # If camera FAILED, emit ABSTAIN heartbeat and stop
        if health.health_state == CameraHealthState.FAILED:
            now = time.time()
            if (now - self._last_abstain_emit_time) >= 1.0:
                self._last_abstain_emit_time = now
                reliability = make_abstain(self.camera_id, health.health_reason, condition.condition)
                # Tiered evidence capture by condition quality (see shared/
                # constants.py's ABSTAIN_SNAPSHOT_INTERVAL_SECONDS docstring):
                # this heartbeat fires every frame (unchanged, real camera-health
                # telemetry), but previously NEVER saved a snapshot at all --
                # frame=None unconditionally -- so a false FAILED trigger left
                # nothing to review. Now captures a real encrypted snapshot
                # periodically instead of never, without flooding disk with one
                # per frame during a sustained outage.
                capture_snapshot = should_capture_abstain_snapshot(self._last_abstain_snapshot_time, now)
                if capture_snapshot:
                    self._last_abstain_snapshot_time = now
                self._emit_event(
                    track=None,
                    reliability=reliability,
                    health=health,
                    condition=condition,
                    zone_id=self._default_zone_id,
                    overrides={},
                    frame=frame if capture_snapshot else None,
                )
            t_frame_end = time.perf_counter()
            self.metrics.record_frame(
                health_condition_ms=(t_health_condition - t_frame_start) * 1000.0,
                detection_tracking_ms=0.0,
                event_processing_ms=(t_frame_end - t_health_condition) * 1000.0,
                total_frame_ms=(t_frame_end - t_frame_start) * 1000.0,
            )
            return

        # === Layer 2.5: Adaptive Compute Gate (architecture v4 §6) ===
        # Skip full YOLO inference on genuinely idle frames (no motion, no
        # active track, no pending candidate) to save compute — reuses Gate
        # 1's own frame-difference variance, no new per-frame cost. Never
        # skips a frame that already has something being tracked (see
        # edge/detection/adaptive_gate.py's module docstring for why that's
        # what makes this safe for ByteTrack's continuity).
        run_inference = self.adaptive_gate.should_run_inference(
            frame_variance=health.frame_variance,
            has_active_tracks=bool(self._trajectories),
            has_pending_candidates=self.event_verifier.get_pending_count() > 0,
        )

        # === Layer 3: Gate 3 — YOLO + ByteTrack ===
        calibrated_threshold = self.calibration.get_threshold(condition.condition)
        detection_frame = frame
        enhancement_applied = False

        if run_inference:
            # CLAHE preprocessing (architecture v4 §3): a SEPARATE enhanced
            # copy for LOW_LIGHT_NIGHT/FOG_RAIN, detector input only — health,
            # condition, evidence snapshots, and ANPR/face crops all keep
            # using the original `frame` so their measurements stay honest.
            policy = self.condition_router.route(condition.condition)
            detection_frame = enhance_for_detection(frame, policy)
            enhancement_applied = detection_frame is not frame
            try:
                tracks = self.detector.detect_and_track(
                    detection_frame, condition.condition, calibrated_threshold,
                    existing_trajectories=self._trajectories,
                )
            except Exception as exc:
                logger.error(f"[Pipeline] Detector error: {exc}")
                tracks = []
        else:
            tracks = []

        t_detection_tracking = time.perf_counter()

        # === Layer 3.5: Track Continuity Guard (architecture v4 §4) ===
        # Re-associates a brand-new ByteTrack ID with a recently-lost one via
        # color-histogram + spatial proximity — classical CV, no learned
        # Re-ID — BEFORE anything else (trajectory, T-feature age, task
        # modules) sees the track. Every downstream consumer keyed by
        # track_id therefore resumes its prior state automatically once a
        # re-association happens, with no further changes needed.
        tracks = self._apply_continuity_guard(tracks, frame)
        for expired_id in self.continuity_guard.expire_stale(time.time()):
            self.track_feature_tracker.forget(expired_id)

        # Update trajectory state + snapshot each active track's appearance
        # (histogram + centroid) so the Continuity Guard has something to
        # match against the moment this track is later lost.
        #
        # track_feature_tracker.observe() is called here UNCONDITIONALLY for
        # every active track, every frame — a real, measured bug fix (see
        # edge/temporal/track_features.py's class docstring and
        # docs/PERFORMANCE_REPORT.md's "Reliability Engine behavior" section):
        # this class's `_first_seen` bookkeeping must be registered as soon
        # as a track is first observed, not only when some task module
        # module later happens to fire an event for it (temporal_score_for()
        # below only calls `compute()` inside those event-triggered
        # branches) — a fence-crossing event, which by its nature usually
        # fires exactly once per track at the crossing transition, would
        # otherwise ALWAYS see age_seconds=0.0 on that one call, regardless
        # of how long the track had genuinely already been tracked.
        for t in tracks:
            self._trajectories[t.track_id] = t.trajectory
            self._track_last_snapshot[t.track_id] = {
                "histogram": compute_track_histogram(frame, t.bbox),
                "centroid": t.bbox.centroid,
            }
            self.track_feature_tracker.observe(t.track_id, time.time())

        # Clean up stale trajectories — hand off to the Continuity Guard's
        # lost pool (with a grace window) instead of forgetting immediately.
        active_ids = {t.track_id for t in tracks}
        stale = [k for k in self._trajectories if k not in active_ids]
        for k in stale[:20]:  # Cap cleanup per frame
            snapshot = self._track_last_snapshot.get(k)
            if snapshot is not None and snapshot["histogram"] is not None:
                self.continuity_guard.remember_lost(
                    k, snapshot["histogram"], snapshot["centroid"],
                    self._trajectories.get(k, []), time.time(),
                )
            else:
                # Nothing usable to re-match against later — forget now
                # rather than leak state waiting for a match that can't happen.
                self.track_feature_tracker.forget(k)
            del self._trajectories[k]
            self._known_track_ids.discard(k)
            native_to_remove = [n_id for n_id, c_id in self._track_id_map.items() if c_id == k]
            for n_id in native_to_remove:
                del self._track_id_map[n_id]
            self._track_last_snapshot.pop(k, None)

        # === Live Telemetry (architecture v4 §16) ===
        if self.telemetry_fps > 0 and (time.time() - self._last_telemetry_time) >= self.telemetry_interval:
            self._last_telemetry_time = time.time()
            self._telemetry_sequence += 1
            frame_h, frame_w = frame.shape[:2] if frame is not None else (1, 1)
            processed_timestamp = time.time()
            frame_snapshot = build_frame_snapshot(
                camera_id=self.camera_id,
                analysis_session_id=self.stream_id,
                frame_index=meta.frame_index,
                source_timestamp=meta.timestamp,
                processed_at=processed_timestamp,
                source_video_time=meta.video_time_seconds,
                tracks=tracks,
                frame_width=frame_w,
                frame_height=frame_h,
            )
            raw_detections = []
            for detection in getattr(self.detector, "last_raw_detections", []):
                class_value = getattr(detection, "class_id", -1)
                class_name = "person" if class_value == 0 else "vehicle" if class_value in {2, 3, 5, 7} else "unknown"
                raw_detections.append({
                    "detection_class": class_name,
                    "confidence": float(detection.confidence),
                    "bbox_x": float(detection.bbox.x1 / frame_w) if frame_w else 0.0,
                    "bbox_y": float(detection.bbox.y1 / frame_h) if frame_h else 0.0,
                    "bbox_w": float(detection.bbox.width / frame_w) if frame_w else 0.0,
                    "bbox_h": float(detection.bbox.height / frame_h) if frame_h else 0.0,
                })
            processing_fps = float(self.metrics.current_fps())
            expected_interval_ms = (1000.0 / processing_fps) if processing_fps > 0 else None
            
            if self._telemetry_sequence % 20 == 0 and tracks:
                logger.info(f"[DEBUG-TRACE] SEQ={self._telemetry_sequence} FRAME_W={frame_w} FRAME_H={frame_h} VIDEO_TIME={meta.video_time_seconds}")
                for t in tracks:
                    logger.info(f"[DEBUG-TRACE] TRACK={t.track_id} ORIGINAL=[{t.bbox.x1:.1f}, {t.bbox.y1:.1f}, {t.bbox.x2:.1f}, {t.bbox.y2:.1f}] NORMALIZED=[{t.bbox.x1/frame_w:.3f}, {t.bbox.y1/frame_h:.3f}, {t.bbox.width/frame_w:.3f}, {t.bbox.height/frame_h:.3f}]")
            payload = {
                "camera_id": self.camera_id,
                "timestamp": processed_timestamp,
                "video_time": meta.video_time_seconds,
                "sequence": self._telemetry_sequence,
                "frame_index": int(meta.frame_index),
                "source_timestamp": float(meta.timestamp),
                "processed_timestamp": processed_timestamp,
                "processing_fps": processing_fps,
                "expected_interval_ms": expected_interval_ms,
                "frame_width": frame_w,
                "frame_height": frame_h,
                "stream_id": self.stream_id,
                "analysis_session_id": self.stream_id,
                "analysis_state": "PROCESSING",
                "scene_condition": str(condition.condition),
                "lighting_state": getattr(condition, "lighting_state", None),
                "mean_luminance": getattr(condition, "mean_luminance", condition.brightness_mean),
                "enhancement_applied": enhancement_applied,
                "detection_method": "YOLO" if tracks else "NONE",
                "source_kind": self.adapter.source_kind,
                "demo_replay": self.adapter.demo_replay,
                "replay_cycle": getattr(meta, "replay_cycle", 0),
                "raw_detection_count": len(raw_detections),
                "tracker_output_count": int(getattr(self.detector, "last_tracker_output_count", len(tracks))),
                "person_count": frame_snapshot.person_count,
                "vehicle_count": frame_snapshot.vehicle_count,
                "track_count": frame_snapshot.track_count,
                "active_track_ids": frame_snapshot.active_track_ids,
                "tracker_output_ids": list(frame_snapshot.tracker_output_ids),
                "raw_detections": raw_detections,
                "preview_available": False,
                "tracks": frame_snapshot.live_tracks(),
            }
            try:
                import base64
                import cv2
                annotated_frame = render_snapshot(frame, frame_snapshot, hud=True)
                clean_ok, clean_encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
                annotated_ok, annotated_encoded = cv2.imencode(".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
                if clean_ok and annotated_ok:
                    payload["_clean_preview_jpeg_base64"] = base64.b64encode(clean_encoded.tobytes()).decode("ascii")
                    payload["_annotated_preview_jpeg_base64"] = base64.b64encode(annotated_encoded.tobytes()).decode("ascii")
                    payload["preview_available"] = True
                    validation_dir = os.environ.get("ANNOTATED_FRAME_DIR")
                    if validation_dir and self._telemetry_sequence in {1, 25, 50, 75, 100}:
                        Path(validation_dir).mkdir(parents=True, exist_ok=True)
                        filename = (
                            f"camera1_frame_{frame_snapshot.frame_index:05d}_"
                            f"p{frame_snapshot.person_count}_v{frame_snapshot.vehicle_count}_t{frame_snapshot.track_count}.jpg"
                        )
                        cv2.imwrite(str(Path(validation_dir) / filename), annotated_frame)
            except Exception as exc:
                logger.debug("[Telemetry] Analyzed-frame JPEG unavailable: %s", exc)

            trace_path = os.environ.get("TELEMETRY_TRACE_PATH")
            if trace_path:
                try:
                    trace_record = {key: value for key, value in payload.items() if not key.startswith("_")}
                    with open(trace_path, "a", encoding="utf-8") as trace_file:
                        trace_file.write(json.dumps(trace_record, sort_keys=True) + "\n")
                except OSError as exc:
                    logger.debug("[Telemetry] Trace write failed: %s", exc)
            try:
                # Latest-only queue strategy (backpressure):
                # If queue is full, discard the OLDEST telemetry to make room
                # for the NEWEST state, rather than discarding the newest.
                if self.telemetry_queue.full():
                    try:
                        self.telemetry_queue.get_nowait()
                        self.telemetry_queue.task_done()
                        self._telemetry_metrics["dropped"] += 1
                    except Empty:
                        pass
                self.telemetry_queue.put_nowait(payload)
                self._telemetry_metrics["produced"] += 1
            except Exception:
                # This is a real telemetry producer failure, distinct from a
                # deliberate latest-only drop above.
                self._telemetry_metrics["errors"] += 1

        # === Layer 3.6: Night-Motion Fallback (architecture v4 §3) ===
        # NightMotionFallback existed in edge/detection/detector.py but was
        # never called from anywhere — dead code until this change. Only
        # checked on frames we actually ran inference on (skipping this on
        # an Adaptive-Compute-Gate-skipped frame would be redundant: that
        # gate already agreed no motion was present via a different signal)
        # and only when YOLO found nothing at all — this is explicitly a
        # fallback for when the detector has no answer, not a second opinion
        # on top of a real detection.
        night_motion = {"motion": False, "area": 0.0, "persistence": 0}
        if (
            run_inference
            and condition.condition == SceneCondition.LOW_LIGHT_NIGHT
            and not tracks
        ):
            night_motion = self.night_motion_fallback.detect_motion_details(frame)
        if (
            run_inference
            and condition.condition == SceneCondition.LOW_LIGHT_NIGHT
            and night_motion.get("motion")
            and (time.time() - self._last_night_motion_emit_time) >= NIGHT_MOTION_COOLDOWN_SECONDS
        ):
            self._last_night_motion_emit_time = time.time()
            movement_reliability = make_uncertain(condition.condition, confidence=0.0, threshold=calibrated_threshold)
            movement_event = {
                "event_type": EventType.MOVEMENT_UNCLASSIFIED,
                "zone_id": self._default_zone_id,
                "track_id": None,
                "detection_class": DetectionClass.UNKNOWN,
                "confidence": 0.0,
                "lighting_state": getattr(condition, "lighting_state", "LOW_LIGHT"),
                "mean_luminance": getattr(condition, "mean_luminance", condition.brightness_mean),
                "dark_pixel_ratio": getattr(condition, "dark_pixel_ratio", None),
                "enhancement_applied": False,
                "detection_method": "MOTION_FALLBACK",
                "motion_area": night_motion.get("area", 0.0),
                "motion_persistence": night_motion.get("persistence", 0),
                "severity": determine_severity(
                    {"event_type": EventType.MOVEMENT_UNCLASSIFIED}, movement_reliability
                ).value,
            }
            # Emitted directly, NOT through the Event Verifier: an UNCERTAIN
            # decision_state can never satisfy the verifier's confirmation
            # requirement (it only counts DETECTED frames), so routing this
            # through submit_candidate would silently produce zero evidence,
            # defeating the entire point of surfacing it. The cooldown above
            # is this path's own, simpler debounce instead.
            self._emit_event(
                track=None, reliability=movement_reliability, health=health, condition=condition,
                zone_id=self._default_zone_id, overrides=movement_event, frame=frame,
            )
            logger.info("[Pipeline] Night-motion fallback: unclassified movement detected, UNCERTAIN evidence emitted")

        # === Layer 4: Task Modules -> Layer 4.5: Event Verification ===
        # A task module firing is only a CANDIDATE (architecture v4 §9).
        # Evidence is packaged and an alert raised only once the Event
        # Verifier promotes a candidate to VERIFIED/ALERTED — see
        # edge/temporal/event_verifier.py. This is the concrete mechanism
        # that stops a single noisy frame from becoming a security alert.
        tick = self._verify_tick
        observed_keys_this_tick: set = set()
        now = time.time()

        def temporal_score_for(track) -> float:
            """T input to the Hybrid Reliability Engine. Neutral (1.0) when
            there's no track to compute it from — e.g. an abandoned-object
            event whose track has already disappeared by the time it fires."""
            if track is None:
                return 1.0
            return self.track_feature_tracker.compute(track.track_id, track.trajectory, now)

        def submit_candidate(event_dict: dict, reliability, track) -> None:
            event_dict.setdefault("lighting_state", getattr(condition, "lighting_state", None))
            event_dict.setdefault("mean_luminance", getattr(condition, "mean_luminance", condition.brightness_mean))
            event_dict.setdefault("dark_pixel_ratio", getattr(condition, "dark_pixel_ratio", None))
            event_dict.setdefault("detection_method", "YOLO")
            event_dict.setdefault("enhancement_applied", enhancement_applied)
            event_type = event_dict["event_type"]
            event_type_value = event_type.value if hasattr(event_type, "value") else str(event_type)
            zone_id = event_dict.get("zone_id", self._default_zone_id)
            key = EventVerifier.make_key(self.camera_id, event_dict.get("track_id"), event_type_value, zone_id)
            observed_keys_this_tick.add(key)
            _state, verified_payload = self.event_verifier.observe(
                key, event_type_value, event_dict, tick,
                reliability.decision_state == DecisionState.DETECTED,
            )
            if verified_payload is not None:
                verified_payload["severity"] = determine_severity(verified_payload, reliability).value
                self._emit_event(track, reliability, health, condition,
                                 zone_id=verified_payload.get("zone_id", self._default_zone_id),
                                 overrides=verified_payload, frame=frame)

        # Real pixel dimensions of THIS frame — zone polygons (fence, line,
        # loitering, checkpoint, verification) are authored in normalized
        # 0-1 coordinates (see edge/rules/modules.py::normalize_point); this
        # is what makes that comparison actually correct regardless of the
        # camera's resolution, instead of comparing raw pixels against an
        # undefined unit.
        frame_height, frame_width = frame.shape[:2]

        # Run behavior module (operates on all active tracks)
        standard_events_this_frame = []
        
        behavior_events = self.behavior_module.update(tracks, frame_width, frame_height)
        for be in behavior_events:
            standard_events_this_frame.append(be)
            track = next((t for t in tracks if t.track_id == be.get("track_id")), None)
            conf = be.get("confidence", 0.0)
            reliability = make_reliability_decision(
                health, condition, conf, calibrated_threshold,
                temporal_score=temporal_score_for(track),
            )
            submit_candidate(be, reliability, track)

        for track in tracks:
            # Fence crossing
            fence_event = self.fence_module.check(track, frame_width, frame_height)
            if fence_event:
                standard_events_this_frame.append(fence_event)
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(fence_event, reliability, track)

            # Line crossing
            line_event = self.line_module.check(track, frame_width, frame_height)
            if line_event:
                standard_events_this_frame.append(line_event)
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(line_event, reliability, track)

            # ANPR
            anpr_result = self.anpr_module.process(track, frame)
            if anpr_result:
                standard_events_this_frame.append(anpr_result)
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(anpr_result, reliability, track)

            # Face detection
            face_result = self.face_module.detect(track, frame)
            if face_result:
                standard_events_this_frame.append(face_result)
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(face_result, reliability, track)
                
        # --- Phase 3 Step 7: Behavioral Analytics Layer ---
        t_behavior_start = time.perf_counter()
        if getattr(self, "behavior_analytics_enabled", False):
            now = time.time()
            features = self.trajectory_layer.update(tracks, now)
            advanced_behavior_events = self.behavior_correlation.update(
                tracks, features, standard_events_this_frame, now,
                frame_width=frame_width, frame_height=frame_height,
            )
            for be in advanced_behavior_events:
                track = next((t for t in tracks if t.track_id == be.get("track_id")), None)
                conf = be.get("confidence", 0.0)
                reliability = make_reliability_decision(
                    health, condition, conf, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(be, reliability, track)
        t_behavior_end = time.perf_counter()

        # Re-check candidates awaiting >1 confirmation (fence crossing, line
        # crossing) that were NOT touched above this tick — i.e. the task
        # module fired once on a past frame at the crossing transition and
        # is now silent, but the track may still be on the new side and
        # needs re-confirming on subsequent frames.
        active_by_track_id = {t.track_id: t for t in tracks}
        for key, payload in self.event_verifier.get_pending_by_type("VIRTUAL_FENCE_CROSSING"):
            if key in observed_keys_this_tick:
                continue
            track = active_by_track_id.get(payload.get("track_id"))
            if track is None:
                continue  # track lost — expire_stale() below will age this out
            expected_inside = str(payload.get("direction", "")).endswith("OUTSIDE_TO_RESTRICTED")
            if self.fence_module.get_track_zone(track.track_id, payload.get("zone_id", self._default_zone_id)) != expected_inside:
                continue  # bounced back before confirmation — do not reconfirm
            reliability = make_reliability_decision(
                health, condition, track.confidence, calibrated_threshold,
                temporal_score=temporal_score_for(track),
            )
            submit_candidate(dict(payload), reliability, track)

        for key, payload in self.event_verifier.get_pending_by_type("LINE_CROSSING"):
            if key in observed_keys_this_tick:
                continue
            track = active_by_track_id.get(payload.get("track_id"))
            if track is None:
                continue  # track lost — expire_stale() below will age this out
            expected_side = -1 if str(payload.get("direction", "")).endswith("A_TO_B") else 1
            if self.line_module.get_track_side(track.track_id, payload.get("zone_id", self._default_zone_id)) != expected_side:
                continue  # bounced back before confirmation — do not reconfirm
            reliability = make_reliability_decision(
                health, condition, track.confidence, calibrated_threshold,
                temporal_score=temporal_score_for(track),
            )
            submit_candidate(dict(payload), reliability, track)

        self.event_verifier.expire_stale(tick)

        # --- Performance instrumentation: frame complete ---
        t_frame_end = time.perf_counter()
        self.metrics.record_frame(
            health_condition_ms=(t_health_condition - t_frame_start) * 1000.0,
            detection_tracking_ms=(t_detection_tracking - t_health_condition) * 1000.0,
            event_processing_ms=(t_frame_end - t_detection_tracking) * 1000.0,
            total_frame_ms=(t_frame_end - t_frame_start) * 1000.0,
        )

    def _flush_event_outbox(self, timeout_seconds: float = 12.0) -> None:
        """Best-effort bounded drain of evidence created by a finite upload."""
        deadline = time.time() + timeout_seconds
        while self.sync_client.get_queue_depth() > 0 and time.time() < deadline:
            result = self.sync_client.sync_once()
            if result.get("status") == "simulated_offline":
                break
            if result.get("remaining", self.sync_client.get_queue_depth()) == 0:
                break
            time.sleep(0.25)
        remaining = self.sync_client.get_queue_depth()
        if remaining:
            logger.warning(f"[Pipeline] EOF flush ended with {remaining} queued event(s)")
        else:
            logger.info("[Pipeline] EOF flush complete; event outbox is empty")

    def _publish_analysis_state(self, state: str) -> None:
        """Publish an explicit lifecycle state after all buffered frames finish."""
        try:
            self._telemetry_sequence += 1
            processed_timestamp = time.time()
            import httpx
            verify: object = self.sync_client._ca_cert if self.sync_client._ca_cert else True
            self._telemetry_sequence += 1
            with httpx.Client(
                timeout=3.0,
                verify=verify,
                cert=self.sync_client._client_cert,
            ) as client:
                response = client.post(
                    f"{self._backend_url}/system/telemetry",
                    json={
                        "camera_id": self.camera_id,
                        "timestamp": processed_timestamp,
                        "video_time": self._last_video_time,
                        "sequence": self._telemetry_sequence,
                        "frame_width": self._last_frame_width,
                        "frame_height": self._last_frame_height,
                        "stream_id": self.stream_id,
                        "analysis_session_id": self.stream_id,
                        "processed_timestamp": processed_timestamp,
                        "analysis_state": state,
                        "tracks": [],
                    },
                    headers=self._edge_auth_headers(),
                )
            response.raise_for_status()
            logger.info(f"[Pipeline] Analysis state published: {state}")
        except Exception as exc:
            logger.warning(f"[Pipeline] Failed to publish analysis state {state}: {exc}")

    def _emit_event(self, track, reliability, health, condition, zone_id, overrides, frame) -> None:
        """Package and enqueue an event for sync."""
        t_start = time.perf_counter()
        try:
            event_overrides = dict(overrides or {})
            # Preserve the source media clock from the exact triggering frame.
            # Never substitute wall-clock time for finite-video events.
            event_overrides.setdefault("video_time", self._last_video_time)
            ep, seq_num = self.packager.package(
                track=track,
                reliability=reliability,
                health=health,
                condition=condition,
                zone_id=zone_id,
                event_overrides=event_overrides,
                frame=frame,
            )
            t_packaged = time.perf_counter()
            self.sync_client.enqueue(ep, seq_num)
            t_enqueued = time.perf_counter()

            # --- Performance instrumentation: decision-to-enqueue latency ---
            timing = dict(getattr(self.packager, "last_timing", {}))
            timing["enqueue_ms"] = (t_enqueued - t_packaged) * 1000.0
            timing["total_event_ms"] = (t_enqueued - t_start) * 1000.0
            self.metrics.record_event(**{
                k: v for k, v in timing.items() if k in PipelineMetrics.EVENT_STAGES
            })

            logger.info(
                f"[Pipeline] Event {ep.event_id[:8]}... "
                f"decision={ep.decision_state} "
                f"seq={seq_num} "
                f"queue_depth={self.sync_client.get_queue_depth()} "
                f"latency={timing['total_event_ms']:.1f}ms"
            )
        except Exception as exc:
            logger.error(f"[Pipeline] Failed to emit event: {exc}")

    def _resync_watchlist(self) -> None:
        """
        Real periodic re-sync (SIH PS 26187) — re-trains the watchlist face
        recognizer from the backend's current, real enrolled photos, so a
        person added/removed from the watchlist takes effect without an
        edge restart. sync_from_backend() itself is non-fatal on failure
        (returns an untrained-but-real recognizer) — this call is
        best-effort, never interrupts the frame loop, same posture as
        _report_camera_health/_report_metrics.
        """
        try:
            self.face_recognizer = sync_from_backend(self._backend_url, auth_token=self._edge_auth_token)
            self.face_module._recognizer = self.face_recognizer
            logger.info(
                f"[Pipeline] Watchlist re-synced (trained={self.face_recognizer.is_trained()})"
            )
        except Exception as exc:
            logger.error(f"[Pipeline] Watchlist re-sync failed (non-fatal): {exc}")

    def _report_metrics(self) -> None:
        """
        Log and persist the real, locally-measured pipeline performance
        summary (architecture v4 §15). Every number here comes from an
        actual perf_counter() reading taken during this run — nothing in
        this method is estimated or invented.
        """
        self.metrics.sample_resources()
        summary = self.metrics.summary()
        fr = summary["frames"]["total_frame_ms"]
        ev = summary["events"]["total_event_ms"]
        gate_stats = self.adaptive_gate.get_stats()
        logger.info(
            f"[Metrics] fps={summary['fps']:.1f} "
            f"frame_mean={fr['mean_ms']:.1f}ms frame_p95={fr['p95_ms']:.1f}ms (n={fr['count']}) "
            f"event_mean={ev['mean_ms']:.1f}ms event_p95={ev['p95_ms']:.1f}ms (n={ev['count']}) "
            f"alerts={summary['alerts_generated']} "
            f"cpu={summary['cpu_percent']} rss_mb={summary['rss_mb']} "
            f"gate={gate_stats['state']} inference_skip_ratio={gate_stats['skip_ratio']:.1%} "
            f"(run={gate_stats['frames_run']},skipped={gate_stats['frames_skipped']})"
        )
        logger.info(
            f"[Telemetry Metrics] fps={self.telemetry_fps} produced={self._telemetry_metrics['produced']} "
            f"dropped={self._telemetry_metrics['dropped']} errors={self._telemetry_metrics['errors']}"
        )
        self.metrics.dump_json(self._metrics_json_path, extra={"adaptive_gate": gate_stats})

        # Push the same real summary to the backend (POST /system/metrics),
        # independent of local disk persistence above — before this, the
        # summary was written only to a local JSON file and never reached
        # the backend at all, so the Performance dashboard page had nothing
        # to show. Best-effort, same posture as _report_camera_health: a
        # failed POST here must never interrupt the frame loop, and this is
        # NOT routed through the offline sync queue — it's a heartbeat, not
        # evidence.
        summary["events"]["queue_depth"] = self.sync_client.get_queue_depth() if hasattr(self, "sync_client") and self.sync_client else 0
        
        try:
            import httpx
            verify: object = self.sync_client._ca_cert if self.sync_client._ca_cert else True
            with httpx.Client(
                timeout=3.0,
                verify=verify,
                cert=self.sync_client._client_cert,
            ) as client:
                response = client.post(
                    f"{self.sync_client.backend_url}/system/metrics",
                    json={
                        "edge_device_id": self.camera_id,
                        "uptime_seconds": summary["uptime_seconds"],
                        "fps": summary["fps"],
                        "frames": summary["frames"],
                        "events": summary["events"],
                        "alerts_generated": summary["alerts_generated"],
                        "telemetry_produced": self._telemetry_metrics["produced"],
                        "telemetry_dropped": self._telemetry_metrics["dropped"],
                        "telemetry_errors": self._telemetry_metrics["errors"],
                        "cpu_percent": summary["cpu_percent"],
                        "rss_mb": summary["rss_mb"],
                        "psutil_available": summary["psutil_available"],
                        "adaptive_gate": gate_stats,
                    },
                    headers=self._edge_auth_headers(),
                )
                response.raise_for_status()
        except Exception as exc:
            logger.debug(f"[Metrics] Backend report failed (non-fatal): {exc}")

    def stop(self) -> None:
        self._running = False

    def _edge_auth_headers(self) -> dict:
        """Return the configured edge bearer credential without logging it."""
        return {"Authorization": f"Bearer {self._edge_auth_token}"} if self._edge_auth_token else {}


def run_edge(config_path: Optional[str] = None) -> None:
    """CLI entry point: load config and run the edge pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    # Load config
    config = {}
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    else:
        # Default config from environment
        camera_id = os.environ.get("CAMERA_ID", os.environ.get("EDGE_DEVICE_ID", "cam-border-01"))
        config = {
            "camera_id": camera_id,
            "video_source": os.environ.get("VIDEO_SOURCE", "demo/videos/vtest.mp4"),
            "backend_url": os.environ.get("BACKEND_URL", "http://localhost:8443"),
            "auth_token": os.environ.get("EDGE_AUTH_TOKEN", ""),
            "simulate_frozen": os.environ.get("SIMULATE_FROZEN_CAMERA", "").lower() == "true",
            "simulate_night": os.environ.get("SIMULATE_NIGHT_CONDITION", "").lower() == "true",
            "zones_config_path": os.environ.get("ZONES_CONFIG_PATH", "demo/scripts/zones_config.json"),
            "key_dir": "certs/edge",
            # Per-camera paths so two simultaneous processes don't collide
            "chain_db_path": f"edge/data/chain_{camera_id}.db",
            "sync_db_path": f"edge/data/sync_{camera_id}.db",
            "clip_dir": "edge/data/clips",
            "metrics_json_path": f"edge/data/metrics_{camera_id}.json",
        }

    pipeline = EdgePipeline(config)
    pipeline.start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NETRAKSH Edge Pipeline")
    parser.add_argument("--config", help="Path to edge config JSON")
    args = parser.parse_args()
    run_edge(args.config)
