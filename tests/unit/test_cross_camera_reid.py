import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.orm import Base, Event, Camera
from backend.services.cross_camera import find_corroboration, CorroborationResult
from backend.services.reid import ClassicalAppearanceDescriptor, BoundedTTLCache

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_classical_appearance_descriptor_safe_failure():
    """
    Test that the classical appearance descriptor fails safely when cv2 is not available
    or input is invalid.
    """
    desc = ClassicalAppearanceDescriptor()
    
    # Invalid image bytes
    res = desc.embed(b"not an image", (0.5, 0.5, 0.1, 0.1))
    assert res is None
    
    # Invalid bounding box
    res = desc.embed(b"mock_image", (None, 0.5, 0.1, 0.1))
    assert res is None

def test_ttl_cache_eviction():
    """Test the bounded TTL cache eviction logic."""
    cache = BoundedTTLCache(maxsize=3, ttl_seconds=1)
    
    cache.put("A", np.array([1.0]))
    cache.put("B", np.array([2.0]))
    cache.put("C", np.array([3.0]))
    
    assert cache.size() == 3
    assert cache.get("A") is not None
    
    # Exceed maxsize
    cache.put("D", np.array([4.0]))
    assert cache.size() == 3
    # B was evicted (oldest) since A was accessed
    assert cache.get("B") is None
    
    # Wait for TTL to expire
    import time
    time.sleep(1.1)
    assert cache.size() == 0

@patch("backend.services.reid.get_or_compute_embedding")
@patch("backend.services.cross_camera.haversine_distance_m")
@patch("backend.services.cross_camera.expected_travel_time_range")
def test_cross_camera_reid_states(mock_eta, mock_dist, mock_embed, db_session):
    """
    Test the multi-camera intelligence correlation states.
    """
    # Setup mock config
    old_setting = settings.CROSS_CAMERA_REID
    settings.CROSS_CAMERA_REID = "appearance"

    try:
        # Mocking Haversine and ETA to guarantee temporal consistency
        mock_dist.return_value = 100.0
        mock_eta.return_value = (10.0, 30.0) # t_expected = 20.0
        
        # Setup mock db
        cam1 = Camera(id="cam1", name="C1", location="L1", latitude=0.0, longitude=0.0, is_active=True)
        cam2 = Camera(id="cam2", name="C2", location="L2", latitude=0.001, longitude=0.001, is_active=True)
        db_session.add(cam1)
        db_session.add(cam2)
        db_session.commit()

        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        
        # Source Event
        event1 = Event(
            id="ev1", camera_id="cam1", timestamp=base_time, 
            detection_class="person", confidence=0.9, decision_state="DETECTED",
            scene_condition="DAY_CLEAR", camera_health_state="NOMINAL",
            evidence_clip_ref="clip1.jpg", bbox_w=0.1
        )
        # Candidate 1: Temporally consistent (+20s), Apperance strong match
        cand_strong = Event(
            id="ev_strong", camera_id="cam2", timestamp=base_time + timedelta(seconds=20),
            detection_class="person", confidence=0.9, decision_state="DETECTED",
            scene_condition="DAY_CLEAR", camera_health_state="NOMINAL",
            evidence_clip_ref="clip2.jpg", bbox_w=0.1
        )
        # Candidate 2: Temporally consistent (+20s), Appearance conflicting
        cand_conflict = Event(
            id="ev_conflict", camera_id="cam2", timestamp=base_time + timedelta(seconds=20),
            detection_class="person", confidence=0.9, decision_state="DETECTED",
            scene_condition="DAY_CLEAR", camera_health_state="NOMINAL",
            evidence_clip_ref="clip3.jpg", bbox_w=0.1
        )
        db_session.add_all([event1, cand_strong, cand_conflict])
        db_session.commit()

        # Mock embeddings: return deterministic arrays
        vec1 = np.array([1.0, 0.0, 0.0])
        vec2 = np.array([1.0, 0.0, 0.0])
        vec3 = np.array([0.0, 1.0, 0.0])

        def mock_embed_func(ev):
            if ev.id == "ev1": return vec1
            if ev.id == "ev_strong": return vec2
            if ev.id == "ev_conflict": return vec3
            return None

        mock_embed.side_effect = mock_embed_func

        # Test 1: Strong match (Tc=1.0, Sim=1.0) -> CORROBORATED
        # We need to test against only cand_strong to isolate the result
        db_session.query(Event).filter(Event.id == "ev_conflict").delete()
        db_session.commit()

        status, res = find_corroboration(event1, db_session)
        assert status == "CORROBORATED"
        assert res is not None
        assert res.appearance_similarity == 1.0
        assert res.representation_type == "CLASSICAL_APPEARANCE_DESCRIPTOR"

        # Test 2: Conflict (Tc=1.0, Sim=0.0) -> CONFLICTED
        # Add conflict candidate freshly
        cand_conflict_new = Event(
            id="ev_conflict2", camera_id="cam2", timestamp=base_time + timedelta(seconds=20),
            detection_class="person", confidence=0.9, decision_state="DETECTED",
            scene_condition="DAY_CLEAR", camera_health_state="NOMINAL",
            evidence_clip_ref="clip3.jpg", bbox_w=0.1
        )
        db_session.add(cand_conflict_new)
        db_session.query(Event).filter(Event.id == "ev_strong").delete()
        db_session.commit()
        
        def mock_embed_func2(ev):
            if ev.id == "ev1": return vec1
            if ev.id == "ev_conflict2": return vec3
            return None
        mock_embed.side_effect = mock_embed_func2

        status, res = find_corroboration(event1, db_session)
        assert status == "CONFLICTED"
        assert res is None # We don't record a corroborated result for conflicts

    finally:
        settings.CROSS_CAMERA_REID = old_setting
