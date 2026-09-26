"""
NETRAKSH Edge — YOLO + ByteTrack detection and tracking (Layer 3 / Gate 3).
Uses YOLOv8n for person/vehicle detection.
ByteTrack (via ultralytics) for multi-object tracking.
Confidence threshold is bucket-calibrated (not global).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from edge.detection.runtime import create_runtime, _YOLO_CLASS_MAP, _YOLO_VEHICLE_SUBTYPE_MAP

from shared.constants import DetectionClass, SceneCondition, VehicleSubtype
from shared.schemas import BoundingBox, Point, TrackData

logger = logging.getLogger(__name__)

# We import these from edge.detection.runtime to avoid duplication.

# Border-tuned ByteTrack config (architecture v4 §4 — Track Continuity Guard):
# same as ultralytics' bundled bytetrack.yaml except a larger track_buffer.
# Resolved as an absolute path so it works regardless of the process's CWD.
_DEFAULT_TRACKER_CONFIG = str(
    Path(__file__).resolve().parent.parent / "config" / "bytetrack_border.yaml"
)


@dataclass
class _NumpyTrack:
    """Small ByteTrack state object used by the ONNX cloud path.

    It intentionally mirrors ByteTrack's two-stage high/low confidence
    association and track-buffer semantics without importing Ultralytics or
    PyTorch into the constrained cloud worker.
    """

    bbox: np.ndarray
    score: float
    cls: int
    track_id: int
    frame_id: int
    lost_frames: int = 0
    velocity: np.ndarray | None = None


def _iou_matrix(left: list[np.ndarray], right: list[np.ndarray]) -> np.ndarray:
    if not left or not right:
        return np.zeros((len(left), len(right)), dtype=np.float32)
    a = np.asarray(left, dtype=np.float32)
    b = np.asarray(right, dtype=np.float32)
    ax1, ay1, ax2, ay2 = a[:, 0, None], a[:, 1, None], a[:, 2, None], a[:, 3, None]
    bx1, by1, bx2, by2 = b[:, 0][None, :], b[:, 1][None, :], b[:, 2][None, :], b[:, 3][None, :]
    inter = np.maximum(0.0, np.minimum(ax2, bx2) - np.maximum(ax1, bx1)) * np.maximum(
        0.0, np.minimum(ay2, by2) - np.maximum(ay1, by1)
    )
    area_a = np.maximum(0.0, ax2 - ax1) * np.maximum(0.0, ay2 - ay1)
    area_b = np.maximum(0.0, bx2 - bx1) * np.maximum(0.0, by2 - by1)
    return inter / np.maximum(area_a + area_b - inter, 1e-6)


def _lap_matches(cost: np.ndarray, threshold: float) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Solve ByteTrack's gated assignment using the repository's lapx dep."""
    if cost.size == 0:
        return [], list(range(cost.shape[0])), list(range(cost.shape[1]))
    import lap

    _, row, col = lap.lapjv(cost.astype(np.float64), extend_cost=True, cost_limit=float(threshold))
    matches = [(i, j) for i, j in enumerate(row) if j >= 0 and j < cost.shape[1] and cost[i, j] <= threshold]
    matched_rows = {i for i, _ in matches}
    matched_cols = {j for _, j in matches}
    return matches, [i for i in range(cost.shape[0]) if i not in matched_rows], [j for j in range(cost.shape[1]) if j not in matched_cols]


