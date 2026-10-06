"""Asynchronous detector + image-grounded intermediate box tracking.

The heavy detector owns track identity.  Between detector completions, this
module propagates those boxes with pyramidal Lucas-Kanade optical flow over the
actual decoded source frames.  It never interpolates coordinates from time
alone and it drops a box as soon as image support becomes unreliable.
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from queue import Empty, Queue
from typing import Any, Iterable, Optional

import cv2
import numpy as np

from shared.schemas import BoundingBox, Point, TrackData

logger = logging.getLogger(__name__)


@dataclass
class DetectorJob:
    frame: np.ndarray
    detector_frame: np.ndarray
    frame_index: int
    meta: Any
    health: Any
    condition: Any
    confidence_threshold: float
    enhancement_applied: bool
    submitted_at: float


@dataclass
class DetectorPacket:
    job: DetectorJob
    tracks: list[TrackData]
    raw_detections: list[Any]
    detector_ms: float
    tracker_ms: float
    completed_at: float
    error: Optional[str] = None


class AsyncDetectorWorker:
    """Single persistent detector session with latest-value job semantics."""

    def __init__(self, detector):
        self.detector = detector
        self._jobs: Queue[DetectorJob] = Queue(maxsize=1)
        self._results: Queue[DetectorPacket] = Queue(maxsize=2)
        self._stop = threading.Event()
        self._busy = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.submitted = 0
        self.completed = 0
        self.dropped_results = 0

    @property
    def busy(self) -> bool:
        return self._busy.is_set() or not self._jobs.empty()

    @property
    def queue_depth(self) -> int:
        return self._jobs.qsize()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="detector-keyframes")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def submit(self, job: DetectorJob) -> bool:
        if self.busy:
            return False
        try:
            self._jobs.put_nowait(job)
            self._busy.set()
            self.submitted += 1
            return True
        except Exception:
            return False

    def poll_latest(self) -> Optional[DetectorPacket]:
        latest = None
        while True:
            try:
                latest = self._results.get_nowait()
                self._results.task_done()
            except Empty:
                return latest

    def _publish(self, packet: DetectorPacket) -> None:
        if self._results.full():
            try:
                self._results.get_nowait()
                self._results.task_done()
                self.dropped_results += 1
            except Empty:
                pass
        self._results.put_nowait(packet)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.1)
            except Empty:
                continue
            started = time.perf_counter()
            tracks: list[TrackData] = []
            error = None
            try:
                tracks = self.detector.detect_and_track(
                    job.detector_frame,
                    job.condition.condition,
                    job.confidence_threshold,
                )
            except Exception as exc:  # pragma: no cover - exercised by integration failure path
                error = f"{type(exc).__name__}: {exc}"
                logger.error("[HybridTracker] Detector keyframe failed: %s", error)
            runtime = getattr(self.detector, "_runtime", None)
            logger.info(
                "[Detector Trace] frame=%d shape=%sx%s condition=%s threshold=%.3f "
                "input=%s candidates=%d threshold_pass=%d nms=%d raw=%d tracks=%d "
                "tracker_output=%d error=%s",
                job.frame_index,
                job.detector_frame.shape[1] if getattr(job.detector_frame, "shape", None) else "?",
                job.detector_frame.shape[0] if getattr(job.detector_frame, "shape", None) else "?",
                job.condition.condition,
                job.confidence_threshold,
                getattr(runtime, "last_input_shape", None),
                getattr(runtime, "last_candidate_count", 0),
                getattr(runtime, "last_threshold_count", 0),
                getattr(runtime, "last_nms_count", 0),
                len(getattr(self.detector, "last_raw_detections", [])),
                len(tracks),
                getattr(self.detector, "last_tracker_output_count", 0),
                error or "none",
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            runtime_timings = getattr(getattr(self.detector, "_runtime", None), "last_stage_ms", {})
            tracker_ms = float(getattr(self.detector, "last_tracker_ms", 0.0))
            detector_ms = float(runtime_timings.get("total", max(0.0, elapsed_ms - tracker_ms)))
            self._publish(DetectorPacket(
                job=job,
                tracks=tracks,
                raw_detections=list(getattr(self.detector, "last_raw_detections", [])),
                detector_ms=detector_ms,
                tracker_ms=tracker_ms,
                completed_at=time.time(),
                error=error,
            ))
            self.completed += 1
            self._busy.clear()
            self._jobs.task_done()


@dataclass
class _FlowTrack:
    source: TrackData
    bbox: np.ndarray
    points: np.ndarray
    detector_frame_index: int
    missed: int = 0
    frames_since_detector: int = 0


def flow_bbox_is_sane(previous: np.ndarray, candidate: np.ndarray, frame_width: int, frame_height: int) -> bool:
    """Reject collapsed, malformed, implausibly resized, or unsupported boxes."""
    if not np.all(np.isfinite(candidate)):
        return False
    previous_width = float(previous[2] - previous[0])
    previous_height = float(previous[3] - previous[1])
    width = float(candidate[2] - candidate[0])
    height = float(candidate[3] - candidate[1])
    if min(previous_width, previous_height, width, height) < 3.0:
        return False
    width_ratio = width / previous_width
    height_ratio = height / previous_height
    if not (0.65 <= width_ratio <= 1.5 and 0.65 <= height_ratio <= 1.5):
        return False
    previous_aspect = previous_width / previous_height
    aspect = width / height
    if not (0.67 <= aspect / previous_aspect <= 1.5):
        return False
    previous_center = (previous[:2] + previous[2:]) * 0.5
    center = (candidate[:2] + candidate[2:]) * 0.5
    if np.linalg.norm(center - previous_center) > max(frame_width, frame_height) * 0.18:
        return False
    intersection_width = max(0.0, min(float(candidate[2]), frame_width) - max(float(candidate[0]), 0.0))
    intersection_height = max(0.0, min(float(candidate[3]), frame_height) - max(float(candidate[1]), 0.0))
    visible_fraction = (intersection_width * intersection_height) / max(width * height, 1e-6)
    return visible_fraction >= 0.35


def box_iou(left: np.ndarray, right: np.ndarray) -> float:
    intersection_width = max(0.0, min(float(left[2]), float(right[2])) - max(float(left[0]), float(right[0])))
    intersection_height = max(0.0, min(float(left[3]), float(right[3])) - max(float(left[1]), float(right[1])))
    intersection = intersection_width * intersection_height
    left_area = max(0.0, float(left[2] - left[0])) * max(0.0, float(left[3] - left[1]))
    right_area = max(0.0, float(right[2] - right[0])) * max(0.0, float(right[3] - right[1]))
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def box_center_error(left: np.ndarray, right: np.ndarray) -> float:
    left_center = (left[:2] + left[2:]) * 0.5
    right_center = (right[:2] + right[2:]) * 0.5
    return float(np.linalg.norm(left_center - right_center))


class OpticalFlowBoxTracker:
    """Image-grounded bounding-box propagation on a bounded frame history."""

    def __init__(
        self,
        *,
        max_width: int = 480,
        history_frames: int = 180,
        max_detector_age_frames: int = 24,
        max_missed_frames: int = 2,
        max_points: int = 20,
        flow_win_size: int = 17,
        backward_check_interval: int = 4,
    ):
        self.max_width = max(160, int(max_width))
        self.history = deque(maxlen=max(8, int(history_frames)))
        self.max_detector_age_frames = max(1, int(max_detector_age_frames))
        self.max_missed_frames = max(0, int(max_missed_frames))
        self.max_points = max(4, int(max_points))
        self.flow_win_size = max(9, int(flow_win_size) | 1)
        self.backward_check_interval = max(1, int(backward_check_interval))
        self._tracks: dict[int, _FlowTrack] = {}
        self._frame_tracks: dict[int, list[TrackData]] = {}
        self._previous_gray: Optional[np.ndarray] = None
        self._scale = 1.0
        self.current_frame_index: Optional[int] = None
        self.last_update_ms = 0.0
        self.update_count = 0

    def reset(self) -> None:
        self.history.clear()
        self._tracks.clear()
        self._frame_tracks.clear()
        self._previous_gray = None
        self.current_frame_index = None

    def _gray(self, frame: np.ndarray) -> tuple[np.ndarray, float]:
        h, w = frame.shape[:2]
        scale = min(1.0, self.max_width / float(max(1, w)))
        if scale < 1.0:
            frame = cv2.resize(frame, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), scale

    def _seed_points(self, gray: np.ndarray, bbox: np.ndarray) -> np.ndarray:
        h, w = gray.shape[:2]
        x1, y1, x2, y2 = bbox
        x1, x2 = sorted((max(0, int(x1)), min(w - 1, int(x2))))
        y1, y2 = sorted((max(0, int(y1)), min(h - 1, int(y2))))
        if x2 - x1 < 4 or y2 - y1 < 4:
            return np.empty((0, 1, 2), dtype=np.float32)
        mask = np.zeros_like(gray)
        mask[y1:y2 + 1, x1:x2 + 1] = 255
        points = cv2.goodFeaturesToTrack(
            gray,
            mask=mask,
            maxCorners=self.max_points,
            qualityLevel=0.01,
            minDistance=5,
            blockSize=5,
        )
        return points.astype(np.float32) if points is not None else np.empty((0, 1, 2), dtype=np.float32)

    def observe(self, frame: np.ndarray, frame_index: int) -> list[TrackData]:
        started = time.perf_counter()
        gray, scale = self._gray(frame)
        self._scale = scale
        self.history.append((int(frame_index), gray))
        if self._previous_gray is not None and self._tracks:
            self._advance(self._previous_gray, gray, int(frame_index))
        self._previous_gray = gray
        self.current_frame_index = int(frame_index)
        self.last_update_ms = (time.perf_counter() - started) * 1000.0
        self.update_count += 1
        tracks = self.current_tracks()
        self._frame_tracks[int(frame_index)] = tracks
        while len(self._frame_tracks) > self.history.maxlen:
            self._frame_tracks.pop(next(iter(self._frame_tracks)))
        return tracks

    def tracks_at(self, frame_index: int) -> list[TrackData]:
        """Return image-tracker results captured for an exact source frame."""
        return list(self._frame_tracks.get(int(frame_index), []))

    def reanchor(self, tracks: Iterable[TrackData], detector_frame_index: int, detector_frame: np.ndarray) -> list[TrackData]:
        detector_gray, detector_scale = self._gray(detector_frame)
        anchored: dict[int, _FlowTrack] = {}
        for track in tracks:
            bbox = np.array([
                track.bbox.x1 * detector_scale,
                track.bbox.y1 * detector_scale,
                track.bbox.x2 * detector_scale,
                track.bbox.y2 * detector_scale,
            ], dtype=np.float32)
            points = self._seed_points(detector_gray, bbox)
            anchored[int(track.track_id)] = _FlowTrack(
                source=track, bbox=bbox, points=points,
                detector_frame_index=int(detector_frame_index),
            )
        self._tracks = anchored
        previous = detector_gray
        for history_index, history_gray in self.history:
            if history_index <= int(detector_frame_index):
                continue
            self._advance(previous, history_gray, int(history_index))
            previous = history_gray
        self._previous_gray = previous
        return self.current_tracks()

    def _advance(self, previous: np.ndarray, current: np.ndarray, frame_index: int) -> None:
        next_tracks: dict[int, _FlowTrack] = {}
        h, w = current.shape[:2]
        for track_id, state in self._tracks.items():
            state.frames_since_detector = max(0, int(frame_index) - state.detector_frame_index)
            if state.frames_since_detector > self.max_detector_age_frames or len(state.points) < 2:
                continue
            win_size = (self.flow_win_size, self.flow_win_size)
            criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 12, 0.03)
            nxt, status, _ = cv2.calcOpticalFlowPyrLK(
                previous,
                current,
                state.points,
                None,
                winSize=win_size,
                maxLevel=2,
                criteria=criteria,
            )
            if nxt is None or status is None:
                state.missed += 1
                if state.missed <= self.max_missed_frames:
                    next_tracks[track_id] = state
                continue
            valid = status.reshape(-1).astype(bool)
            # Forward flow is sufficient for the intermediate image-grounded
            # sample path.  Keep the more expensive backward consistency check
            # at a bounded cadence so it still rejects drift/ghost boxes while
            # leaving enough CPU for a genuinely high-cadence visible HUD.
            if state.frames_since_detector % self.backward_check_interval == 0:
                back, back_status, _ = cv2.calcOpticalFlowPyrLK(
                    current, previous, nxt, None, winSize=win_size, maxLevel=2,
                )
                if back is not None and back_status is not None:
                    fb = np.linalg.norm(state.points.reshape(-1, 2) - back.reshape(-1, 2), axis=1)
                    valid &= back_status.reshape(-1).astype(bool) & (fb < 1.5)
            old_points = state.points.reshape(-1, 2)[valid]
            new_points = nxt.reshape(-1, 2)[valid]
            if len(new_points) < 2:
                state.missed += 1
                if state.missed <= self.max_missed_frames:
                    next_tracks[track_id] = state
                continue
            displacement_vectors = new_points - old_points
            displacement = np.median(displacement_vectors, axis=0)
            if not np.all(np.isfinite(displacement)):
                continue
            residuals = np.linalg.norm(displacement_vectors - displacement, axis=1)
            if float(np.median(residuals)) > max(2.0, min(
                float(state.bbox[2] - state.bbox[0]),
                float(state.bbox[3] - state.bbox[1]),
            ) * 0.12):
                continue
            candidate = state.bbox.copy()
            candidate[[0, 2]] += displacement[0]
            candidate[[1, 3]] += displacement[1]
            if not flow_bbox_is_sane(state.bbox, candidate, w, h):
                continue
            state.bbox = candidate
            state.points = new_points.reshape(-1, 1, 2).astype(np.float32)
            state.missed = 0
            if state.frames_since_detector % 6 == 0:
                refreshed = self._seed_points(current, state.bbox)
                if len(refreshed) >= 2:
                    state.points = refreshed
            next_tracks[track_id] = state
        self._tracks = next_tracks

    def current_tracks(self) -> list[TrackData]:
        scale = max(self._scale, 1e-9)
        output = []
        for track_id in sorted(self._tracks):
            state = self._tracks[track_id]
            x1, y1, x2, y2 = (float(value / scale) for value in state.bbox)
            bbox = BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2)
            trajectory = list(state.source.trajectory)
            trajectory.append(bbox.centroid)
            output.append(state.source.model_copy(update={
                "bbox": bbox,
                "trajectory": trajectory[-50:],
                "tracker_state": "IMAGE_TRACKER_UPDATED",
                "matched_current_frame": True,
                "detector_confirmed": state.frames_since_detector == 0,
                "confidence_semantics": (
                    "DETECTOR_CURRENT_FRAME" if state.frames_since_detector == 0
                    else "LAST_DETECTION_CONFIDENCE"
                ),
                "last_detection_confidence": float(state.source.confidence),
            }))
        return output
