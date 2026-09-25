import pytest
import time
from fastapi.testclient import TestClient

from backend.main import app
from shared.schemas import LiveTelemetryPayload, LiveTrack
from unittest.mock import patch, MagicMock

client = TestClient(app)

def test_live_telemetry_payload_validation():
    # Test valid payload with multiple tracks
    valid_payload = {
        "camera_id": "cam-01",
        "timestamp": time.time(),
        "sequence": 42,
        "tracks": [
            {
                "track_id": 1,
                "detection_class": "person",
                "confidence": 0.95,
                "bbox_x": 0.1,
                "bbox_y": 0.2,
                "bbox_w": 0.1,
                "bbox_h": 0.3
            },
            {
                "track_id": 2,
                "detection_class": "vehicle",
                "confidence": 0.88,
                "bbox_x": 0.5,
                "bbox_y": 0.5,
                "bbox_w": 0.2,
                "bbox_h": 0.2
            }
        ]
    }
    obj = LiveTelemetryPayload(**valid_payload)
    assert obj.camera_id == "cam-01"
    assert len(obj.tracks) == 2
    assert obj.sequence == 42

    # Test invalid payload (missing sequence)
    invalid_payload = valid_payload.copy()
    del invalid_payload["sequence"]
    with pytest.raises(ValueError):
        LiveTelemetryPayload(**invalid_payload)

@patch("backend.api.system.broadcast_telemetry")
def test_post_telemetry_endpoint(mock_broadcast, monkeypatch):
    from backend.config import settings
    from backend.database.session import init_db
    monkeypatch.setattr(settings, "EDGE_AUTH_TOKEN", "test-edge-auth-token-0123456789abcdef")
    init_db()
    payload = {
        "camera_id": "cam-01",
        "timestamp": time.time(),
        "sequence": 1,
        "tracks": []
    }
    response = client.post(
        "/system/telemetry",
        json=payload,
        headers={"Authorization": f"Bearer {settings.EDGE_AUTH_TOKEN}"},
    )
    assert response.status_code == 202
    assert response.json() == {"status": "ok"}
    mock_broadcast.assert_called_once()
    
def test_frontend_out_of_order_logic_simulation():
    # Simulating the React hook logic for out-of-order dropping
    last_sequence = {}
    live_tracks = {}

    def handle_telemetry(tel):
        cid = tel["camera_id"]
        if cid in last_sequence and tel["sequence"] <= last_sequence[cid]:
            return # Drop out-of-order
        last_sequence[cid] = tel["sequence"]
        live_tracks[cid] = tel

    # First packet
    handle_telemetry({"camera_id": "cam-01", "sequence": 10})
    assert last_sequence["cam-01"] == 10
    
    # Second packet (in order)
    handle_telemetry({"camera_id": "cam-01", "sequence": 11})
    assert last_sequence["cam-01"] == 11
    
    # Out of order packet (late 10)
    handle_telemetry({"camera_id": "cam-01", "sequence": 10})
    assert last_sequence["cam-01"] == 11 # Unchanged

    # Different camera
    handle_telemetry({"camera_id": "cam-02", "sequence": 5})
    assert last_sequence["cam-02"] == 5

def test_edge_telemetry_queue_latest_only_logic():
    import queue
    # Simulate the logic from edge/main.py
    telemetry_queue = queue.Queue(maxsize=2)
    dropped = 0
    produced = 0
    
    def enqueue(payload):
        nonlocal dropped, produced
        if telemetry_queue.full():
            try:
                telemetry_queue.get_nowait()
                telemetry_queue.task_done()
                dropped += 1
            except queue.Empty:
                pass
        telemetry_queue.put_nowait(payload)
        produced += 1
        
    enqueue({"seq": 1})
    enqueue({"seq": 2})
    enqueue({"seq": 3})  # Should force out seq 1
    
    assert dropped == 1
    assert produced == 3
    assert telemetry_queue.qsize() == 2
    assert telemetry_queue.get_nowait() == {"seq": 2}
    assert telemetry_queue.get_nowait() == {"seq": 3}
