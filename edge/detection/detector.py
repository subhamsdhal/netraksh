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
        self.last_raw_detections = []
        self.last_tracker_output_count = 0

    def load(self) -> None:
        """Load detector runtime and initialize tracker. Called once at startup."""
        self._runtime.load()
        
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
            raise RuntimeError("Tracker not loaded.")

        # 1. Run inference using abstracted runtime
        detections = self._runtime.detect(frame, confidence_threshold)
        # Expose the exact detector input to the telemetry layer for
        # diagnostics. This is bounded to the current analyzed frame only.
        self.last_raw_detections = list(detections)

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
                if getattr(t, "frame_id", self._tracker.frame_id) != self._tracker.frame_id:
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