class _NumpyByteTracker:
    """Dependency-light ByteTrack association for ONNX CPU inference."""

    def __init__(self, config: dict):
        self.high = float(config.get("track_high_thresh", 0.25))
        self.low = float(config.get("track_low_thresh", 0.1))
        self.new = float(config.get("new_track_thresh", 0.25))
        self.buffer = int(config.get("track_buffer", 120))
        self.match = float(config.get("match_thresh", 0.8))
        self.frame_id = 0
        self._next_id = 1
        self._tracks: list[_NumpyTrack] = []

    @staticmethod
    def _predict(track: _NumpyTrack) -> None:
        if track.velocity is not None:
            track.bbox = track.bbox + track.velocity

    def _associate(self, tracks: list[_NumpyTrack], detections: list[DetectionResult], threshold: float):
        if not tracks or not detections:
            return [], list(range(len(tracks))), list(range(len(detections)))
        ious = _iou_matrix(
            [t.bbox for t in tracks],
            [np.array([d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2], dtype=np.float32) for d in detections],
        )
        for i, track in enumerate(tracks):
            for j, det in enumerate(detections):
                if track.cls != det.class_id:
                    ious[i, j] = 0.0
        return _lap_matches(1.0 - ious, 1.0 - threshold)

    def _update_track(self, track: _NumpyTrack, det: DetectionResult) -> None:
        previous = track.bbox.copy()
        current = np.array([det.bbox.x1, det.bbox.y1, det.bbox.x2, det.bbox.y2], dtype=np.float32)
        track.velocity = current - previous
        track.bbox = current
        track.score = det.confidence
        track.cls = det.class_id
        track.lost_frames = 0
        track.frame_id = self.frame_id

    def update(self, detections: list[DetectionResult]) -> list[_NumpyTrack]:
        self.frame_id += 1
        for track in self._tracks:
            self._predict(track)

        high = [d for d in detections if d.confidence >= self.high]
        low = [d for d in detections if self.low <= d.confidence < self.high]
        active = [t for t in self._tracks if t.lost_frames == 0]
        lost = [t for t in self._tracks if t.lost_frames > 0]
        matches, unmatched_active, unmatched_high = self._associate(active + lost, high, self.match)
        pool = active + lost
        for track_idx, det_idx in matches:
            self._update_track(pool[track_idx], high[det_idx])

        unmatched_tracks = [pool[i] for i in unmatched_active]
        matches_low, unmatched_after_low, _ = self._associate(unmatched_tracks, low, 0.5)
        for track_idx, det_idx in matches_low:
            self._update_track(unmatched_tracks[track_idx], low[det_idx])

        matched_ids = {pool[i].track_id for i, _ in matches}
        matched_ids.update(unmatched_tracks[i].track_id for i, _ in matches_low)
        for track in pool:
            if track.track_id not in matched_ids:
                track.lost_frames += 1

        for det_idx in unmatched_high:
            det = high[det_idx]
            if det.confidence >= self.new:
                self._tracks.append(_NumpyTrack(
                    bbox=np.array([det.bbox.x1, det.bbox.y1, det.bbox.x2, det.bbox.y2], dtype=np.float32),
                    score=det.confidence,
                    cls=det.class_id,
                    track_id=self._next_id,
                    frame_id=self.frame_id,
                ))
                self._next_id += 1

        self._tracks = [t for t in self._tracks if t.lost_frames <= self.buffer]
        return [t for t in self._tracks if t.lost_frames == 0 and t.frame_id == self.frame_id]


