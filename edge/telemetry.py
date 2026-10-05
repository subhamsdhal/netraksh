"""Authoritative, immutable current-frame telemetry snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

VEHICLE_CLASS_NAMES = frozenset({"car", "motorcycle", "bus", "truck"})


def _detection_class(track) -> str:
    value = getattr(track, "detection_class", "unknown")
    return str(getattr(value, "value", value)).lower()


def _class_name(track) -> str:
    detection_class = _detection_class(track)
    if detection_class == "person":
        return "person"
    subtype = getattr(track, "vehicle_subtype", None)
    subtype = str(getattr(subtype, "value", subtype or "")).lower()
    return subtype if subtype in VEHICLE_CLASS_NAMES else detection_class


@dataclass(frozen=True)
class SnapshotObject:
    track_id: int
    class_id: Optional[int]
    class_name: str
    detection_class: str
    confidence: float
    bbox: Tuple[float, float, float, float]
    tracker_state: str = "TRACKED_CURRENT_FRAME"
    matched_current_frame: bool = True
    detector_confirmed: bool = True
    confidence_semantics: str = "DETECTOR_CURRENT_FRAME"
    last_detection_confidence: Optional[float] = None

    def to_live_track(self, frame_width: int, frame_height: int) -> dict:
        x1, y1, x2, y2 = self.bbox
        return {
            "track_id": self.track_id,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "detection_class": self.detection_class,
            "tracker_state": self.tracker_state,
            "matched_current_frame": self.matched_current_frame,
            "confidence": self.confidence,
            "detector_confirmed": self.detector_confirmed,
            "confidence_semantics": self.confidence_semantics,
            "last_detection_confidence": self.last_detection_confidence,
            "bbox_x": x1 / frame_width if frame_width else 0.0,
            "bbox_y": y1 / frame_height if frame_height else 0.0,
            "bbox_w": (x2 - x1) / frame_width if frame_width else 0.0,
            "bbox_h": (y2 - y1) / frame_height if frame_height else 0.0,
        }


@dataclass(frozen=True)
class FrameSnapshot:
    camera_id: str
    analysis_session_id: str
    frame_index: int
    source_timestamp: float
    processed_at: float
    source_video_time: float
    frame_width: int
    frame_height: int
    objects: Tuple[SnapshotObject, ...]
    tracker_output_ids: Tuple[int, ...]

    @property
    def person_count(self) -> int:
        return sum(obj.class_name == "person" for obj in self.objects)

    @property
    def vehicle_count(self) -> int:
        return sum(obj.class_name in VEHICLE_CLASS_NAMES for obj in self.objects)

    @property
    def track_count(self) -> int:
        return len({obj.track_id for obj in self.objects})

    @property
    def active_track_ids(self) -> list[int]:
        return [obj.track_id for obj in self.objects]

    def live_tracks(self) -> list[dict]:
        return [obj.to_live_track(self.frame_width, self.frame_height) for obj in self.objects]


def build_frame_snapshot(
    *, camera_id: str, analysis_session_id: str, frame_index: int,
    source_timestamp: float, processed_at: float, source_video_time: float,
    tracks: Iterable, frame_width: int, frame_height: int,
) -> FrameSnapshot:
    """Freeze only objects returned by this exact tracker update.

    Ultralytics BYTETracker.update() returns activated ``tracked_stracks``
    after unmatched tracks have been marked LOST and removed. Its returned
    rows are therefore detection-associated with this update; retention-buffer
    lost/predicted-only objects are not admitted here.
    """
    by_id = {}
    output_ids = []
    for track in tracks:
        if not bool(getattr(track, "matched_current_frame", False)):
            continue
        track_id = int(track.track_id)
        output_ids.append(track_id)
        obj = SnapshotObject(
            track_id=track_id,
            class_id=getattr(track, "source_class_id", None),
            class_name=_class_name(track),
            detection_class=_detection_class(track),
            confidence=float(track.confidence),
            bbox=(float(track.bbox.x1), float(track.bbox.y1), float(track.bbox.x2), float(track.bbox.y2)),
            tracker_state=str(getattr(track, "tracker_state", "TRACKED_CURRENT_FRAME")),
            matched_current_frame=True,
            detector_confirmed=bool(getattr(track, "detector_confirmed", True)),
            confidence_semantics=str(getattr(track, "confidence_semantics", "DETECTOR_CURRENT_FRAME")),
            last_detection_confidence=(
                float(getattr(track, "last_detection_confidence"))
                if getattr(track, "last_detection_confidence", None) is not None
                else float(track.confidence)
            ),
        )
        current = by_id.get(track_id)
        if current is None or obj.confidence > current.confidence:
            by_id[track_id] = obj
    return FrameSnapshot(
        camera_id=camera_id,
        analysis_session_id=analysis_session_id,
        frame_index=int(frame_index),
        source_timestamp=float(source_timestamp),
        processed_at=float(processed_at),
        source_video_time=float(source_video_time),
        frame_width=int(frame_width),
        frame_height=int(frame_height),
        objects=tuple(by_id[key] for key in sorted(by_id)),
        tracker_output_ids=tuple(output_ids),
    )


def render_snapshot(frame, snapshot: FrameSnapshot, hud: bool = True):
    """Draw exactly ``snapshot.objects``; no second object derivation exists."""
    import cv2

    rendered = frame.copy()
    if not hud:
        return rendered
    for obj in snapshot.objects:
        x1, y1, x2, y2 = (int(round(value)) for value in obj.bbox)
        color = (80, 220, 120) if obj.class_name == "person" else (0, 190, 255)
        cv2.rectangle(rendered, (x1, y1), (x2, y2), color, 2)
        label = f"{obj.class_name} #{obj.track_id} {obj.confidence:.2f}"
        cv2.putText(rendered, label, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
    session = snapshot.analysis_session_id[:8]
    cv2.rectangle(rendered, (8, 8), (315, 60), (8, 12, 18), -1)
    cv2.putText(rendered, f"FRAME {snapshot.frame_index}  SESSION {session}", (16, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (230, 240, 245), 1, cv2.LINE_AA)
    cv2.putText(rendered, f"P: {snapshot.person_count}  V: {snapshot.vehicle_count}  T: {snapshot.track_count}", (16, 51), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (80, 220, 120), 2, cv2.LINE_AA)
    return rendered


def build_active_track_snapshot(tracks: Iterable, frame_width: int, frame_height: int) -> dict:
    snapshot = build_frame_snapshot(
        camera_id="test", analysis_session_id="test", frame_index=0,
        source_timestamp=0, processed_at=0, source_video_time=0,
        tracks=tracks, frame_width=frame_width, frame_height=frame_height,
    )
    return {
        "tracks": snapshot.live_tracks(),
        "active_track_ids": snapshot.active_track_ids,
        "tracker_output_ids": list(snapshot.tracker_output_ids),
        "tracker_output_count": len(snapshot.tracker_output_ids),
        "person_count": snapshot.person_count,
        "vehicle_count": snapshot.vehicle_count,
        "track_count": snapshot.track_count,
    }


def telemetry_is_newer(current: dict | None, incoming: dict) -> bool:
    if current is None:
        return True
    current_session = current.get("analysis_session_id") or current.get("stream_id")
    incoming_session = incoming.get("analysis_session_id") or incoming.get("stream_id")
    if current_session != incoming_session:
        return float(incoming.get("processed_timestamp") or incoming.get("timestamp") or 0) > float(current.get("processed_timestamp") or current.get("timestamp") or 0)
    if current_session is None and incoming_session is None:
        return float(incoming.get("processed_timestamp") or incoming.get("timestamp") or 0) > float(current.get("processed_timestamp") or current.get("timestamp") or 0)
    current_frame = current.get("frame_index")
    incoming_frame = incoming.get("frame_index")
    if current_frame is not None and incoming_frame is not None and incoming_frame != current_frame:
        return int(incoming_frame) > int(current_frame)
    return int(incoming.get("sequence") or 0) > int(current.get("sequence") or 0)
