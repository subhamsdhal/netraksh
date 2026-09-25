"""
NETRAKSH — Phase 3 Step 7: Behavioral Intelligence
State-machine backed behavior correlation engine.
Preserves existing detector/tracker. Never fabricates results.
"""
import time
import math
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from shared.constants import EventType
from shared.schemas import ZoneSchema, TrackData, Point
from edge.temporal.trajectory import TrajectoryFeatures
from edge.rules.modules import point_in_polygon

class BehaviorState(str, Enum):
    NORMAL = "NORMAL"
    CANDIDATE = "CANDIDATE"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class BehaviorRule:
    """Base class for behavior analytics rules."""
    def __init__(self, zones: List[ZoneSchema]):
        self.zones = zones
        # track_id -> State
        self.states: Dict[int, BehaviorState] = {}
        # track_id -> (timestamp_first_candidate, frame_count)
        self.candidates: Dict[int, Tuple[float, int]] = {}
        # track_id -> timestamp_confirmed (for cooldown)
        self.last_fired: Dict[int, float] = {}

    def process(self, track_id: int, track: TrackData, features: TrajectoryFeatures, events: List[dict], current_time: float, frame_width: float = 1.0, frame_height: float = 1.0) -> Optional[dict]:
        """Process track and return an event dict if rule fires."""
        raise NotImplementedError


def dist_to_segment(p: Point, a: Point, b: Point) -> float:
    """Distance from point p to line segment a-b."""
    l2 = (a.x - b.x)**2 + (a.y - b.y)**2
    if l2 == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = max(0, min(1, ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / l2))
    proj = Point(x=a.x + t * (b.x - a.x), y=a.y + t * (b.y - a.y))
    return math.hypot(p.x - proj.x, p.y - proj.y)


class RapidApproachRule(BehaviorRule):
    """
    RAPID_APPROACH_TO_BOUNDARY:
    Track moves toward a fence/restricted boundary at high speed.
    """
    def __init__(self, zones: List[ZoneSchema], threshold_px_s: float = 150.0, min_duration: float = 1.0):
        super().__init__(zones)
        self.fence_zones = [z for z in self.zones if z.zone_type == "fence"]
        self.threshold_px_s = threshold_px_s
        self.min_duration = min_duration
        self.cooldown = 10.0

    def process(self, track_id: int, track: TrackData, features: TrajectoryFeatures, events: List[dict], current_time: float, frame_width: float = 1.0, frame_height: float = 1.0) -> Optional[dict]:
        if not self.fence_zones or features.pixel_velocity_px_per_s is None:
            return None
            
        if features.pixel_velocity_px_per_s < self.threshold_px_s:
            self._reset_candidate(track_id)
            return None

        # Check if approaching any fence boundary
        # Zone coordinates are normalized, while tracker centroids and
        # trajectory direction are in frame pixels.  Convert both into the
        # same normalized coordinate system before geometry comparisons.
        if frame_width <= 0 or frame_height <= 0:
            return None
        cx = track.bbox.centroid.x / frame_width
        cy = track.bbox.centroid.y / frame_height
        vx, vy = features.direction_vector
        if vx == 0 and vy == 0:
            return None
        nvx, nvy = vx / frame_width, vy / frame_height
        norm = math.hypot(nvx, nvy)
        if norm == 0:
            return None
        nvx, nvy = nvx / norm, nvy / norm
            
        is_approaching = False
        approached_zone = None
        min_dist = float('inf')

        for zone in self.fence_zones:
            # First check if inside. If inside, not approaching boundary from outside.
            # Could also apply to inside-out, but typically it's outside-in.
            pts = zone.polygon.points
            if point_in_polygon(Point(x=cx, y=cy), pts):
                continue
                
            # Find min distance to boundary
            dist = min(dist_to_segment(Point(x=cx, y=cy), pts[i], pts[(i+1)%len(pts)]) for i in range(len(pts)))
            
            # Predict future position
            future_p = Point(x=cx + nvx * dist, y=cy + nvy * dist)
            future_dist = min(dist_to_segment(future_p, pts[i], pts[(i+1)%len(pts)]) for i in range(len(pts)))
            
            # If distance decreases significantly, it's approaching
            if future_dist < dist - 1e-4:
                is_approaching = True
                if dist < min_dist:
                    min_dist = dist
                    approached_zone = zone.zone_id

        if not is_approaching:
            self._reset_candidate(track_id)
            return None

        # State machine update
        if track_id not in self.candidates:
            self.candidates[track_id] = (current_time, 1)
            self.states[track_id] = BehaviorState.CANDIDATE
            return None
            
        first_ts, count = self.candidates[track_id]
        duration = current_time - first_ts
        self.candidates[track_id] = (first_ts, count + 1)
        
        if duration >= self.min_duration:
            # Check cooldown
            if track_id in self.last_fired and (current_time - self.last_fired[track_id]) < self.cooldown:
                return None
                
            self.states[track_id] = BehaviorState.CONFIRMED
            self.last_fired[track_id] = current_time
            self._reset_candidate(track_id)
            
            why = (f"Track {track_id} moved toward zone {approached_zone} at "
                   f"{features.pixel_velocity_px_per_s:.1f} px/s over {duration:.1f} s; "
                   f"configured threshold = {self.threshold_px_s} px/s.")
                   
            return {
                "event_type": EventType.RAPID_APPROACH_TO_BOUNDARY,
                "zone_id": approached_zone,
                "track_id": track_id,
                "detection_class": track.detection_class,
                "confidence": track.confidence,
                "behavior_type": "RAPID_APPROACH",
                "rule": "rapid_approach_to_boundary",
                "measured_trigger_values": {
                    "velocity_px_s": features.pixel_velocity_px_per_s,
                    "distance_normalized": min_dist
                },
                "observation_window": duration,
                "why": why
            }
            
        return None

    def _reset_candidate(self, track_id: int):
        if track_id in self.candidates:
            del self.candidates[track_id]
        if track_id in self.states and self.states[track_id] == BehaviorState.CANDIDATE:
            self.states[track_id] = BehaviorState.NORMAL


