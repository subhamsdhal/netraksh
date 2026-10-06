"""
Phase 7.4.5: Continuity Identity Hardening Regression Test
"""
import pytest
import time
import numpy as np
from queue import Queue
from shared.schemas import BoundingBox, Point
from edge.tracking.continuity_guard import TrackContinuityGuard
from edge.main import EdgePipeline, hud_sample_is_due
from edge.temporal.event_verifier import EventVerifier
from edge.temporal.track_features import TrackFeatureTracker

class DummyTrack:
    def __init__(self, track_id):
        self.track_id = track_id
        self.bbox = BoundingBox(x1=10, y1=10, x2=20, y2=20, confidence=0.9)
        self.trajectory = [self.bbox.centroid]

def test_duplicate_reassociation_loop(monkeypatch):
    """
    Test that a native tracker ID repeatedly observed is mapped consistently
    and does not trigger multiple re-associations for the same ID.
    """
    # Mock pipeline
    monkeypatch.setattr("edge.main.EdgePipeline.__init__", lambda self: None)
    pipeline = EdgePipeline()
    pipeline.continuity_guard = TrackContinuityGuard()
    pipeline._known_track_ids = set()
    pipeline._track_id_map = {}
    
    # Simulate a lost track 50
    now = time.time()
    dummy_hist = np.zeros((30, 32), dtype=np.float32)
    pipeline.continuity_guard.remember_lost(
        track_id=50,
        histogram=dummy_hist,
        centroid=Point(x=15, y=15),
        trajectory=[],
        now=now
    )
    
    # Mock compute_histogram to return the dummy_hist
    monkeypatch.setattr("edge.main.compute_track_histogram", lambda f, b: dummy_hist)
    
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    
    # Frame 1: ByteTrack yields track 58.
    track_f1 = DummyTrack(58)
    processed_tracks = pipeline._apply_continuity_guard([track_f1], frame)
    
    # Track 58 should have been mapped to 50
    assert processed_tracks[0].track_id == 50
    assert 58 in pipeline._track_id_map
    assert pipeline._track_id_map[58] == 50
    
    # Frame 2: ByteTrack STILL yields native track 58
    track_f2 = DummyTrack(58)
    
    # Spy on resolve_new_track to ensure it is NOT called again
    called = []
    original_resolve = pipeline.continuity_guard.resolve_new_track
    def mock_resolve(*args, **kwargs):
        called.append(True)
        return original_resolve(*args, **kwargs)
    pipeline.continuity_guard.resolve_new_track = mock_resolve
    
    processed_tracks_2 = pipeline._apply_continuity_guard([track_f2], frame)
    
    # Assert resolve was NOT called
    assert not called, "ContinuityGuard was called again for a known native ID!"
    
    # Track 58 should remain mapped to 50
    assert processed_tracks_2[0].track_id == 50


def test_replay_boundary_resets_transient_tracker_and_rule_state():
    class RuleState:
        def __init__(self):
            self._track_zone_state = {1: {"zone": True}}
            self._track_side_state = {1: {"zone": 1}}
            self._entry_times = {1: {"zone": 1.0}}
            self._static_tracks = {1: {}}
            self._disappeared_tracks = {1: {}}
            self._fired_loitering = {(1, "zone")}

    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline._trajectories = {1: []}; pipeline._known_track_ids = {1}
    pipeline._track_last_snapshot = {1: {}}; pipeline._track_id_map = {7: 1}
    pipeline.continuity_guard = TrackContinuityGuard(); pipeline.continuity_guard._lost_pool = {1: {}}
    pipeline.track_feature_tracker = TrackFeatureTracker(); pipeline.event_verifier = EventVerifier()
    pipeline.fence_module = RuleState(); pipeline.line_module = RuleState(); pipeline.behavior_module = RuleState()
    pipeline.face_module = type("Face", (), {"_temporal_fusion": None})()
    pipeline.detector = type("Detector", (), {"_tracker": None})()
    pipeline._hud_state_lock = __import__("threading").Lock()
    pipeline._hud_tracker = type("HudTracker", (), {"reset": lambda self: None})()
    pipeline.visual_tracker = type("VisualTracker", (), {"reset": lambda self: None})()
    pipeline._reset_replay_state(2)
    assert pipeline._trajectories == {}
    assert pipeline._known_track_ids == set()
    assert pipeline.continuity_guard.get_pool_size() == 0
    assert pipeline.fence_module._track_zone_state == {}
    assert isinstance(pipeline.event_verifier, EventVerifier)


def test_hud_loop_reanchors_against_detector_frame_index():
    class HudTracker:
        def __init__(self):
            self.calls = []

        def reset(self):
            self.calls.append(("reset",))

        def observe(self, frame, frame_index):
            self.calls.append(("observe", frame_index))
            return []

        def reanchor(self, tracks, frame_index, frame):
            self.calls.append(("reanchor", frame_index))

    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline._running = False
    pipeline._hud_frame_queue = Queue()
    pipeline._hud_state_lock = __import__("threading").Lock()
    pipeline._hud_tracker = HudTracker()
    pipeline._hud_anchor_frame_index = None
    anchor_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    pipeline._hud_anchor = ([], anchor_frame, 7)
    sample_frame = np.zeros((8, 8, 3), dtype=np.uint8)
    sample_meta = type("Meta", (), {"frame_index": 8})()
    pipeline._hud_frame_queue.put((sample_frame, sample_meta))
    emitted = []
    pipeline._emit_hud_sample = lambda frame, meta, tracks: emitted.append((meta.frame_index, tracks))

    pipeline._run_hud_loop()

    assert pipeline._hud_anchor_frame_index == 7
    assert ("reanchor", 7) in pipeline._hud_tracker.calls
    assert emitted == [(8, [])]


def test_hud_samples_are_rate_limited_by_source_time():
    assert hud_sample_is_due(None, 0.0, 0.1)
    assert not hud_sample_is_due(0.0, 0.08, 0.1)
    assert hud_sample_is_due(0.0, 0.125, 0.1)
    assert hud_sample_is_due(9.9, 0.0, 0.1)