class DetectionTracker:
    """
    Wraps Ultralytics YOLO (yolov8n) + ByteTrack.
    Returns tracked objects for each frame.
    """

    def __init__(
        self,
        model_size: str = "yolov8n.pt",
        device: str = "cpu",
        tracker_config: Optional[str] = None,
    ):
        self.model_size = os.environ.get("DETECTOR_MODEL", model_size)
        self.device = device
        
        # Read desired tracker from environment (bytetrack vs botsort)
        tracker_type = os.environ.get("TRACKER", "bytetrack").lower()
        
        if tracker_config is None:
            if tracker_type == "botsort":
                tracker_config = str(Path(__file__).resolve().parent.parent / "config" / "botsort_border.yaml")
            else:
                tracker_config = _DEFAULT_TRACKER_CONFIG
                
        # Falls back to the border-tuned config if the given/default path doesn't exist, 
        # and further to ultralytics' own bundled yaml if even that is missing
        if not os.path.exists(tracker_config):
            fallback_yaml = "botsort.yaml" if tracker_type == "botsort" else "bytetrack.yaml"
            logger.warning(
                f"[Detector] Tracker config not found at {tracker_config}; "
                f"falling back to ultralytics' bundled {fallback_yaml}"
            )
            tracker_config = fallback_yaml
            
        self.tracker_config = tracker_config
        self._runtime = create_runtime()
        self._tracker = None
        self._numpy_tracker: _NumpyByteTracker | None = None
        self.last_raw_detections = []
        self.last_tracker_output_count = 0

    def load(self) -> None:
        """Load detector runtime and initialize tracker. Called once at startup."""
        self._runtime.load()

        # ONNX CPU is the constrained cloud runtime.  Keep the real ByteTrack
        # association semantics, but do not import Ultralytics (which imports
        # PyTorch) merely to wrap NumPy detections in a Boxes object.
        if os.environ.get("DETECTOR_RUNTIME", "pytorch").lower() == "onnx_cpu":
            import yaml

            with open(self.tracker_config, "r") as f:
                self._numpy_tracker = _NumpyByteTracker(yaml.safe_load(f) or {})
            logger.info("[Detector] NumPy ByteTrack initialized for ONNX CPU runtime")
            return
        
        try:
            from ultralytics.trackers import BYTETracker, BOTSORT
            tracker_type = os.environ.get("TRACKER", "bytetrack").lower()
            import yaml
            from ultralytics.utils import IterableSimpleNamespace
            
            with open(self.tracker_config, "r") as f:
                cfg = yaml.safe_load(f)
            
            args = IterableSimpleNamespace(**cfg)
            if tracker_type == "botsort":
                self._tracker = BOTSORT(args=args)
            else:
                self._tracker = BYTETracker(args=args)
            logger.info(f"[Detector] Standalone tracker ({tracker_type}) initialized")
        except Exception as exc:
            logger.error(f"[Detector] Failed to initialize tracker: {exc}")
            raise

    def detect_and_track(
        self,
        frame: np.ndarray,
        condition: SceneCondition,
        confidence_threshold: float,
        existing_trajectories: Optional[Dict[int, List[Point]]] = None,
    ) -> List[TrackData]:
        """
        Run YOLO inference + ByteTrack association.
        Returns a list of TrackData objects (one per tracked object).
        """
        if self._tracker is None:
            if self._numpy_tracker is None:
                raise RuntimeError("Tracker not loaded.")

        # 1. Run inference using abstracted runtime
        detections = self._runtime.detect(frame, confidence_threshold)
        # Expose the exact detector input to the telemetry layer for
        # diagnostics. This is bounded to the current analyzed frame only.
        self.last_raw_detections = list(detections)

        if self._numpy_tracker is not None:
            tracked_objects = self._numpy_tracker.update(detections)
            self.last_tracker_output_count = len(tracked_objects)
            tracks = []
            for tracked in tracked_objects:
                cls_id = int(tracked.cls)
                if cls_id not in _YOLO_CLASS_MAP:
                    continue
                bbox_arr = tracked.bbox
                track_id = int(tracked.track_id)
                traj = []
                if existing_trajectories and track_id in existing_trajectories:
                    traj = list(existing_trajectories[track_id])
                bbox = BoundingBox(x1=float(bbox_arr[0]), y1=float(bbox_arr[1]), x2=float(bbox_arr[2]), y2=float(bbox_arr[3]))
                traj.append(bbox.centroid)
                if len(traj) > 50:
                    traj = traj[-50:]
                tracks.append(TrackData(
                    track_id=track_id,
                    detection_class=_YOLO_CLASS_MAP[cls_id],
                    bbox=bbox,
                    confidence=float(tracked.score),
                    trajectory=traj,
                    vehicle_subtype=_YOLO_VEHICLE_SUBTYPE_MAP.get(cls_id),
                    source_class_id=cls_id,
                    tracker_state="TRACKED_CURRENT_FRAME",
                    matched_current_frame=True,
                ))
            return tracks

        # 2. Build the official ultralytics Boxes object expected by the tracker.
        # BYTETracker.update() (installed source confirmed) accesses:
        #   results.conf  → data[:, -2]
        #   results.cls   → data[:, -1]
        #   results.xywh  → computed from data[:, :4] (xyxy → xywh)
        # The authoritative way to satisfy this is to construct the real
        # ultralytics.engine.results.Boxes class (BaseTensor subclass).
        # Ultralytics 8.3.0 installed (verified from __init__.py).
        import torch
        from ultralytics.engine.results import Boxes as UltralyticsBoxes

        tracks = []
        orig_shape = frame.shape[:2]  # (height, width) — required by Boxes

        if not detections:
            # Construct empty Boxes — tracker handles len(results.conf)==0
            empty_t = torch.zeros((0, 6), dtype=torch.float32)
            empty_boxes = UltralyticsBoxes(empty_t, orig_shape)
            tracked_objects = self._tracker.update(empty_boxes, frame)
            self.last_tracker_output_count = len(tracked_objects)
            return tracks

        det_array = np.zeros((len(detections), 6), dtype=np.float32)
        for i, d in enumerate(detections):
            # Column layout required by Boxes: [x1, y1, x2, y2, conf, cls]
            det_array[i] = [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2, d.confidence, d.class_id]

        det_tensor = torch.tensor(det_array, dtype=torch.float32)
        det_boxes = UltralyticsBoxes(det_tensor, orig_shape)

        # 3. Update tracker with the real Boxes object
        tracked_objects = self._tracker.update(det_boxes, frame)
        self.last_tracker_output_count = len(tracked_objects)
        
        for t in tracked_objects:
            if hasattr(t, "tlbr"):
                track_frame_id = getattr(t, "frame_id", None)
                tracker_frame_id = getattr(self._tracker, "frame_id", None)
                # Real STrack objects expose integer frame IDs. Keep the stale
                # track guard strict for those values without treating a test
                # double or alternate tracker object's dynamic attribute as a
                # real frame mismatch.
                if (
                    isinstance(track_frame_id, (int, np.integer))
                    and isinstance(tracker_frame_id, (int, np.integer))
                    and track_frame_id != tracker_frame_id
                ):
                    continue
                # Direct STrack access if it returns raw tracks
                bbox_arr = t.tlbr
                track_id = int(t.track_id)
                cls_id = int(t.cls) if hasattr(t, 'cls') else 0
                conf = float(t.score)
            else:
                # If it returns a tensor/array
                bbox_arr = t[:4]
                track_id = int(t[4])
                conf = float(t[5])
                cls_id = int(t[6]) if len(t) > 6 else 0
                
            if cls_id not in _YOLO_CLASS_MAP:
                continue

            bbox = BoundingBox(x1=bbox_arr[0], y1=bbox_arr[1], x2=bbox_arr[2], y2=bbox_arr[3])

            traj = []
            if existing_trajectories and track_id in existing_trajectories:
                traj = list(existing_trajectories[track_id])
            traj.append(bbox.centroid)
            if len(traj) > 50:
                traj = traj[-50:]

            tracks.append(TrackData(
                track_id=track_id,
                detection_class=_YOLO_CLASS_MAP[cls_id],
                bbox=bbox,
                confidence=conf,
                trajectory=traj,
                vehicle_subtype=_YOLO_VEHICLE_SUBTYPE_MAP.get(cls_id),
                source_class_id=cls_id,
                tracker_state="TRACKED_CURRENT_FRAME",
                matched_current_frame=True,
            ))

        return tracks

    def get_avg_fps(self) -> float:
        return self._runtime.get_avg_fps()


