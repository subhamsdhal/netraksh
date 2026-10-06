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
from collections import deque
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
from edge.tracking.hybrid_tracker import (
    AsyncDetectorWorker,
    DetectorJob,
    OpticalFlowBoxTracker,
    box_center_error,
    box_iou,
)
from edge.runtime_diagnostics import log_runtime_checkpoint
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


def hud_sample_is_due(last_video_time: Optional[float], current_video_time: float, interval: float) -> bool:
    """Return whether the next source-time HUD sample should be emitted."""
    if interval <= 0:
        return False
    if last_video_time is None or current_video_time < last_video_time:
        return True
    return (current_video_time - last_video_time) >= interval


def should_capture_abstain_snapshot(last_snapshot_time: float, now: float) -> bool:
    """
    Tiered evidence capture by condition quality (shared/constants.py's
    ABSTAIN_SNAPSHOT_INTERVAL_SECONDS docstring) — a pure, directly-testable
    function so this throttle decision doesn't require instantiating the
    full EdgePipeline (real YOLO model load and all) just to verify its
    boundary conditions.
    """
    return (now - last_snapshot_time) >= ABSTAIN_SNAPSHOT_INTERVAL_SECONDS


def resolve_detector_model_path(config: dict) -> str:
    """Return the model artifact that the selected detector runtime loads."""
    configured_path = config.get("model_size", os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt"))
    if os.environ.get("DETECTOR_RUNTIME", "pytorch").lower() == "onnx_cpu":
        return os.environ.get("DETECTOR_MODEL_ONNX", configured_path)
    return configured_path


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
        # Durable source identity remains stable across explicit replay
        # generations; stream_id above is the per-run analysis identity.
        self.source_stream_id = config.get("source_stream_id") or self.stream_id
        self.analysis_generation = config.get("analysis_generation")
        self.source_generation = config.get("source_generation")
        self.zone_config_path = config.get("zones_config_path", "demo/scripts/zones_config.json")
        self._running = False

        # Offline Model Readiness Validation (Batch 1 & 2)
        self.yolo_model_path = resolve_detector_model_path(config)
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
        self.adapter.set_frame_tap(self._capture_hud_frame)

        # Telemetry
        self.telemetry_fps = int(os.environ.get("TELEMETRY_FPS", 10))
        self.telemetry_interval = 1.0 / self.telemetry_fps if self.telemetry_fps > 0 else 0
        self._last_tracking_video_time: Optional[float] = None
        self._telemetry_sequence = 0
        self._last_video_time = None
        # The adapter's frame counter includes decoded frames that may be
        # dropped by its bounded queue. Completion must report the last frame
        # that this pipeline actually processed instead.
        self._last_processed_frame_index: Optional[int] = None
        self._last_frame_width = None
        self._last_frame_height = None
        # We need a small bounded queue so if the backend goes down or network
        # is durable/offline-capable. Telemetry is explicitly lossy.
        self.telemetry_queue = Queue(maxsize=2)
        # Keep a little more burst headroom for the lightweight HUD channel.
        # The queue remains bounded and lossy; this only prevents short hosted
        # response-latency spikes from erasing an entire visible interval.
        self.tracking_queue = Queue(maxsize=128)
        self._hud_frame_queue = Queue(maxsize=2)
        self._hud_decoupled = False
        self._hud_tracker = OpticalFlowBoxTracker(
            max_width=int(os.environ.get("IMAGE_TRACKER_MAX_WIDTH", "280")),
            history_frames=int(os.environ.get("TRACKING_HISTORY_FRAMES", "180")),
            max_detector_age_frames=int(os.environ.get("TRACK_MAX_DETECTOR_AGE_FRAMES", "24")),
            max_points=int(os.environ.get("IMAGE_TRACKER_MAX_POINTS", "16")),
            flow_win_size=int(os.environ.get("IMAGE_TRACKER_FLOW_WIN_SIZE", "13")),
            backward_check_interval=int(os.environ.get("IMAGE_TRACKER_BACKWARD_CHECK_INTERVAL", "2")),
        )
        self._hud_state_lock = threading.Lock()
        self._hud_anchor = None
        self._hud_anchor_frame_index = None
        self._hud_emit_times = deque(maxlen=64)
        self._last_hud_video_time: Optional[float] = None
        self._telemetry_metrics = {"produced": 0, "dropped": 0, "errors": 0}
        self._tracking_metrics = {"produced": 0, "transmitted": 0, "dropped": 0, "errors": 0}
        self._tracking_emit_times = deque(maxlen=64)
        self.snapshot_telemetry_fps = float(os.environ.get("SNAPSHOT_TELEMETRY_FPS", "1"))
        self.snapshot_telemetry_interval = (
            1.0 / self.snapshot_telemetry_fps if self.snapshot_telemetry_fps > 0 else 0
        )
        self._last_snapshot_telemetry_time = 0.0

        # Layer 2: Health + Condition
        self.health_monitor = CameraHealthMonitor(
            camera_id=self.camera_id,
            fps_declared=config.get("fps_declared", 25.0),
        )
        self.condition_classifier = SceneConditionClassifier(camera_id=self.camera_id)
        # Scene statistics are detector-keyframe context, not a prerequisite
        # for every optical-flow visualization sample.  Cache the most recent
        # report and refresh it immediately before each detector submission.
        # This preserves detector/event semantics while removing a redundant
        # full-frame grayscale/histogram pass from intermediate frames.
        self._last_condition = None
        self.condition_router = ConditionRouter()

        # Layer 3: Detection + calibration
        self.calibration = CalibrationModule(
            calibration_path=config.get("calibration_path")
        )
        self.detector = DetectionTracker(
            model_size=self.yolo_model_path,
            device=config.get("device", "cpu"),
        )
        self.detector_worker = AsyncDetectorWorker(self.detector)
        self.visual_tracker = OpticalFlowBoxTracker(
            max_width=int(os.environ.get("IMAGE_TRACKER_MAX_WIDTH", "280")),
            history_frames=int(os.environ.get("TRACKING_HISTORY_FRAMES", "180")),
            max_detector_age_frames=int(os.environ.get("TRACK_MAX_DETECTOR_AGE_FRAMES", "24")),
            max_points=int(os.environ.get("IMAGE_TRACKER_MAX_POINTS", "16")),
            flow_win_size=int(os.environ.get("IMAGE_TRACKER_FLOW_WIN_SIZE", "13")),
            backward_check_interval=int(os.environ.get("IMAGE_TRACKER_BACKWARD_CHECK_INTERVAL", "2")),
        )
        self._last_detector_source_time: Optional[float] = None
        self._last_detector_completed_at: Optional[float] = None
        self._last_detector_frame_index: Optional[int] = None
        self._last_detector_latency_ms: Optional[float] = None
        self._last_tracker_latency_ms: Optional[float] = None
        self._detector_refresh_interval_ms: Optional[float] = None
        log_runtime_checkpoint("pipeline_constructed_before_detector_load")
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
        log_runtime_checkpoint("anpr_constructed")

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
        log_runtime_checkpoint("face_module_constructed")

        # Layer 6: Evidence
        key_dir = config.get("key_dir", "certs/edge")
        self.key_manager = EdgeKeyManager(
            private_key_path=os.path.join(key_dir, f"{self.camera_id}.key"),
            public_key_path=os.path.join(key_dir, f"{self.camera_id}.pub"),
        )
        allow_key_generation = config.get(
            "allow_key_generation",
            os.environ.get("EDGE_ALLOW_KEY_GENERATION", "false").lower() == "true",
        )
        self.key_manager.load_or_generate(allow_generate=allow_key_generation)

        chain_path = config.get("chain_db_path", f"edge/data/chain_{self.camera_id}.db")
        self.chain_store = EvidenceChainStore(chain_path)
        self.packager = EvidencePackager(
            camera_id=self.camera_id,
            # stream_id is the durable uploaded-source identity.  The
            # per-run analysis identity is carried separately below.
            stream_id=self.source_stream_id,
            analysis_session_id=self.stream_id,
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
        self.detector_worker.start()
        log_runtime_checkpoint("onnx_detector_and_tracker_loaded")

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

        self._hud_decoupled = True
        hud_thread = threading.Thread(
            target=self._run_hud_loop,
            daemon=True,
            name=f"hud-{self.camera_id}",
        )
        hud_thread.start()
        logger.info("[Pipeline] Decoupled image-grounded HUD tracker started")

        tracking_worker_count = max(
            1,
            int(os.environ.get(
                "TRACKING_TRANSPORT_WORKERS",
                # Keep the hosted transport below the backend's burst limit
                # while leaving enough parallelism to carry the lightweight
                # HUD samples at the required live cadence.
                # A smaller hosted fan-out avoids synchronized request bursts
                # against the backend while still carrying the HUD above the
                # required live cadence.
                "6" if os.environ.get("EDGE_CONSTRAINED_CLOUD", "false").lower() == "true" else "4",
            )),
        )
        tracking_threads = []
        for worker_index in range(tracking_worker_count):
            tracking_thread = threading.Thread(
                target=self._run_tracking_loop,
                daemon=True,
                name=f"tracking-{self.camera_id}-{worker_index + 1}",
            )
            tracking_thread.start()
            tracking_threads.append(tracking_thread)
        logger.info(
            "[Pipeline] Lightweight tracking transport started workers=%d",
            tracking_worker_count,
        )

        try:
            self._run_frame_loop()
        except KeyboardInterrupt:
            logger.info("[Pipeline] Interrupted by user")
        finally:
            completed = self.adapter.eof_reached and self.adapter.state != StreamState.FAILED
            # No PROCESSING packet may be delivered after a terminal state.
            # Stop producers first, discard lossy visualization snapshots,
            # and wait for any in-flight request before publishing the final
            # lifecycle record synchronously.
            if completed:
                # The adapter has stopped producing by this point. Let the
                # lossy visualization workers drain briefly, but never allow
                # a slow hosted HTTP request to prevent the terminal state
                # from being published. Evidence/event queues retain their
                # existing durable flush path below.
                self._hud_frame_queue.join()
                self._running = False
                for queue_name, queue, timeout_seconds in (
                    # The HUD queue carries compact replay samples, not
                    # evidence. Give the bounded transport enough time to
                    # finish the intentional 10 Hz source-time timeline at
                    # EOF, while still bounding a failed backend drain.
                    ("tracking", self.tracking_queue, 45.0),
                    ("telemetry", self.telemetry_queue, 12.0),
                ):
                    deadline = time.monotonic() + timeout_seconds
                    while queue.unfinished_tasks and time.monotonic() < deadline:
                        time.sleep(0.1)
                    if queue.unfinished_tasks:
                        abandoned = 0
                        while True:
                            try:
                                queue.get_nowait()
                                queue.task_done()
                                abandoned += 1
                            except Empty:
                                break
                        logger.warning(
                            "[Pipeline] EOF %s drain timed out; discarded %d lossy item(s)",
                            queue_name,
                            abandoned,
                        )
            else:
                self._running = False
            if not completed:
                self._clear_live_queues()
            # A completed finite-file run must drain its exact HUD samples
            # before the terminal telemetry snapshot freezes the replay
            # timeline. Discarding these queues here produced a misleading
            # "analyzed replay" containing only the first seconds and no boxes.
            hud_thread.join(timeout=5.0)
            for tracking_thread in tracking_threads:
                tracking_thread.join(timeout=5.0)
            telemetry_thread.join(timeout=12.0)
            if completed:
                self._flush_event_outbox()
                # Publish one final metrics snapshot after the drain so the
                # command-center sync indicator sees the real zero queue.
                self._report_metrics()
                self._publish_analysis_state("COMPLETED")
            elif self.adapter.state == StreamState.FAILED:
                self._publish_analysis_state("FAILED")
            if hasattr(self, 'sync_client') and self.sync_client:
                try:
                    self.sync_client.stop()
                except Exception:
                    pass
            self.adapter.stop()
            self.adapter.join()
            self.detector_worker.stop()

    def _clear_live_queues(self) -> None:
        """Discard lossy live packets before a replay/terminal transition."""
        for live_queue in filter(None, (
            getattr(self, "telemetry_queue", None),
            getattr(self, "tracking_queue", None),
            getattr(self, "_hud_frame_queue", None),
        )):
            while not live_queue.empty():
                try:
                    live_queue.get_nowait()
                    live_queue.task_done()
                except Empty:
                    break

    def stop(self) -> None:
        """Gracefully stop the pipeline."""
        logger.info(f"[Pipeline] Stopping frame loop for camera {self.camera_id}")
        self._running = False
        self.detector_worker.stop()
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

        client = httpx.Client(
            # A telemetry item can contain two JPEGs.  One second is a valid
            # fast-fail budget for a tiny heartbeat but not for an HTTPS frame
            # upload to a hosted control plane, where a normal upload can take
            # longer without being a transport failure.
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0),
            verify=verify,
            cert=self.sync_client._client_cert
        )
        telemetry_url = f"{self._backend_url}/system/telemetry"
        while self._running or not self.telemetry_queue.empty():
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
                            if frame_response.status_code != 202:
                                payload["preview_available"] = False
                                self._record_telemetry_transport_error(
                                    "frame", status_code=frame_response.status_code
                                )
                        except httpx.RequestError as exc:
                            payload["preview_available"] = False
                            self._record_telemetry_transport_error("frame", exception=exc)

                    try:
                        telemetry_response = client.post(
                            telemetry_url, json=payload, headers=self._edge_auth_headers()
                        )
                        if telemetry_response.status_code != 202:
                            self._record_telemetry_transport_error(
                                "snapshot", status_code=telemetry_response.status_code
                            )
                    except httpx.RequestError as exc:
                        self._record_telemetry_transport_error("snapshot", exception=exc)
                finally:
                    self.telemetry_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                self._telemetry_metrics["errors"] += 1
                logger.error("[Telemetry] Unexpected worker error: %s: %s", type(e).__name__, e)
        client.close()

    def _capture_hud_frame(self, frame, meta) -> None:
        """Tap every decoded frame into the loss-tolerant HUD queue."""
        try:
            if self._hud_frame_queue.full():
                self._hud_frame_queue.get_nowait()
                self._hud_frame_queue.task_done()
            self._hud_frame_queue.put_nowait((frame, meta))
        except Exception:
            # The HUD is lossy by design; camera ingestion never waits for it.
            pass

    def _run_hud_loop(self) -> None:
        """Track every decoded image independently of heavy event analysis."""
        while self._running or not self._hud_frame_queue.empty():
            try:
                frame, meta = self._hud_frame_queue.get(timeout=0.25)
            except Empty:
                continue
            try:
                with self._hud_state_lock:
                    if self._hud_anchor is not None and self._hud_anchor_frame_index != self._hud_anchor[2]:
                        detector_tracks, detector_frame, detector_index = self._hud_anchor
                        self._hud_tracker.reset()
                        self._hud_tracker.observe(detector_frame, detector_index)
                        anchored = self._hud_tracker.reanchor(detector_tracks, detector_index, detector_frame)
                        self._hud_anchor_frame_index = detector_index
                        logger.info(
                            "[HUD Trace] anchor_frame=%d detector_tracks=%d anchored_tracks=%d",
                            detector_index,
                            len(detector_tracks),
                            len(anchored),
                        )
                    tracks = self._hud_tracker.observe(frame, meta.frame_index)
                self._emit_hud_sample(frame, meta, tracks)
            except Exception as exc:
                logger.debug("[HUD] Lightweight tracker sample failed: %s", type(exc).__name__)
            finally:
                self._hud_frame_queue.task_done()

    def _emit_hud_sample(self, frame, meta, tracks) -> None:
        # The primary analyzed view consumes only exact detector frames.
        # Publishing high-rate optical-flow frames would fill the lossy
        # transport queue and evict the detector anchors needed for replay.
        if self._hud_decoupled:
            return
        current_video_time = float(meta.video_time_seconds)
        if not hud_sample_is_due(
            self._last_hud_video_time,
            current_video_time,
            self.telemetry_interval,
        ):
            return
        self._last_hud_video_time = current_video_time
        frame_h, frame_w = frame.shape[:2]
        processed_timestamp = time.time()
        self._hud_emit_times.append(processed_timestamp)
        span = self._hud_emit_times[-1] - self._hud_emit_times[0]
        measured_hud_fps = ((len(self._hud_emit_times) - 1) / span) if len(self._hud_emit_times) > 1 and span > 0 else None
        with self._hud_state_lock:
            self._telemetry_sequence += 1
            sequence = self._telemetry_sequence
        snapshot = build_frame_snapshot(
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
        payload = {
            "camera_id": self.camera_id, "timestamp": processed_timestamp,
            "video_time": meta.video_time_seconds, "sequence": sequence,
            "frame_index": int(meta.frame_index), "source_timestamp": float(meta.timestamp),
            "processed_timestamp": processed_timestamp,
            "processing_fps": float(self.metrics.current_fps()),
            "source_fps": float(meta.fps_declared) if meta.fps_declared > 0 else None,
            "fps_declared": float(meta.fps_declared) if meta.fps_declared > 0 else None,
            "frame_width": frame_w, "frame_height": frame_h,
            "stream_id": self.source_stream_id, "analysis_session_id": self.stream_id,
            "analysis_generation": self.analysis_generation, "source_generation": self.source_generation,
            "analysis_state": "PROCESSING",
            "scene_condition": str(getattr(self._last_condition, "condition", "UNKNOWN")),
            "detection_method": "OPTICAL_FLOW" if tracks else "NONE",
            "bbox_format": "XYWH", "coordinate_space": "NORMALIZED_FRAME",
            "source_kind": self.adapter.source_kind, "demo_replay": self.adapter.demo_replay,
            "replay_cycle": getattr(meta, "replay_cycle", 0), "raw_detection_count": 0,
            "tracker_output_count": len(tracks), "person_count": snapshot.person_count,
            "vehicle_count": snapshot.vehicle_count, "track_count": snapshot.track_count,
            "active_track_ids": snapshot.active_track_ids, "tracker_output_ids": list(snapshot.tracker_output_ids),
            "raw_detections": [], "preview_available": False,
            "tracks": snapshot.live_tracks(), "visualization_only": True,
            "detector_frame_index": self._last_detector_frame_index,
            "detector_latency_ms": self._last_detector_latency_ms,
            "tracker_latency_ms": self._hud_tracker.last_update_ms,
            "detector_refresh_interval_ms": self._detector_refresh_interval_ms,
            "detector_fps": (1000.0 / self._detector_refresh_interval_ms if self._detector_refresh_interval_ms and self._detector_refresh_interval_ms > 0 else None),
            "hud_fps": measured_hud_fps,
        }
        try:
            if self.tracking_queue.full():
                self.tracking_queue.get_nowait()
                self.tracking_queue.task_done()
                self._tracking_metrics["dropped"] += 1
            self.tracking_queue.put_nowait(payload)
            self._tracking_metrics["produced"] += 1
        except Exception:
            self._tracking_metrics["errors"] += 1

    def _emit_detector_sample(self, packet, tracks) -> None:
        """Publish the detector's own source frame, never a later flow frame.

        The decoupled HUD path emits only optical-flow samples. Without this
        anchor, a detector-only analyzed view has no boxed frames to replay.
        """
        frame = packet.job.frame
        meta = packet.job.meta
        frame_h, frame_w = frame.shape[:2]
        processed_timestamp = time.time()
        snapshot = build_frame_snapshot(
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
        # All boxes in this packet were associated by the detector with this
        # exact image. A rejected malformed box is omitted by the snapshot.
        with self._hud_state_lock:
            self._telemetry_sequence += 1
            sequence = self._telemetry_sequence
        payload = {
            "camera_id": self.camera_id,
            "timestamp": processed_timestamp,
            "video_time": float(meta.video_time_seconds),
            "sequence": sequence,
            "frame_index": int(meta.frame_index),
            "source_timestamp": float(meta.timestamp),
            "processed_timestamp": processed_timestamp,
            "processing_fps": float(self.metrics.current_fps()),
            "source_fps": float(meta.fps_declared) if meta.fps_declared > 0 else None,
            "fps_declared": float(meta.fps_declared) if meta.fps_declared > 0 else None,
            "frame_width": frame_w,
            "frame_height": frame_h,
            "stream_id": self.source_stream_id,
            "analysis_session_id": self.stream_id,
            "analysis_generation": self.analysis_generation,
            "source_generation": self.source_generation,
            "analysis_state": "PROCESSING",
            "scene_condition": str(packet.job.condition.condition),
            "detection_method": "YOLO_BYTE_TRACK",
            "bbox_format": "XYWH",
            "coordinate_space": "NORMALIZED_FRAME",
            "source_kind": self.adapter.source_kind,
            "demo_replay": self.adapter.demo_replay,
            "person_count": snapshot.person_count,
            "vehicle_count": snapshot.vehicle_count,
            "track_count": snapshot.track_count,
            "active_track_ids": snapshot.active_track_ids,
            "tracker_output_ids": snapshot.tracker_output_ids,
            "tracks": snapshot.live_tracks(),
            "preview_available": False,
            "visualization_only": True,
            "detector_frame_index": int(meta.frame_index),
            "detector_latency_ms": packet.detector_ms,
            "detector_fps": (
                1000.0 / self._detector_refresh_interval_ms
                if self._detector_refresh_interval_ms and self._detector_refresh_interval_ms > 0
                else None
            ),
        }
        try:
            if self.tracking_queue.full():
                self.tracking_queue.get_nowait()
                self.tracking_queue.task_done()
                self._tracking_metrics["dropped"] += 1
            self.tracking_queue.put_nowait(payload)
            self._tracking_metrics["produced"] += 1
        except Exception:
            self._tracking_metrics["errors"] += 1

    def _run_tracking_loop(self) -> None:
        """Push small current-frame box metadata without persistence/JPEGs."""
        import httpx
        verify: object = self.sync_client._ca_cert if self.sync_client._ca_cert else True
        client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0),
            verify=verify,
            cert=self.sync_client._client_cert,
        )
        url = f"{self._backend_url}/system/tracking-frame"
        while self._running or not self.tracking_queue.empty():
            try:
                payload = self.tracking_queue.get(timeout=0.25)
                try:
                    response = client.post(url, json=payload, headers=self._edge_auth_headers())
                    if response.status_code != 202:
                        self._record_tracking_transport_error(status_code=response.status_code)
                    else:
                        self._tracking_metrics["transmitted"] += 1
                except httpx.RequestError as exc:
                    self._record_tracking_transport_error(exception=exc)
                finally:
                    self.tracking_queue.task_done()
            except Empty:
                continue
            except Exception as exc:
                self._tracking_metrics["errors"] += 1
                logger.warning("[Tracking] Unexpected transport error: %s", type(exc).__name__)
        client.close()

    def _record_tracking_transport_error(
        self, *, status_code: Optional[int] = None, exception: Optional[Exception] = None,
    ) -> None:
        self._tracking_metrics["errors"] += 1
        if status_code is not None:
            logger.warning("[Tracking] metadata rejected: HTTP %s", status_code)
        elif exception is not None:
            logger.warning("[Tracking] metadata transport error: %s", type(exception).__name__)

    def _record_telemetry_transport_error(
        self,
        channel: str,
        *,
        status_code: Optional[int] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Count and safely identify a telemetry transport failure.

        Never log headers, credentials, or the JPEG/telemetry payload.  The
        channel plus status or exception type is sufficient to distinguish a
        rejected request from a connection/read/write timeout in field logs.
        """
        self._telemetry_metrics["errors"] += 1
        if status_code is not None:
            logger.warning("[Telemetry] %s upload rejected: HTTP %s", channel, status_code)
        elif exception is not None:
            logger.warning(
                "[Telemetry] %s upload transport error: %s: %s",
                channel,
                type(exception).__name__,
                exception,
            )

    def _run_frame_loop(self) -> None:
        """Main frame processing loop."""
        frame_skip = self.config.get("frame_skip", 1)  # process every Nth frame
        frame_count = 0
        last_health_report_time = 0.0
        last_metrics_report_time = 0.0
        last_watchlist_sync_time = time.time()  # already synced once in __init__

        self.adapter.start()
        finite_wall_start: Optional[float] = None
        finite_media_start: Optional[float] = None
        try:
            while self._running:
                frame, meta = self.adapter.get_frame(timeout=0.1)

                if frame is not None and meta is not None:
                    if getattr(meta, "replay_boundary", False):
                        self._reset_replay_state(meta.replay_cycle)
                    frame_count += 1
                    if frame_count % frame_skip == 0:
                        if self.adapter.source_kind == "LOCAL_FINITE_FILE":
                            media_time = float(meta.video_time_seconds)
                            if finite_wall_start is None or finite_media_start is None:
                                finite_wall_start = time.perf_counter()
                                finite_media_start = media_time
                            target_elapsed = max(0.0, media_time - finite_media_start)
                            lead = target_elapsed - (time.perf_counter() - finite_wall_start)
                            if lead > 0:
                                time.sleep(lead)
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
        if hasattr(self, "packager"):
            self.packager.stream_id = self.source_stream_id
            self.packager.analysis_session_id = self.stream_id
        self._telemetry_sequence = 0
        self._last_tracking_video_time = None
        self._last_snapshot_telemetry_time = 0.0
        self._last_detector_source_time = None
        self._last_detector_completed_at = None
        self._last_hud_video_time = None
        self._last_detector_frame_index = None
        self._last_processed_frame_index = None
        with self._hud_state_lock:
            self._hud_anchor = None
            self._hud_anchor_frame_index = None
            self._hud_tracker.reset()
        self._last_condition = None
        self.visual_tracker.reset()
        self._clear_live_queues()

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
        log_runtime_checkpoint("active_inference", active=True)
        # Record the authoritative frame identity before any health gate can
        # return early. This is the frame the pipeline really processed, not
        # merely the number of frames the decoder read.
        self._last_processed_frame_index = int(meta.frame_index)
        self._last_video_time = meta.video_time_seconds
        self._last_frame_width = meta.width
        self._last_frame_height = meta.height

        # The adapter learns the authoritative stream FPS only after opening
        # the source.  Health must compare processing cadence with that source
        # rate, not with a stale caller default (for example 30 against a
        # 10-FPS replay file).
        source_fps = getattr(meta, "fps_declared", None)
        if isinstance(source_fps, (int, float)) and source_fps > 0:
            self.health_monitor.fps_declared = float(source_fps)

        # --- Performance instrumentation: t0 (frame received) ---
        t_frame_start = time.perf_counter()

        # === Layer 2: Gate 1 — Camera Health ===
        health = self.health_monitor.update(frame, meta.timestamp, self.adapter.state)
        self._last_health = health

        # The compute gate depends only on health/motion and existing runtime
        # state, so decide whether a detector keyframe is eligible before
        # paying for scene classification.
        run_inference = self.adaptive_gate.should_run_inference(
            frame_variance=health.frame_variance,
            has_active_tracks=bool(self._trajectories),
            has_pending_candidates=self.event_verifier.get_pending_count() > 0,
        )

        # === Layer 2: Gate 2 — Scene Condition ===
        if (
            self._last_condition is None
            or (run_inference and not self.detector_worker.busy)
        ):
            self._last_condition = self.condition_classifier.classify(frame)
        condition = self._last_condition

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

        # === Layer 3: asynchronous YOLO keyframes + image-grounded tracking ===
        calibrated_threshold = self.calibration.get_threshold(condition.condition)
        detection_frame = frame
        enhancement_applied = False
        # Optical flow consumes every actual decoded frame.  It is independent
        # of detector latency and never blocks on the detector worker.
        tracks = self.visual_tracker.observe(frame, meta.frame_index)
        detector_packet = self.detector_worker.poll_latest()
        detector_tracks = None
        if detector_packet is not None:
            if detector_packet.error is None:
                detector_tracks = self._apply_continuity_guard(
                    detector_packet.tracks, detector_packet.job.frame,
                )
                if self._hud_decoupled:
                    self._emit_detector_sample(detector_packet, detector_tracks)
                flow_at_detector_frame = self.visual_tracker.tracks_at(
                    detector_packet.job.frame_index,
                )
                flow_by_id = {int(track.track_id): track for track in flow_at_detector_frame}
                detector_age_seconds = max(
                    0.0,
                    float(meta.video_time_seconds) - float(detector_packet.job.meta.video_time_seconds),
                )
                for detector_track in detector_tracks:
                    flow_track = flow_by_id.get(int(detector_track.track_id))
                    if flow_track is None:
                        continue
                    flow_box = np.array([
                        flow_track.bbox.x1, flow_track.bbox.y1,
                        flow_track.bbox.x2, flow_track.bbox.y2,
                    ], dtype=np.float32)
                    detector_box = np.array([
                        detector_track.bbox.x1, detector_track.bbox.y1,
                        detector_track.bbox.x2, detector_track.bbox.y2,
                    ], dtype=np.float32)
                    logger.info(
                        "[Flow Reanchor] frame=%d track=%d source_time=%.3f age_s=%.3f "
                        "iou=%.4f center_error_px=%.2f flow_bbox=%s detector_bbox=%s",
                        detector_packet.job.frame_index,
                        detector_track.track_id,
                        float(detector_packet.job.meta.video_time_seconds),
                        detector_age_seconds,
                        box_iou(flow_box, detector_box),
                        box_center_error(flow_box, detector_box),
                        [round(float(value), 1) for value in flow_box],
                        [round(float(value), 1) for value in detector_box],
                    )
                tracks = self.visual_tracker.reanchor(
                    detector_tracks,
                    detector_packet.job.frame_index,
                    detector_packet.job.frame,
                )
                if self._hud_decoupled:
                    with self._hud_state_lock:
                        self._hud_anchor = (
                            list(detector_tracks),
                            detector_packet.job.frame.copy(),
                            int(detector_packet.job.frame_index),
                        )
                self._verify_tick += 1
                for expired_id in self.continuity_guard.expire_stale(time.time()):
                    self.track_feature_tracker.forget(expired_id)
                for track in detector_tracks:
                    self._trajectories[track.track_id] = track.trajectory
                    self._track_last_snapshot[track.track_id] = {
                        "histogram": compute_track_histogram(detector_packet.job.frame, track.bbox),
                        "centroid": track.bbox.centroid,
                    }
                    self.track_feature_tracker.observe(track.track_id, time.time())
                active_ids = {track.track_id for track in detector_tracks}
                stale = [key for key in self._trajectories if key not in active_ids]
                for key in stale[:20]:
                    snapshot = self._track_last_snapshot.get(key)
                    if snapshot is not None and snapshot["histogram"] is not None:
                        self.continuity_guard.remember_lost(
                            key, snapshot["histogram"], snapshot["centroid"],
                            self._trajectories.get(key, []), time.time(),
                        )
                    else:
                        self.track_feature_tracker.forget(key)
                    self._trajectories.pop(key, None)
                    self._known_track_ids.discard(key)
                    for native_id in [n for n, canonical in self._track_id_map.items() if canonical == key]:
                        self._track_id_map.pop(native_id, None)
                    self._track_last_snapshot.pop(key, None)

                completed_at = detector_packet.completed_at
                if self._last_detector_completed_at is not None:
                    self._detector_refresh_interval_ms = (
                        completed_at - self._last_detector_completed_at
                    ) * 1000.0
                self._last_detector_completed_at = completed_at
                self._last_detector_frame_index = detector_packet.job.frame_index
                self._last_detector_latency_ms = detector_packet.detector_ms
                self._last_tracker_latency_ms = self.visual_tracker.last_update_ms

        if run_inference and not self.detector_worker.busy:
            policy = self.condition_router.route(condition.condition)
            detection_frame = enhance_for_detection(frame, policy)
            enhancement_applied = detection_frame is not frame
            source_copy = frame.copy()
            detector_copy = detection_frame.copy() if enhancement_applied else source_copy
            submitted = self.detector_worker.submit(DetectorJob(
                frame=source_copy,
                detector_frame=detector_copy,
                frame_index=int(meta.frame_index),
                meta=meta,
                health=health,
                condition=condition,
                confidence_threshold=calibrated_threshold,
                enhancement_applied=enhancement_applied,
                submitted_at=time.time(),
            ))
            if submitted:
                self._last_detector_source_time = float(meta.video_time_seconds)

        t_detection_tracking = time.perf_counter()

        # === Live Telemetry (architecture v4 §16) ===
        tracking_video_time = float(meta.video_time_seconds)
        # Every processed frame has an image-grounded optical-flow/tracker
        # result, including an explicit empty result when all tracks leave the
        # frame. Emitting every processed frame prevents detector latency from
        # turning a source-time cadence gate into a stale, sub-8Hz HUD. The
        # bounded transport queue remains the loss-tolerant back-pressure
        # boundary; event/evidence semantics stay on their existing keyframes.
        tracking_due = self.telemetry_fps > 0
        if tracking_due:
            self._last_tracking_video_time = tracking_video_time
            self._telemetry_sequence += 1
            frame_h, frame_w = frame.shape[:2] if frame is not None else (1, 1)
            processed_timestamp = time.time()
            self._tracking_emit_times.append(processed_timestamp)
            measured_hud_fps = None
            if len(self._tracking_emit_times) >= 2:
                tracking_span = self._tracking_emit_times[-1] - self._tracking_emit_times[0]
                if tracking_span > 0:
                    measured_hud_fps = (len(self._tracking_emit_times) - 1) / tracking_span
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
            for detection in (detector_packet.raw_detections if detector_packet is not None else []):
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
                # Source cadence is media metadata measured by CameraAdapter,
                # never a processing-rate estimate or dashboard default.
                "source_fps": float(meta.fps_declared) if getattr(meta, "fps_declared", 0) > 0 else None,
                "fps_declared": float(meta.fps_declared) if getattr(meta, "fps_declared", 0) > 0 else None,
                "expected_interval_ms": expected_interval_ms,
                "frame_width": frame_w,
                "frame_height": frame_h,
                "stream_id": self.source_stream_id,
                "analysis_session_id": self.stream_id,
                "analysis_generation": self.analysis_generation,
                "source_generation": self.source_generation,
                "analysis_state": "PROCESSING",
                "scene_condition": str(condition.condition),
                "lighting_state": getattr(condition, "lighting_state", None),
                "mean_luminance": getattr(condition, "mean_luminance", condition.brightness_mean),
                "enhancement_applied": enhancement_applied,
                "detection_method": (
                    "YOLO_BYTE_TRACK" if detector_packet is not None
                    else "OPTICAL_FLOW" if tracks else "NONE"
                ),
                "bbox_format": "XYWH",
                "coordinate_space": "NORMALIZED_FRAME",
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
                "visualization_only": True,
                "detector_frame_index": self._last_detector_frame_index,
                "detector_latency_ms": self._last_detector_latency_ms,
                "tracker_latency_ms": self.visual_tracker.last_update_ms,
                "detector_refresh_interval_ms": self._detector_refresh_interval_ms,
                "detector_fps": (
                    1000.0 / self._detector_refresh_interval_ms
                    if self._detector_refresh_interval_ms and self._detector_refresh_interval_ms > 0
                    else None
                ),
                "hud_fps": measured_hud_fps,
            }
            trace_path = os.environ.get("TELEMETRY_TRACE_PATH")
            if trace_path:
                try:
                    trace_record = {key: value for key, value in payload.items() if not key.startswith("_")}
                    with open(trace_path, "a", encoding="utf-8") as trace_file:
                        trace_file.write(json.dumps(trace_record, sort_keys=True) + "\n")
                except OSError as exc:
                    logger.debug("[Telemetry] Trace write failed: %s", exc)
            if not self._hud_decoupled:
                try:
                    if self.tracking_queue.full():
                        try:
                            self.tracking_queue.get_nowait()
                            self.tracking_queue.task_done()
                            self._tracking_metrics["dropped"] += 1
                        except Empty:
                            pass
                    self.tracking_queue.put_nowait(dict(payload))
                    self._tracking_metrics["produced"] += 1
                except Exception:
                    self._tracking_metrics["errors"] += 1

            # Full JPEG + durable latest-state telemetry stays diagnostic and
            # low-cadence.  Its encoding/upload can no longer gate HUD boxes.
            snapshot_due = (
                self.snapshot_telemetry_fps > 0
                and (processed_timestamp - self._last_snapshot_telemetry_time)
                >= self.snapshot_telemetry_interval
            )
            if snapshot_due:
                self._last_snapshot_telemetry_time = processed_timestamp
                snapshot_payload = dict(payload)
                snapshot_payload["visualization_only"] = False
                try:
                    import base64
                    import cv2
                    annotated_frame = render_snapshot(frame, frame_snapshot, hud=True)
                    clean_ok, clean_encoded = cv2.imencode(
                        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 68]
                    )
                    annotated_ok, annotated_encoded = cv2.imencode(
                        ".jpg", annotated_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 76]
                    )
                    if clean_ok and annotated_ok:
                        snapshot_payload["_clean_preview_jpeg_base64"] = base64.b64encode(
                            clean_encoded.tobytes()
                        ).decode("ascii")
                        snapshot_payload["_annotated_preview_jpeg_base64"] = base64.b64encode(
                            annotated_encoded.tobytes()
                        ).decode("ascii")
                        snapshot_payload["preview_available"] = True
                except Exception as exc:
                    logger.debug("[Telemetry] Diagnostic JPEG unavailable: %s", exc)
                try:
                    if self.telemetry_queue.full():
                        try:
                            self.telemetry_queue.get_nowait()
                            self.telemetry_queue.task_done()
                            self._telemetry_metrics["dropped"] += 1
                        except Empty:
                            pass
                    self.telemetry_queue.put_nowait(snapshot_payload)
                    self._telemetry_metrics["produced"] += 1
                except Exception:
                    self._telemetry_metrics["errors"] += 1

        # Intermediate optical-flow samples are visualization-only.  Existing
        # event/reliability/evidence rules run exactly once per completed
        # detector keyframe, never at the higher HUD cadence.
        if detector_packet is None or detector_tracks is None:
            t_frame_end = time.perf_counter()
            self.metrics.record_frame(
                health_condition_ms=(t_health_condition - t_frame_start) * 1000.0,
                detection_tracking_ms=(t_detection_tracking - t_health_condition) * 1000.0,
                event_processing_ms=0.0,
                total_frame_ms=(t_frame_end - t_frame_start) * 1000.0,
            )
            return

        # From here down, retain the original event semantics but bind them to
        # the exact detector keyframe and context that produced these tracks.
        frame = detector_packet.job.frame
        meta = detector_packet.job.meta
        health = detector_packet.job.health
        condition = detector_packet.job.condition
        calibrated_threshold = detector_packet.job.confidence_threshold
        enhancement_applied = detector_packet.job.enhancement_applied
        tracks = detector_tracks
        run_inference = True
        self._event_video_time = meta.video_time_seconds

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
        import httpx
        processed_timestamp = time.time()
        verify: object = self.sync_client._ca_cert if self.sync_client._ca_cert else True
        payload = {
            "camera_id": self.camera_id,
            "timestamp": processed_timestamp,
            "video_time": self._last_video_time,
            "frame_index": self._last_processed_frame_index,
            "frame_width": self._last_frame_width,
            "frame_height": self._last_frame_height,
            "stream_id": self.source_stream_id,
            "analysis_session_id": self.stream_id,
            "analysis_generation": self.analysis_generation,
            "source_generation": self.source_generation,
            "processed_timestamp": processed_timestamp,
            "analysis_state": state,
            "tracks": [],
        }
        for attempt in range(2):
            try:
                self._telemetry_sequence += 1
                payload["sequence"] = self._telemetry_sequence
                with httpx.Client(
                    timeout=httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0),
                    verify=verify,
                    cert=self.sync_client._client_cert,
                ) as client:
                    response = client.post(
                        f"{self._backend_url}/system/telemetry",
                        json=payload,
                        headers=self._edge_auth_headers(),
                    )
                response.raise_for_status()
                logger.info(f"[Pipeline] Analysis state published: {state}")
                return
            except Exception as exc:
                if attempt == 0:
                    logger.warning(f"[Pipeline] Analysis state publish retry for {state}: {exc}")
                    time.sleep(0.5)
                else:
                    logger.warning(f"[Pipeline] Failed to publish analysis state {state}: {exc}")

    def _emit_event(self, track, reliability, health, condition, zone_id, overrides, frame) -> None:
        """Package and enqueue an event for sync."""
        t_start = time.perf_counter()
        try:
            event_overrides = dict(overrides or {})
            # Preserve the source media clock from the exact triggering frame.
            # Never substitute wall-clock time for finite-video events.
            event_overrides.setdefault(
                "video_time",
                getattr(self, "_event_video_time", None) or self._last_video_time,
            )
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

            logger.info(
                "[EventTrace] EVENT_OBJECT_CREATED event_id=%s camera_id=%s "
                "stream_id=%s analysis_session_id=%s seq=%s",
                ep.event_id,
                ep.camera_id,
                ep.stream_id,
                ep.analysis_session_id,
                seq_num,
            )

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
        runtime_stage = getattr(getattr(self.detector, "_runtime", None), "last_stage_ms", {})
        logger.info(
            "[Hybrid Metrics] tracking_produced=%d transmitted=%d dropped=%d errors=%d "
            "optical_ms=%.2f detector_ms=%s bytetrack_ms=%.2f refresh_ms=%s "
            "detector_busy=%s detector_queue=%d",
            self._tracking_metrics["produced"], self._tracking_metrics["transmitted"], self._tracking_metrics["dropped"],
            self._tracking_metrics["errors"], self.visual_tracker.last_update_ms,
            f"{runtime_stage.get('total', 0.0):.2f}" if runtime_stage else "N/A",
            float(getattr(self.detector, "last_tracker_ms", 0.0)),
            f"{self._detector_refresh_interval_ms:.1f}" if self._detector_refresh_interval_ms else "N/A",
            self.detector_worker.busy, self.detector_worker.queue_depth,
        )
        self.metrics.dump_json(self._metrics_json_path, extra={
            "adaptive_gate": gate_stats,
            "detector_stage_ms": runtime_stage,
            "image_tracker_ms": self.visual_tracker.last_update_ms,
            "detector_refresh_interval_ms": self._detector_refresh_interval_ms,
            "tracking_transport": dict(self._tracking_metrics),
        })

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