class RepeatedZoneCrossingRule(BehaviorRule):
    """
    REPEATED_ZONE_CROSSING:
    Track crosses into the same zone > N times in M seconds (Pacing/Jumping).
    """
    def __init__(self, zones: List[ZoneSchema], count_threshold: int = 3, window_s: float = 60.0):
        super().__init__(zones)
        self.count_threshold = count_threshold
        self.window_s = window_s
        self.cooldown = 30.0
        # track_id -> list of crossing timestamps
        self.crossings: Dict[int, List[float]] = {}
        
    def process(self, track_id: int, track: TrackData, features: TrajectoryFeatures, events: List[dict], current_time: float, frame_width: float = 1.0, frame_height: float = 1.0) -> Optional[dict]:
        # Extract base crossing events from standard modules for this track
        cross_events = [e for e in events if e.get("track_id") == track_id and e.get("event_type") == EventType.VIRTUAL_FENCE_CROSSING]
        
        if not cross_events:
            return None
            
        if track_id not in self.crossings:
            self.crossings[track_id] = []
            
        # Add new crossing
        self.crossings[track_id].append(current_time)
        
        # Prune old crossings
        self.crossings[track_id] = [ts for ts in self.crossings[track_id] if current_time - ts <= self.window_s]
        
        count = len(self.crossings[track_id])
        if count >= self.count_threshold:
            if track_id in self.last_fired and (current_time - self.last_fired[track_id]) < self.cooldown:
                return None
                
            self.states[track_id] = BehaviorState.CONFIRMED
            self.last_fired[track_id] = current_time
            self.crossings[track_id].clear() # Reset after fire
            
            zone_id = cross_events[0].get("zone_id", "unknown")
            why = (f"Track {track_id} crossed zone {zone_id} {count} times "
                   f"in the last {self.window_s} seconds; "
                   f"threshold = {self.count_threshold} crossings.")
                   
            return {
                "event_type": EventType.REPEATED_ZONE_CROSSING,
                "zone_id": zone_id,
                "track_id": track_id,
                "detection_class": track.detection_class,
                "confidence": track.confidence,
                "behavior_type": "REPEATED_CROSSING",
                "rule": "repeated_zone_crossing",
                "measured_trigger_values": {
                    "crossing_count": count
                },
                "observation_window": self.window_s,
                "why": why
            }
            
        return None