class NightMotionFallback:
    """
    Frame-differencing motion fallback for LOW_LIGHT_NIGHT when detector
    confidence collapses below threshold. Emits 'movement_detected_but_class_uncertain'
    events rather than DETECTED — honest about what we know.
    """

    def __init__(self):
        self._prev_gray: Optional[np.ndarray] = None
        self._persistence = 0
        self._last_area = 0.0

    def detect_motion(self, frame: np.ndarray, min_area: int = 500) -> bool:
        """Compatibility boolean API; use ``detect_motion_details`` in the
        pipeline when area/persistence metadata is needed."""
        return self.detect_motion_details(frame, min_area=min_area, required_frames=1)["motion"]

    def detect_motion_details(
        self,
        frame: np.ndarray,
        min_area: Optional[int] = None,
        required_frames: Optional[int] = None,
    ) -> dict:
        """Return explainable frame-difference motion metrics.

        A candidate requires a minimum changed contour area and consecutive
        observations.  This rejects compression/noise flicker while keeping
        the original boolean behavior available to existing callers.
        """
        import os
        if min_area is None:
            min_area = int(os.environ.get("NIGHT_MOTION_MIN_AREA", "500"))
        if required_frames is None:
            required_frames = max(1, int(os.environ.get("NIGHT_MOTION_REQUIRED_FRAMES", "2")))
        gray = np.array(frame, dtype=np.uint8)
        if len(gray.shape) == 3:
            import cv2
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        import cv2
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            self._persistence = 0
            self._last_area = 0.0
            return {"motion": False, "area": 0.0, "persistence": 0}

        diff = cv2.absdiff(self._prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        dilated = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        self._prev_gray = gray

        area = max((float(cv2.contourArea(c)) for c in contours), default=0.0)
        if area >= min_area:
            self._persistence += 1
        else:
            self._persistence = 0
        self._last_area = area
        return {
            "motion": self._persistence >= required_frames,
            "area": area,
            "persistence": self._persistence,
        }
