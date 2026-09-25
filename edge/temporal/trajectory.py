"""
NETRAKSH — Phase 3 Step 7: Trajectory Analytics
Modular trajectory feature extractor that computes pixel velocity, direction,
displacement, and dwell time.
"""
from collections import deque
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from shared.schemas import TrackData, Point

# Configuration
MAX_HISTORY_SECONDS = 30.0  # Bounded history window
STALE_TRACK_SECONDS = 5.0   # Expire track after N seconds of no updates

@dataclass
class TrajectoryObservation:
    timestamp: float
    centroid: Point

@dataclass
class TrajectoryFeatures:
    track_id: int
    pixel_velocity_px_per_s: Optional[float]
    displacement_px: float
    direction_vector: Optional[Tuple[float, float]]
    path_length_px: float
    dwell_time_s: float
    observation_window_s: float

class TrajectoryFeatureLayer:
    """
    Extracts temporal features from bounded track history.
    Does NOT depend on fixed FPS. Handles missing frames and duplicate timestamps safely.
    """
    def __init__(self):
        # track_id -> deque of TrajectoryObservation
        self._history: Dict[int, deque] = {}
        # track_id -> last update timestamp (for expiration)
        self._last_update: Dict[int, float] = {}

    def update(self, tracks: List[TrackData], current_time_s: float) -> Dict[int, TrajectoryFeatures]:
        """
        Ingests current track data and returns computed features.
        """
        self._expire_stale_tracks(current_time_s)
        
        features = {}
        for track in tracks:
            track_id = track.track_id
            
            # Using real timestamps from track, defaulting to current time if absent/invalid
            ts = track.timestamp.timestamp() if track.timestamp else current_time_s
            centroid = track.bbox.centroid
            
            if track_id not in self._history:
                self._history[track_id] = deque()
                
            history = self._history[track_id]
            
            # Prevent duplicate timestamps (e.g. from same frame) or regressions
            if history and ts <= history[-1].timestamp:
                # If exact duplicate, ignore it. If regression, something is wrong, skip.
                continue
                
            history.append(TrajectoryObservation(timestamp=ts, centroid=centroid))
            self._last_update[track_id] = current_time_s
            
            # Bound history duration
            while len(history) > 1 and (ts - history[0].timestamp) > MAX_HISTORY_SECONDS:
                history.popleft()
                
            # Compute features
            features[track_id] = self._compute_features(track_id, history)
            
        return features
        
    def _expire_stale_tracks(self, current_time_s: float):
        stale_ids = [tid for tid, last_ts in self._last_update.items() 
                     if (current_time_s - last_ts) > STALE_TRACK_SECONDS]
        for tid in stale_ids:
            del self._history[tid]
            del self._last_update[tid]

    def _compute_features(self, track_id: int, history: deque) -> TrajectoryFeatures:
        if len(history) < 2:
            return TrajectoryFeatures(
                track_id=track_id,
                pixel_velocity_px_per_s=None,
                displacement_px=0.0,
                direction_vector=None,
                path_length_px=0.0,
                dwell_time_s=0.0,
                observation_window_s=0.0
            )
            
        first = history[0]
        last = history[-1]
        
        dt = last.timestamp - first.timestamp
        
        if dt <= 0:
            # Should be prevented by duplicate check, but safe fallback
            return TrajectoryFeatures(
                track_id=track_id,
                pixel_velocity_px_per_s=None,
                displacement_px=0.0,
                direction_vector=None,
                path_length_px=0.0,
                dwell_time_s=0.0,
                observation_window_s=0.0
            )

        dx = last.centroid.x - first.centroid.x
        dy = last.centroid.y - first.centroid.y
        displacement = math.hypot(dx, dy)
        
        pixel_velocity = displacement / dt
        
        # Unit vector for overall direction
        direction_vector = (dx / displacement, dy / displacement) if displacement > 0 else (0.0, 0.0)
        
        path_length = 0.0
        for i in range(1, len(history)):
            p1 = history[i-1].centroid
            p2 = history[i].centroid
            path_length += math.hypot(p2.x - p1.x, p2.y - p1.y)
            
        return TrajectoryFeatures(
            track_id=track_id,
            pixel_velocity_px_per_s=pixel_velocity,
            displacement_px=displacement,
            direction_vector=direction_vector,
            path_length_px=path_length,
            dwell_time_s=dt,
            observation_window_s=dt
        )
