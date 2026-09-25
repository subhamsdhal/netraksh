import pytest
import time
from edge.temporal.trajectory import TrajectoryFeatureLayer, TrajectoryFeatures
from edge.rules.behavior_analytics import BehaviorCorrelationEngine, BehaviorState, RapidApproachRule, RepeatedZoneCrossingRule, SustainedDirectionViolationRule
from shared.schemas import ZoneSchema, Polygon, Point, TrackData, BoundingBox
from shared.constants import ZoneType, EventType

@pytest.fixture
def zones():
    return [
        ZoneSchema(
            camera_id="cam-1",
            name="Restricted Zone",
            zone_type=ZoneType.FENCE,
            polygon=Polygon(points=[Point(x=100, y=100), Point(x=200, y=100), Point(x=200, y=200), Point(x=100, y=200)]),
            owning_command_id="cmd-1"
        ),
        ZoneSchema(
            camera_id="cam-1",
            name="One-Way Road",
            zone_type=ZoneType.BOUNDARY,
            polygon=Polygon(points=[Point(x=0, y=150), Point(x=300, y=150)]),
            owning_command_id="cmd-1",
            restricted_direction="A_TO_B" # Cross from bottom to top is restricted
        )
    ]

@pytest.fixture
def trajectory_layer():
    return TrajectoryFeatureLayer()

@pytest.fixture
def engine(zones):
    return BehaviorCorrelationEngine(zones)

def test_rapid_approach_rule(zones):
    rule = RapidApproachRule(zones, threshold_px_s=50.0, min_duration=0.5)
    
    # Track is moving fast towards the fence from x=0
    track = TrackData(
        track_id=1,
        detection_class="person",
        confidence=0.9,
        bbox=BoundingBox(x1=0, y1=140, x2=20, y2=160), # Centroid ~ 10,150
        trajectory=[Point(x=0,y=150), Point(x=10,y=150)]
    )
    features = TrajectoryFeatures(
        pixel_velocity_px_per_s=100.0,
        direction_vector=(1.0, 0.0),
        track_id=1,
        displacement_px=10.0,
        path_length_px=10.0,
        dwell_time_s=1.0,
        observation_window_s=1.0
    )
    
    # First frame, starts approach
    evt = rule.process(1, track, features, [], 1.0)
    assert evt is None
    assert rule.states[1] == BehaviorState.CANDIDATE
    
    # Next frame at 1.4s, duration 0.4s (under min_duration)
    track.bbox = BoundingBox(x1=40, y1=140, x2=60, y2=160)
    evt = rule.process(1, track, features, [], 1.4)
    assert evt is None
    
    # Next frame at 1.6s, duration 0.6s (over min_duration)
    track.bbox = BoundingBox(x1=60, y1=140, x2=80, y2=160)
    evt = rule.process(1, track, features, [], 1.6)
    assert evt is not None
    assert evt["event_type"] == EventType.RAPID_APPROACH_TO_BOUNDARY
    assert evt["measured_trigger_values"]["velocity_px_s"] == 100.0
    assert "why" in evt
    
def test_repeated_zone_crossing_rule(zones):
    rule = RepeatedZoneCrossingRule(zones, count_threshold=3, window_s=10.0)
    
    track = TrackData(
        track_id=2,
        detection_class="vehicle",
        confidence=0.8,
        bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10),
        trajectory=[]
    )
    features = TrajectoryFeatures(
        pixel_velocity_px_per_s=10.0,
        direction_vector=(1.0, 0.0),
        track_id=2,
        displacement_px=10.0,
        path_length_px=10.0,
        dwell_time_s=1.0,
        observation_window_s=1.0
    )
    
    base_evt = {"track_id": 2, "event_type": EventType.VIRTUAL_FENCE_CROSSING, "zone_id": "zone-1"}
    
    # Cross 1
    assert rule.process(2, track, features, [base_evt], 1.0) is None
    # Cross 2
    assert rule.process(2, track, features, [base_evt], 2.0) is None
    # Cross 3 - triggers
    evt = rule.process(2, track, features, [base_evt], 3.0)
    assert evt is not None
    assert evt["event_type"] == EventType.REPEATED_ZONE_CROSSING
    
def test_sustained_direction_violation_rule(zones):
    rule = SustainedDirectionViolationRule(zones, min_duration=1.0)
    
    track = TrackData(
        track_id=3,
        detection_class="person",
        confidence=0.9,
        bbox=BoundingBox(x1=140, y1=160, x2=160, y2=180), # Centroid (150, 170) -> below line A-B (0,150)->(300,150)
        trajectory=[]
    )
    # Moving up (towards smaller y, so side > 0 to side < 0? Wait, let's see side logic)
    features = TrajectoryFeatures(
        pixel_velocity_px_per_s=20.0,
        direction_vector=(0.0, -1.0), # Moving up
        track_id=3,
        displacement_px=10.0,
        path_length_px=10.0,
        dwell_time_s=1.0,
        observation_window_s=1.0
    )
    
    # Starts violating
    assert rule.process(3, track, features, [], 1.0) is None
    assert rule.states[3] == BehaviorState.CANDIDATE
    
    # 1.5s
    assert rule.process(3, track, features, [], 1.5) is None
    
    # 2.1s - Triggers
    evt = rule.process(3, track, features, [], 2.1)
    assert evt is not None
    assert evt["event_type"] == EventType.SUSTAINED_DIRECTION_VIOLATION
