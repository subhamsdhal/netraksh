import os
import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from shared.schemas import BoundingBox, TrackData, DetectionClass, EventType
from edge.detection.face_align import FaceAligner
from edge.detection.face_embedding import FaceEmbeddingEngine, ONNXFaceEmbeddingEngine
from edge.detection.face_watchlist import EmbeddingWatchlistIndex
from edge.detection.face_fusion import TemporalFaceFusion
from edge.rules.modules import FaceDetectionModule

# --- Fixtures ---

@pytest.fixture
def dummy_frame():
    return np.zeros((720, 1280, 3), dtype=np.uint8)

@pytest.fixture
def dummy_bbox():
    return BoundingBox(x1=100.0, y1=100.0, x2=200.0, y2=200.0)

@pytest.fixture
def dummy_landmarks():
    return np.array([
        [130, 130],
        [170, 130],
        [150, 150],
        [130, 180],
        [170, 180]
    ], dtype=np.float32)

@pytest.fixture
def dummy_embedding():
    # Deterministic vector
    emb = np.array([0.1, -0.2, 0.3, 0.4], dtype=np.float32)
    return emb / np.linalg.norm(emb)

# --- FaceAligner Tests ---

def test_face_aligner_landmark(dummy_frame, dummy_bbox, dummy_landmarks):
    aligner = FaceAligner(output_size=(112, 112))
    res = aligner.align(dummy_frame, dummy_bbox, dummy_landmarks)
    
    assert res["success"] is True
    assert res["alignment_method"] == "LANDMARK_ALIGNMENT"
    assert res["aligned_face"].shape == (112, 112, 3)

def test_face_aligner_bbox_fallback(dummy_frame, dummy_bbox):
    aligner = FaceAligner(output_size=(112, 112))
    # No landmarks
    res = aligner.align(dummy_frame, dummy_bbox, None)
    
    assert res["success"] is True
    assert res["alignment_method"] == "BBOX_ALIGNMENT"
    assert res["aligned_face"].shape == (112, 112, 3)

def test_face_aligner_invalid_landmarks(dummy_frame, dummy_bbox):
    aligner = FaceAligner(output_size=(112, 112))
    # 3 points instead of 5
    invalid_landmarks = np.array([[10, 10], [20, 20], [30, 30]])
    res = aligner.align(dummy_frame, dummy_bbox, invalid_landmarks)
    
    assert res["success"] is True
    assert res["alignment_method"] == "BBOX_ALIGNMENT" # fallback

# --- FaceEmbeddingEngine Tests ---

def test_onnx_embedding_engine_invalid_path():
    with pytest.raises(ValueError, match="ONNX model path not found"):
        ONNXFaceEmbeddingEngine("/fake/path/to/model.onnx")

# --- EmbeddingWatchlistIndex Tests ---

def test_watchlist_index_search(dummy_embedding):
    index = EmbeddingWatchlistIndex(match_threshold=0.5)
    
    persons = [{
        "person_id": "P_123",
        "name": "Test Subject",
        "embeddings": [dummy_embedding]
    }]
    index.sync_from_embeddings(persons)
    
    # Exact match
    res = index.search(dummy_embedding)
    assert res["state"] == "MATCH"
    assert res["person_id"] == "P_123"
    assert res["name"] == "Test Subject"
    assert res["similarity"] > 0.99

    # Unrelated vector
    other_vector = np.array([0.9, 0.1, -0.1, -0.9], dtype=np.float32)
    other_vector = other_vector / np.linalg.norm(other_vector)
    
    res2 = index.search(other_vector)
    # Cosine sim will be low
    assert res2["state"] == "UNKNOWN"

# --- TemporalFaceFusion Tests ---

def test_temporal_fusion_stable():
    fusion = TemporalFaceFusion(confirm_threshold=3)
    
    track_id = 1
    # 3 MATCHes
    fusion.add_observation(track_id, "P_123", "MATCH", 0.9)
    fusion.add_observation(track_id, "P_123", "MATCH", 0.95)
    res = fusion.add_observation(track_id, "P_123", "MATCH", 0.8)
    
    assert res["fusion_state"] == "CONFIRMED"
    assert res["person_id"] == "P_123"
    assert res["confidence"] == 0.95

def test_temporal_fusion_unstable():
    fusion = TemporalFaceFusion(confirm_threshold=2)
    track_id = 1
    
    fusion.add_observation(track_id, "P_123", "MATCH", 0.9)
    fusion.add_observation(track_id, "P_456", "MATCH", 0.9)
    fusion.add_observation(track_id, "P_123", "MATCH", 0.9)
    res = fusion.add_observation(track_id, "P_456", "MATCH", 0.9)
    
    # Conflicting identities
    assert res["fusion_state"] == "UNSTABLE"

# --- FaceDetectionModule Feature Flag Tests ---

@patch("os.environ.get")
def test_face_detection_module_embedding_unavailable(mock_env_get):
    # Mock environment to select embedding mode, but return empty path
    def env_override(key, default=""):
        if key == "FACE_RECOGNITION_ENGINE": return "embedding"
        if key == "FACE_EMBEDDING_MODEL_PATH": return ""
        return default
    mock_env_get.side_effect = env_override
    
    module = FaceDetectionModule(zones=[])
    
    assert module._engine_type == "embedding"
    assert module._embedding_engine is None
    assert "not found" in module._embedding_unavailable_reason or "invalid tool" in module._embedding_unavailable_reason or "ONNX model path not found" in module._embedding_unavailable_reason
    
    # Test result mutation
    result = {
        "event_type": EventType.FACE_DETECTED,
        "track_id": 1,
        "face_bbox": BoundingBox(x1=0, y1=0, x2=50, y2=50)
    }
    
    module._attempt_embedding_recognition(result, np.zeros((100, 100, 3), dtype=np.uint8))
    
    assert result["face_engine"] == "embedding"
    assert result["recognition_state"] == "EMBEDDING_ENGINE_UNAVAILABLE"