class SustainedDirectionViolationRule(BehaviorRule):
    """
    SUSTAINED_DIRECTION_VIOLATION:
    Track moves consistently in a restricted direction for a minimum duration.
    Only applies to boundary line zones with a restricted_direction.
    """
    def __init__(self, zones: List[ZoneSchema], min_duration: float = 2.0):
        super().__init__(zones)
        self.boundary_zones = [z for z in self.zones if z.zone_type == "boundary" and len(z.polygon.points) == 2 and z.restricted_direction]
        self.min_duration = min_duration
        self.cooldown = 15.0

    @staticmethod
    def _side(a: Point, b: Point, p: Point) -> int:
        cross = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
        return 1 if cross > 0 else -1 if cross < 0 else 0

    def process(self, track_id: int, track: TrackData, features: TrajectoryFeatures, events: List[dict], current_time: float, frame_width: float = 1.0, frame_height: float = 1.0) -> Optional[dict]:
        if not self.boundary_zones or not features.direction_vector:
            return None
            
        vx, vy = features.direction_vector
        if vx == 0 and vy == 0:
            return None

        # For a line A-B, normal vector is (-dy, dx). 
        # A_TO_B means moving from side > 0 to side < 0, so movement vector dot normal should be negative?
        # Actually, simpler: we see if the movement vector points heavily in the restricted direction.
        
        violation_zone = None
        is_violating = False
        
        cx, cy = track.bbox.centroid.x, track.bbox.centroid.y
        future_p = Point(x=cx + vx, y=cy + vy)
        
        for zone in self.boundary_zones:
            a, b = zone.polygon.points[0], zone.polygon.points[1]
            
            # Cross product of line vector and velocity vector
            # B-A cross v = (b.x - a.x)*vy - (b.y - a.y)*vx
            # If > 0, velocity points to side 1 (B_TO_A crossing direction)
            # If < 0, velocity points to side -1 (A_TO_B crossing direction)
            cross_vel = (b.x - a.x) * vy - (b.y - a.y) * vx
            
            if cross_vel < -0.1:
                dir_moving = "A_TO_B"
            elif cross_vel > 0.1:
                dir_moving = "B_TO_A"
            else:
                dir_moving = None
            
            if dir_moving and dir_moving == zone.restricted_direction:
                # To be distinct, the movement should have a strong component perpendicular to the line
                dx, dy = b.x - a.x, b.y - a.y
                length = math.hypot(dx, dy)
                if length > 0:
                    nx, ny = -dy / length, dx / length
                    dot = vx * nx + vy * ny
                    if abs(dot) > 0.5: # Moving distinctly perpendicular to line
                        is_violating = True
                        violation_zone = zone.zone_id
                        break
                    
        if not is_violating:
            self._reset_candidate(track_id)
            return None
            
        if track_id not in self.candidates:
            self.candidates[track_id] = (current_time, 1)
            self.states[track_id] = BehaviorState.CANDIDATE
            return None
            
        first_ts, count = self.candidates[track_id]
        duration = current_time - first_ts
        self.candidates[track_id] = (first_ts, count + 1)
        
        if duration >= self.min_duration:
            if track_id in self.last_fired and (current_time - self.last_fired[track_id]) < self.cooldown:
                return None
                
            self.states[track_id] = BehaviorState.CONFIRMED
            self.last_fired[track_id] = current_time
            self._reset_candidate(track_id)
            
            why = (f"Track {track_id} moved consistently in restricted direction "
                   f"near zone {violation_zone} over {duration:.1f} s; "
                   f"threshold = {self.min_duration} s.")
                   
            return {
                "event_type": EventType.SUSTAINED_DIRECTION_VIOLATION,
                "zone_id": violation_zone,
                "track_id": track_id,
                "detection_class": track.detection_class,
                "confidence": track.confidence,
                "behavior_type": "DIRECTION_VIOLATION",
                "rule": "sustained_direction_violation",
                "measured_trigger_values": {
                    "duration_s": duration
                },
                "observation_window": duration,
                "why": why
            }
            
        return None

    def _reset_candidate(self, track_id: int):
        if track_id in self.candidates:
            del self.candidates[track_id]
        if track_id in self.states and self.states[track_id] == BehaviorState.CANDIDATE:
            self.states[track_id] = BehaviorState.NORMAL


class BehaviorCorrelationEngine:
    def __init__(self, zones: List[ZoneSchema]):
        self.rules = [
            RapidApproachRule(zones),
            RepeatedZoneCrossingRule(zones),
            SustainedDirectionViolationRule(zones)
        ]

    def update(self, tracks: List[TrackData], features: Dict[int, TrajectoryFeatures], standard_events: List[dict], current_time: float, frame_width: float = 1.0, frame_height: float = 1.0) -> List[dict]:
        behavior_events = []
        for track in tracks:
            tid = track.track_id
            feat = features.get(tid)
            if not feat:
                continue
                
            for rule in self.rules:
                event = rule.process(
                    tid, track, feat, standard_events, current_time,
                    frame_width=frame_width, frame_height=frame_height,
                )
                if event:
                    behavior_events.append(event)
                    
        return behavior_events
