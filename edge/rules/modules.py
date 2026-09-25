"""
NETRAKSH Edge — Task Modules.
Five modules live here: fence, line crossing, behavior, ANPR, face detection.
Each module fires independently on tracked objects in their respective zones.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np

from edge.detection.anpr import EnhancedANPRModule

from shared.constants import (
    ABANDONED_DISAPPEAR_FRAMES,
    ABANDONED_STATIONARY_FRAMES,
    LOITERING_DWELL_SECONDS,
    DetectionClass,
    EventType,
    FenceDirection,
    LineCrossingDirection,
)
from shared.schemas import BoundingBox, Point, TrackData, ZoneSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Geometry utilities
# ---------------------------------------------------------------------------

def point_in_polygon(point: Point, polygon: List[Point]) -> bool:
    """Ray-casting algorithm for point-in-polygon test."""
    x, y = point.x, point.y
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i].x, polygon[i].y
        xj, yj = polygon[j].x, polygon[j].y
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-10) + xi):
            inside = not inside
        j = i
    return inside


def normalize_point(p: Point, frame_width: float, frame_height: float) -> Point:
    """
    Converts a raw-pixel point to the 0-1 normalized space that zone polygons
    in demo/scripts/zones_config.json are authored in.

    This closes a real gap: every zone-matching call below used to compare a
    raw-pixel centroid directly against polygon coordinates with no defined
    unit, matching whatever coincidentally worked for one specific frame size
    and silently breaking for any other. Normalizing here means a zone config
    written once (by eye, or via scripts/define_zone.py against real footage)
    keeps working if the camera's resolution ever changes — the polygon
    doesn't need re-authoring for a different frame size.
    """
    if frame_width <= 0 or frame_height <= 0:
        return p  # can't normalize without real dimensions — compare as-is rather than divide by zero
    return Point(x=p.x / frame_width, y=p.y / frame_height)


def load_zones(zones_config_path: str) -> List[ZoneSchema]:
    """Load zone definitions from JSON config file."""
    try:
        with open(zones_config_path) as f:
            data = json.load(f)
        return [ZoneSchema(**z) for z in data.get("zones", [])]
    except Exception as exc:
        logger.warning(f"Could not load zones config: {exc}")
        return []


# ---------------------------------------------------------------------------
# Virtual Fence Module
# ---------------------------------------------------------------------------

class VirtualFenceModule:
    """
    Detects crossing of configured polygon zones.
    Direction-aware: tracks whether centroid enters from outside or inside.
    """

    def __init__(self, zones: List[ZoneSchema]):
        self._zones = [z for z in zones if z.zone_type == "fence"]
        self._track_zone_state: Dict[int, Dict[str, bool]] = defaultdict(dict)

    def check(self, track: TrackData, frame_width: float = 1.0, frame_height: float = 1.0) -> Optional[dict]:
        """
        Returns a fence-crossing event dict if a crossing is detected, else None.
        frame_width/frame_height are the CURRENT frame's real pixel dimensions
        (e.g. frame.shape[1], frame.shape[0]) — used to normalize the centroid
        into the same 0-1 space the zone polygon is authored in. Default 1.0
        (a no-op divide) if omitted — the caller is then asserting the track's
        own coordinates are already normalized; edge/main.py always passes
        the real frame size in the live pipeline.
        """
        centroid = normalize_point(track.bbox.centroid, frame_width, frame_height)
        for zone in self._zones:
            polygon = zone.polygon.points
            currently_inside = point_in_polygon(centroid, polygon)
            prev_state = self._track_zone_state[track.track_id].get(zone.zone_id, None)
            self._track_zone_state[track.track_id][zone.zone_id] = currently_inside

            if prev_state is None:
                continue  # No history yet

            if not prev_state and currently_inside:
                direction = FenceDirection.OUTSIDE_TO_RESTRICTED
            elif prev_state and not currently_inside:
                direction = FenceDirection.RESTRICTED_TO_OUTSIDE
            else:
                continue  # No crossing

            return {
                "event_type": EventType.VIRTUAL_FENCE_CROSSING,
                "zone_id": zone.zone_id,
                "direction": direction,
                "track_id": track.track_id,
                "detection_class": track.detection_class,
                "confidence": track.confidence,
            }
        return None

    def get_track_zone(self, track_id: int, zone_id: str) -> bool:
        return self._track_zone_state[track_id].get(zone_id, False)


# ---------------------------------------------------------------------------
# Line Crossing Module (architecture v4 §5)
# ---------------------------------------------------------------------------

class LineCrossingModule:
    """
    Detects a tracked object's centroid crossing a configured line segment.
    A line is a degenerate 2-point polygon with directional crossing logic —
    this reuses the same geometric style as VirtualFenceModule, just without
    an "inside" concept (a line has two sides, not an interior/exterior).

    Zones with zone_type == "boundary" and exactly 2 polygon points are
    treated as crossing lines. Direction is reported relative to the order
    of the two configured points — see shared.constants.LineCrossingDirection
    for the exact convention.
    """

    def __init__(self, zones: List[ZoneSchema]):
        self._lines = [
            z for z in zones
            if z.zone_type == "boundary" and len(z.polygon.points) == 2
        ]
        # track_id -> {zone_id: last_side} where side is +1, -1 (0/on-the-line is never stored)
        self._track_side_state: Dict[int, Dict[str, int]] = defaultdict(dict)

    @staticmethod
    def _side(a: Point, b: Point, p: Point) -> int:
        """Sign of the cross product (B-A) x (P-A): +1, -1, or 0 (exactly on the line)."""
        cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
        if cross > 0:
            return 1
        if cross < 0:
            return -1
        return 0

    def check(self, track: TrackData, frame_width: float = 1.0, frame_height: float = 1.0) -> Optional[dict]:
        """
        Returns a line-crossing event dict if a crossing is detected, else None.
        A point falling exactly on the line (side == 0) is skipped entirely —
        neither recorded as a side nor treated as a crossing — since it's
        genuinely ambiguous which side it's on; the next frame resolves it.
        frame_width/frame_height normalize the centroid into the same 0-1
        space the line's endpoints are authored in — see normalize_point().
        Default 1.0/1.0 (a no-op) if omitted; edge/main.py always passes the
        real frame size.
        """
        centroid = normalize_point(track.bbox.centroid, frame_width, frame_height)
        for line in self._lines:
            a, b = line.polygon.points[0], line.polygon.points[1]
            side = self._side(a, b, centroid)
            if side == 0:
                continue

            prev_side = self._track_side_state[track.track_id].get(line.zone_id)
            self._track_side_state[track.track_id][line.zone_id] = side

            if prev_side is None or prev_side == side:
                continue  # no history yet, or still on the same side — no crossing

            direction = LineCrossingDirection.A_TO_B if prev_side == 1 else LineCrossingDirection.B_TO_A

            # Wrong-way detection (SIH PS 26187's "suspicious activity
            # detection"): a real, configured restricted_direction on this
            # zone (see ZoneSchema) turns a crossing in that specific
            # direction into WRONG_DIRECTION instead of an ordinary
            # LINE_CROSSING. EventType.WRONG_DIRECTION previously existed
            # only as a defined-but-unused enum value (shared/constants.py)
            # and a literal in scripts/seed_demo_events.py's mock data —
            # no real module ever produced it before this.
            # .value, not str() -- direction is a real (str, Enum) member, and
            # str(Enum member) returns "LineCrossingDirection.A_TO_B", not the
            # plain "A_TO_B" value ZoneSchema.restricted_direction actually
            # holds (ZoneSchema's Config.use_enum_values=True stores the bare
            # string). A real bug caught by this feature's own tests, not
            # theoretical -- str()-comparing these two never matched.
            is_wrong_way = (
                line.restricted_direction is not None
                and direction.value == line.restricted_direction
            )
            event_type = EventType.WRONG_DIRECTION if is_wrong_way else EventType.LINE_CROSSING

            return {
                "event_type": event_type,
                "zone_id": line.zone_id,
                "direction": direction,
                "track_id": track.track_id,
                "detection_class": track.detection_class,
                "confidence": track.confidence,
            }
        return None

    def get_track_side(self, track_id: int, zone_id: str) -> Optional[int]:
        return self._track_side_state[track_id].get(zone_id)


# ---------------------------------------------------------------------------
# Behavior Module (loitering + abandoned object)
# ---------------------------------------------------------------------------

class BehaviorModule:
    """
    Rule-based behavior detection.
    Rules:
      1. Loitering: dwell time in zone exceeds LOITERING_DWELL_SECONDS
      2. Abandoned object: object is stationary then track disappears
    """

    def __init__(self, zones: List[ZoneSchema], dwell_threshold_seconds: float = LOITERING_DWELL_SECONDS):
        self._all_zones = zones
        self._dwell_threshold = dwell_threshold_seconds
        # track_id → {zone_id: entry_time}
        self._entry_times: Dict[int, Dict[str, float]] = defaultdict(dict)
        # track_id → {frame_count_stationary, last_bbox}
        self._static_tracks: Dict[int, dict] = {}
        self._disappeared_tracks: Dict[int, dict] = {}
        self._fired_loitering: set = set()

    def update(self, active_tracks: List[TrackData], frame_width: float = 1.0, frame_height: float = 1.0) -> List[dict]:
        """
        frame_width/frame_height are the current frame's real pixel dimensions,
        used ONLY to normalize the centroid for zone-membership tests below —
        the separate stationary-object motion check further down deliberately
        keeps comparing raw pixel displacement (dx/dy against a fixed 5px
        threshold), since that threshold's meaning is about physical movement
        magnitude, not position within a zone, and must not be normalized.
        """
        events = []
        active_ids = {t.track_id for t in active_tracks}
        now = time.time()

        for track in active_tracks:
            centroid = normalize_point(track.bbox.centroid, frame_width, frame_height)

            # --- Loitering ---
            for zone in self._all_zones:
                if point_in_polygon(centroid, zone.polygon.points):
                    if zone.zone_id not in self._entry_times[track.track_id]:
                        self._entry_times[track.track_id][zone.zone_id] = now
                    dwell = now - self._entry_times[track.track_id][zone.zone_id]
                    key = (track.track_id, zone.zone_id)
                    if dwell >= self._dwell_threshold and key not in self._fired_loitering:
                        self._fired_loitering.add(key)
                        events.append({
                            "event_type": EventType.LOITERING,
                            "zone_id": zone.zone_id,
                            "track_id": track.track_id,
                            "detection_class": track.detection_class,
                            "confidence": track.confidence,
                            "rule": "dwell_time_exceeded",
                            "rule_value": round(dwell, 1),
                        })
                else:
                    self._entry_times[track.track_id].pop(zone.zone_id, None)
                    self._fired_loitering.discard((track.track_id, zone.zone_id))

            # --- Stationary object tracking (for abandoned object) ---
            if track.track_id in self._static_tracks:
                prev = self._static_tracks[track.track_id]
                dx = abs(track.bbox.centroid.x - prev["last_cx"])
                dy = abs(track.bbox.centroid.y - prev["last_cy"])
                if dx < 5.0 and dy < 5.0:
                    prev["stationary_frames"] += 1
                else:
                    prev["stationary_frames"] = 0
                    prev["last_cx"] = track.bbox.centroid.x
                    prev["last_cy"] = track.bbox.centroid.y
            else:
                self._static_tracks[track.track_id] = {
                    "stationary_frames": 0,
                    "last_cx": track.bbox.centroid.x,
                    "last_cy": track.bbox.centroid.y,
                    "bbox": track.bbox,
                    "zone_id": self._get_zone_for_track(track, frame_width, frame_height),
                    "class": track.detection_class,
                    "confidence": track.confidence,
                }

        # --- Abandoned object: was stationary, then genuinely left behind ---
        # A real gap, fixed here: candidates used to fire the instant a
        # stationary track disappeared for even a single frame -- no
        # tolerance for a brief detection/tracking miss, exactly the kind of
        # single-frame noise ByteTrack's own track_buffer already tolerates
        # elsewhere. `ABANDONED_DISAPPEAR_FRAMES` and `self._disappeared_tracks`
        # both already existed for this purpose but were never wired together.
        # A candidate now has to stay missing for ABANDONED_DISAPPEAR_FRAMES
        # consecutive updates before it's reported; if tracking recovers it
        # before then, the pending candidate is cancelled, not fired.
        reappeared = set(self._disappeared_tracks) & active_ids
        for reappeared_id in reappeared:
            del self._disappeared_tracks[reappeared_id]

        newly_gone = set(self._static_tracks.keys()) - active_ids
        for gone_id in newly_gone:
            stat = self._static_tracks.pop(gone_id, None)
            if stat and stat.get("stationary_frames", 0) >= ABANDONED_STATIONARY_FRAMES:
                self._disappeared_tracks[gone_id] = {**stat, "missing_frames": 0}

        fired = []
        for pending_id, stat in self._disappeared_tracks.items():
            stat["missing_frames"] += 1
            if stat["missing_frames"] >= ABANDONED_DISAPPEAR_FRAMES:
                events.append({
                    "event_type": EventType.ABANDONED_OBJECT,
                    "zone_id": stat.get("zone_id", "unknown"),
                    "track_id": pending_id,
                    "detection_class": stat.get("class"),
                    "confidence": stat.get("confidence", 0.0),
                    "rule": "stationary_object_timeout",
                    "rule_value": stat.get("stationary_frames", 0),
                })
                fired.append(pending_id)
        for pending_id in fired:
            del self._disappeared_tracks[pending_id]

        return events

    def _get_zone_for_track(self, track: TrackData, frame_width: float, frame_height: float) -> str:
        centroid = normalize_point(track.bbox.centroid, frame_width, frame_height)
        for zone in self._all_zones:
            if point_in_polygon(centroid, zone.polygon.points):
                return zone.zone_id
        return "no_zone"


# ---------------------------------------------------------------------------
# ANPR Module (checkpoint-style cameras only)
# ---------------------------------------------------------------------------

class ANPRModule:
    """
    Automatic Number Plate Recognition.
    Architecture §14: scoped explicitly to checkpoint-angle cameras.
    Pipeline: vehicle track in checkpoint zone → plate crop → EasyOCR.

    Note: A proper plate detector (YOLO-based) would precede OCR for production.
    For MVP, we use a simplified crop based on the vehicle bbox (lower-middle region)
    and run EasyOCR on it. This is explicitly noted in docs/LIMITATIONS.md.
    """

    def __init__(self, zones: List[ZoneSchema], languages: List[str] = None):
        self._checkpoint_zones = [z for z in zones if z.zone_type == "checkpoint"]
        self._languages = languages or ["en"]
        self._reader = None
        
        # The enhanced YuNet + temporal-fusion path is authoritative.  The
        # legacy heuristic remains available only as an explicit compatibility
        # mode for old fixtures.
        self._pipeline = os.environ.get("ANPR_PIPELINE", "enhanced").lower()
        self._frame_interval = max(1, int(os.environ.get("ANPR_FRAME_INTERVAL", "5")))
        self._track_calls = {}
        if self._pipeline == "enhanced":
            self._enhanced_module = EnhancedANPRModule()


    def _load_reader(self):
        if self._reader is None:
            try:
                import easyocr
                self._reader = easyocr.Reader(self._languages, gpu=False, verbose=False)
                logger.info("[ANPR] EasyOCR reader initialized")
            except Exception as exc:
                logger.error(f"[ANPR] EasyOCR init failed: {exc}")

    def process(
        self,
        track: TrackData,
        frame: np.ndarray,
    ) -> Optional[dict]:
        """
        Returns ANPR result dict if this track is a vehicle in a checkpoint zone, else None.
        """
        if track.detection_class != DetectionClass.VEHICLE:
            return None

        # OCR is gated per camera-local vehicle track.  The first observation
        # is immediate; subsequent reads are sampled at a configurable cadence
        # so EasyOCR does not run on every video frame.
        calls = self._track_calls.get(track.track_id, 0) + 1
        self._track_calls[track.track_id] = calls
        if calls > 1 and calls % self._frame_interval != 0:
            return None

        fh, fw = frame.shape[:2]
        centroid = normalize_point(track.bbox.centroid, fw, fh)
        in_checkpoint = any(
            point_in_polygon(centroid, z.polygon.points)
            for z in self._checkpoint_zones
        )
        if not in_checkpoint:
            return None

        # Get zone_id for the first matching zone
        zone_id = next(
            (z.zone_id for z in self._checkpoint_zones
             if point_in_polygon(centroid, z.polygon.points)),
            "unknown"
        )

        if self._pipeline == "enhanced":
            res = self._enhanced_module.process(track, frame)
            # If no read or unstable, return None to avoid polluting the pipeline with bad events.
            if not res or res.get("fusion_state") == "NO_VALID_READ" or not res.get("plate_text"):
                return None
            return {
                "event_type": EventType.ANPR_READ,
                "zone_id": zone_id,
                "track_id": track.track_id,
                "detection_class": DetectionClass.VEHICLE,
                "confidence": track.confidence,
                "plate_text": res.get("plate_text"),
                "plate_confidence": res.get("plate_confidence"),
                "raw_plate_text": res.get("raw_plate_text"),
                "normalized_plate_text": res.get("normalized_plate_text"),
                "localization_confidence": res.get("localization_confidence"),
                "ocr_confidence": res.get("ocr_confidence"),
                "observations_count": res.get("observations_count"),
                "processing_method": res.get("processing_method"),
                "fusion_state": res.get("fusion_state"),
                "validation_status": res.get("validation_status"),
                "watchlist_match": res.get("watchlist_match"),
            }

        # Legacy ANPR path below:
        # Crop: lower-middle third of vehicle bbox (typical plate location)
        x1, y1, x2, y2 = int(track.bbox.x1), int(track.bbox.y1), int(track.bbox.x2), int(track.bbox.y2)
        h = y2 - y1
        w = x2 - x1
        plate_y1 = y1 + int(h * 0.55)
        plate_y2 = y2
        plate_x1 = x1 + int(w * 0.1)
        plate_x2 = x2 - int(w * 0.1)

        # Bounds check (fh, fw already computed above for centroid normalization)
        plate_y1 = max(0, plate_y1)
        plate_y2 = min(fh, plate_y2)
        plate_x1 = max(0, plate_x1)
        plate_x2 = min(fw, plate_x2)

        if plate_y2 <= plate_y1 or plate_x2 <= plate_x1:
            return None

        crop = frame[plate_y1:plate_y2, plate_x1:plate_x2]
        self._load_reader()
        if self._reader is None:
            return None

        try:
            import cv2
            # Enhance crop for OCR
            gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            _, thresh_crop = cv2.threshold(gray_crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            results = self._reader.readtext(thresh_crop, detail=1, paragraph=False)

            if not results:
                return None

            # Take best result by confidence
            best = max(results, key=lambda r: r[2])
            text = best[1].strip().upper()
            conf = float(best[2])

            logger.info(f"[ANPR] Track {track.track_id}: plate='{text}', confidence={conf:.2f}")
            return {
                "event_type": EventType.ANPR_READ,
                "zone_id": zone_id,
                "track_id": track.track_id,
                "detection_class": DetectionClass.VEHICLE,
                "confidence": track.confidence,
                "plate_text": text,
                "plate_confidence": conf,
            }
        except Exception as exc:
            logger.debug(f"[ANPR] OCR failed for track {track.track_id}: {exc}")
            return None


# ---------------------------------------------------------------------------
# Face Detection Module (+ real watchlist recognition — see
# edge/detection/face_recognition.py's module docstring for the full
# honest scope)
# ---------------------------------------------------------------------------

class FaceDetectionModule:
    """
    Face detection for person tracks in verification zones.
    Uses OpenCV Haar cascade as primary detector (fast, CPU-friendly).
    RetinaFace used if retina-face package is available (better accuracy).

    Real watchlist recognition (SIH PS 26187 — "support facial
    recognition", not detection alone): if a `recognizer` is supplied
    (edge/detection/face_recognition.py's WatchlistFaceRecognizer,
    typically built via sync_from_backend() in edge/main.py), every
    detected face is also run through it — a real match adds
    face_match_person_id/face_match_person_name/face_match_confidence to
    the returned event dict; no match leaves them absent (never
    fabricated). Detection-only behavior (recognizer=None, the previous
    default) is completely unchanged.
    """

    def __init__(self, zones: List[ZoneSchema], recognizer=None):
        self._verification_zones = [z for z in zones if z.zone_type == "verification"]
        self._face_cascade = None
        self._retinaface_available = False
        
        # Phase 3 Step 2: Recognition Engine Selection
        self._engine_type = os.environ.get("FACE_RECOGNITION_ENGINE", "lbph").lower()
        self._recognizer = recognizer  # Optional[WatchlistFaceRecognizer] for LBPH
        
        self._embedding_engine = None
        self._embedding_watchlist = None
        self._temporal_fusion = None
        self._face_aligner = None
        self._embedding_unavailable_reason = None
        
        if self._engine_type == "embedding":
            from edge.detection.face_align import FaceAligner
            from edge.detection.face_embedding import ONNXFaceEmbeddingEngine
            from edge.detection.face_watchlist import EmbeddingWatchlistIndex
            from edge.detection.face_fusion import TemporalFaceFusion
            
            self._face_aligner = FaceAligner()
            self._embedding_watchlist = EmbeddingWatchlistIndex()
            self._temporal_fusion = TemporalFaceFusion()
            
            model_path = os.environ.get("FACE_EMBEDDING_MODEL_PATH", "")
            try:
                self._embedding_engine = ONNXFaceEmbeddingEngine(model_path)
            except Exception as e:
                self._embedding_unavailable_reason = str(e)
                logger.error(f"[Face] Embedding engine unavailable: {e}")

        self._load_detectors()

    def _load_detectors(self):
        import cv2
        import os
        from pathlib import Path

        bundled_path = Path(__file__).resolve().parent.parent / "detection" / "cascades" / "haarcascade_frontalface_default.xml"
        
        self._face_cascade = None
        if os.path.exists(bundled_path):
            cascade = cv2.CascadeClassifier(str(bundled_path))
            if not cascade.empty():
                self._face_cascade = cascade
                logger.info(f"[Face] FACE DETECTOR READY (Haar cascade loaded from {bundled_path})")
            else:
                logger.error(f"[Face] FACE DETECTOR UNAVAILABLE (Haar cascade file exists but failed to load)")
                self._face_cascade = cv2.CascadeClassifier()
        else:
            logger.error(f"[Face] FACE DETECTOR UNAVAILABLE (Haar cascade file missing at {bundled_path})")
            self._face_cascade = cv2.CascadeClassifier()

        try:
            import retina_face
            self._retinaface_available = True
            logger.info("[Face] RetinaFace available — will use for verification zones")
        except ImportError:
            logger.info("[Face] RetinaFace not available — using Haar cascade fallback (SIH Demo path)")

    def detect(
        self,
        track: TrackData,
        frame: np.ndarray,
    ) -> Optional[dict]:
        """
        Returns face detection result if person track is in verification zone.
        """
        if track.detection_class != DetectionClass.PERSON:
            return None

        fh, fw = frame.shape[:2]
        centroid = normalize_point(track.bbox.centroid, fw, fh)
        in_verification = any(
            point_in_polygon(centroid, z.polygon.points)
            for z in self._verification_zones
        )
        if not in_verification:
            return None

        zone_id = next(
            (z.zone_id for z in self._verification_zones
             if point_in_polygon(centroid, z.polygon.points)),
            "unknown"
        )

        # Crop person region
        x1 = max(0, int(track.bbox.x1))
        y1 = max(0, int(track.bbox.y1))
        x2 = min(frame.shape[1], int(track.bbox.x2))
        y2 = min(frame.shape[0], int(track.bbox.y2))
        person_crop = frame[y1:y2, x1:x2]

        if person_crop.size == 0:
            return None

        if self._retinaface_available:
            result = self._detect_retinaface(track, person_crop, zone_id)
        else:
            result = self._detect_haar(track, person_crop, zone_id)

        if result is not None:
            # A detected face is always surfaced with an explicit recognition
            # state.  UNKNOWN means evaluation completed without a watchlist
            # hit; INSUFFICIENT_QUALITY means the crop could not be evaluated.
            result.setdefault("face_match_status", "UNKNOWN")
            result.setdefault("recognition_engine", self._engine_type)
            result.setdefault("recognition_observation_count", 1)
            if self._engine_type == "embedding":
                self._attempt_embedding_recognition(result, person_crop)
            else:
                self._attempt_lbph_recognition(result, person_crop)
        return result

    def _attempt_lbph_recognition(self, result: dict, person_crop: np.ndarray) -> None:
        """
        Mutates `result` in place, adding face_match_* keys on a real
        match. No-op (result unchanged) if no recognizer was supplied, the
        recognizer hasn't been trained yet (e.g. watchlist sync hasn't
        completed), or the real face_bbox this detection produced can't be
        cropped from person_crop for any reason.
        """
        result.setdefault("recognition_engine", "lbph")
        result.setdefault("recognition_threshold", float(os.environ.get("FACE_RECOGNITION_THRESHOLD", "60.0")))
        if self._recognizer is None or not self._recognizer.is_trained():
            result["face_match_status"] = "NOT_EVALUATED"
            return
        face_bbox = result.get("face_bbox")
        if face_bbox is None:
            return
        fx1, fy1 = max(0, int(face_bbox.x1)), max(0, int(face_bbox.y1))
        fx2 = min(person_crop.shape[1], int(face_bbox.x2))
        fy2 = min(person_crop.shape[0], int(face_bbox.y2))
        if fx2 <= fx1 or fy2 <= fy1:
            result["face_match_status"] = "INSUFFICIENT_QUALITY"
            result["face_quality_status"] = "INVALID_CROP"
            return
        face_crop = person_crop[fy1:fy2, fx1:fx2]
        if face_crop.size == 0 or face_crop.shape[0] < 20 or face_crop.shape[1] < 20:
            result["face_match_status"] = "INSUFFICIENT_QUALITY"
            result["face_quality_status"] = "TOO_SMALL"
            return
        try:
            match = self._recognizer.recognize(face_crop)
        except Exception as exc:
            logger.debug(f"[Face] Watchlist recognition error: {exc}")
            result["face_match_status"] = "UNKNOWN"
            return
        if match is None:
            result["face_match_status"] = "UNKNOWN"
            return
        result["face_match_person_id"] = match["person_id"]
        result["face_match_person_name"] = match["name"]
        result["face_match_confidence"] = match["confidence"]
        result["face_engine"] = "lbph"
        result["recognition_engine"] = "lbph"
        result["recognition_score"] = match.get("confidence")
        result["recognition_threshold"] = match.get("threshold", result.get("recognition_threshold"))
        result["watchlist_person_id"] = match["person_id"]
        result["watchlist_label"] = match["name"]
        result["face_match_status"] = "KNOWN"
        result["recognition_state"] = "MATCH"
        logger.info(
            f"[Face] Watchlist match: track {result.get('track_id')} -> "
            f"{match['name']} (confidence={match['confidence']:.1f}, lower=stronger)"
        )

    def _attempt_embedding_recognition(self, result: dict, person_crop: np.ndarray) -> None:
        result["face_engine"] = "embedding"
        result["recognition_engine"] = "embedding"
        
        if self._embedding_engine is None:
            result["recognition_state"] = "EMBEDDING_ENGINE_UNAVAILABLE"
            result["face_match_status"] = "NOT_EVALUATED"
            return
            
        face_bbox = result.get("face_bbox")
        if face_bbox is None:
            result["recognition_state"] = "ERROR"
            result["face_match_status"] = "INSUFFICIENT_QUALITY"
            return
            
        # 1. Align face
        align_res = self._face_aligner.align(person_crop, face_bbox, result.get("landmarks"))
        result["alignment_method"] = align_res.get("alignment_method", "UNKNOWN")
        if not align_res.get("success"):
            result["recognition_state"] = "ALIGNMENT_FAILED"
            result["face_match_status"] = "INSUFFICIENT_QUALITY"
            return
            
        aligned_face = align_res["aligned_face"]
        
        # 2. Embed face
        embedding = self._embedding_engine.embed(aligned_face)
        if embedding is None:
            result["recognition_state"] = "EMBEDDING_FAILED"
            result["face_match_status"] = "INSUFFICIENT_QUALITY"
            return
            
        # 3. Search Watchlist
        search_res = self._embedding_watchlist.search(embedding)
        state = search_res.get("state", "ERROR")
        person_id = search_res.get("person_id")
        score = search_res.get("similarity")
        
        # 4. Temporal Fusion
        track_id = result.get("track_id")
        fusion_res = self._temporal_fusion.add_observation(track_id, person_id, state, score)
        
        result["recognition_state"] = fusion_res.get("fusion_state", "UNKNOWN")
        if fusion_res.get("person_id"):
            result["face_match_person_id"] = fusion_res["person_id"]
            result["face_match_person_name"] = search_res.get("name") # From current search
            result["watchlist_person_id"] = fusion_res["person_id"]
            result["watchlist_label"] = search_res.get("name")
            result["face_match_status"] = "KNOWN"
        else:
            result["face_match_status"] = "UNKNOWN"
            
        if fusion_res.get("confidence") is not None:
            result["similarity_score"] = float(fusion_res["confidence"])

    def _detect_retinaface(self, track: TrackData, crop: np.ndarray, zone_id: str) -> Optional[dict]:
        try:
            from retina_face import RetinaFace
            faces = RetinaFace.detect_faces(crop)
            if not faces or not isinstance(faces, dict):
                return None
            # Take highest confidence face
            best_face = max(faces.values(), key=lambda f: f.get("score", 0))
            face_conf = float(best_face.get("score", 0.0))
            facial_area = best_face.get("facial_area", [0, 0, 0, 0])
            face_bbox = BoundingBox(x1=facial_area[0], y1=facial_area[1],
                                    x2=facial_area[2], y2=facial_area[3])
                                    
            landmarks = best_face.get("landmarks", {})
            lm_array = None
            if landmarks:
                # Typically keys are right_eye, left_eye, nose, mouth_right, mouth_left
                # Format to 5x2 array [left_eye, right_eye, nose, mouth_left, mouth_right]
                lm_array = np.array([
                    landmarks.get("left_eye", [0, 0]),
                    landmarks.get("right_eye", [0, 0]),
                    landmarks.get("nose", [0, 0]),
                    landmarks.get("mouth_left", [0, 0]),
                    landmarks.get("mouth_right", [0, 0])
                ], dtype=np.float32)

            return {
                "event_type": EventType.FACE_DETECTED,
                "zone_id": zone_id,
                "track_id": track.track_id,
                "detection_class": DetectionClass.FACE,
                "confidence": track.confidence,
                "face_confidence": face_conf,
                "face_bbox": face_bbox,
                "detector": "retinaface",
                "landmarks": lm_array,
            }
        except Exception as exc:
            logger.debug(f"[Face] RetinaFace error: {exc}")
            return None

    def _detect_haar(self, track: TrackData, crop: np.ndarray, zone_id: str) -> Optional[dict]:
        import cv2
        if self._face_cascade is None or self._face_cascade.empty():
            # Real, environment-specific gap (see docs/LIMITATIONS.md): some
            # OpenCV builds (e.g. opencv-contrib-python-headless, installed
            # in this project for cv2.face/LBPH watchlist recognition) do
            # not ship the bundled Haar cascade XML data files that
            # opencv-python does, so cv2.CascadeClassifier(...) silently
            # constructs an empty, unusable classifier -- _load_detectors()
            # already logs this at startup. Calling detectMultiScale() on an
            # empty classifier raises cv2.error (a real, previously
            # uncaught crash that took down the entire real-time frame
            # loop on the first person track inside a verification zone,
            # confirmed against demo/videos/vtest.avi). Skip face
            # detection for this frame rather than crash -- same posture
            # as every other optional/best-effort real-time dependency in
            # this codebase (psutil, RetinaFace, backend connectivity).
            return None
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(20, 20))
        if len(faces) == 0:
            return None
        # Use largest face
        largest = max(faces, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = largest
        face_bbox = BoundingBox(x1=float(fx), y1=float(fy), x2=float(fx + fw), y2=float(fy + fh))
        return {
            "event_type": EventType.FACE_DETECTED,
            "zone_id": zone_id,
            "track_id": track.track_id,
            "detection_class": DetectionClass.FACE,
            "confidence": track.confidence,
            "face_confidence": 0.7,  # Haar doesn't output probability
            "face_bbox": face_bbox,
            "detector": "haar_cascade",
        }
