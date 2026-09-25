"""
Phase 7.4.5: Evidence Key ID (kid) Regression Test
"""
import pytest
import os
import json
from edge.evidence.packager import EdgeKeyManager, EvidencePackager, EvidenceChainStore
from shared.schemas import ReliabilityDecision, CameraHealthReport, SceneConditionReport, DecisionState

def test_evidence_package_contains_kid(tmp_path):
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    private_key_path = str(key_dir / "cam.key")
    public_key_path = str(key_dir / "cam.pub")
    
    key_manager = EdgeKeyManager(private_key_path, public_key_path)
    key_manager.load_or_generate(allow_generate=True)
    
    assert key_manager.kid is not None
    assert key_manager.kid.startswith("ed25519-")
    
    chain_store = EvidenceChainStore(str(tmp_path / "chain.db"))
    
    packager = EvidencePackager(
        camera_id="cam-1",
        key_manager=key_manager,
        chain_store=chain_store,
        clip_storage_dir=str(tmp_path / "clips")
    )
    
    rel = ReliabilityDecision(
        decision_state=DecisionState.DETECTED, 
        decision_reason="", 
        camera_health="OK",
        scene_condition="CLEAR_DAY",
        detector_confidence=0.9,
        applied_threshold=0.5,
        score_d=1, score_t=1, score_s=1, score_h=1, score_r=1
    )
    health = CameraHealthReport(camera_id="cam-1", health_state="OK", health_reason="ok")
    cond = SceneConditionReport(
        camera_id="cam-1", 
        condition="CLEAR_DAY",
        brightness_mean=128.0,
        contrast_std=50.0,
        glare_fraction=0.0
    )
    
    ep, seq_num = packager.package(
        track=None,
        reliability=rel,
        health=health,
        condition=cond,
        zone_id="zone-1",
        event_overrides={"detection_class": "person", "confidence": 0.9},
        frame=None
    )
    
    # 1. EvidencePackage model instance contains the kid
    assert ep.kid == key_manager.kid

    # 2. Serialized payload contains the kid
    serialized = ep.model_dump_json()
    parsed = json.loads(serialized)
    assert parsed.get("kid") == key_manager.kid
    
    # 3. Signature is generated
    assert ep.signature is not None

@pytest.mark.asyncio
async def test_backend_kid_propagation():
    from backend.api.events import ingest_event, _event_to_response
    from shared.schemas import EventCreateRequest, EventResponse, EvidencePackage as SchemasEvidencePackage
    from backend.models.orm import EvidencePackage as OrmEvidencePackage, Event, Camera
    from fastapi import Request
    from unittest.mock import MagicMock
    from datetime import datetime
    import json
    
    # Create an EventCreateRequest with a known kid
    test_kid = "ed25519-test-kid"
    ep_schema = SchemasEvidencePackage(
        event_id="test-event-123",
        camera_id="test-cam",
        timestamp=datetime.utcnow(),
        zone_id="test-zone",
        detection_class="person",
        confidence=0.95,
        scene_condition="CLEAR_DAY",
        camera_health_state="OK",
        decision_state="DETECTED"
    )
    # The packager sets kid dynamically after signing, so we set it directly for the test
    ep_schema.kid = test_kid
    ep_schema.hash = "fake-hash"
    ep_schema.signature = "fake-signature"
    
    payload = EventCreateRequest(
        evidence_package=ep_schema,
        edge_device_id="test-cam",
        sequence_number=1
    )
    
    # Mock Database Session
    db_mock = MagicMock()
    # Ensure camera exists to bypass stub creation and zone stub creation
    db_mock.query.return_value.filter.return_value.first.return_value = MagicMock()
    # However, when querying for existing Event, return None (not duplicate)
    # When querying for existing EvidencePackage, return None (force insert)
    # When querying for existing EvidencePackage, return None (force insert)
    # So we need a side_effect for first()
    def mock_first_side_effect():
        # First call is Zone (if we have ep.zone_id, which we do): return mock
        yield MagicMock(adjacent_command_id="COMMAND_B")
        # Second call is Camera: return mock
        yield MagicMock(owning_command_id="COMMAND_A")
        # Third call is Event: return None
        yield None
        # Fourth call is EvidencePackage: return None
        yield None
        # Provide extra Nones just in case
        while True:
            yield None
    
    first_mock = MagicMock()
    first_mock.first.side_effect = mock_first_side_effect()
    filter_mock = MagicMock()
    filter_mock.filter.return_value = first_mock
    db_mock.query.return_value = filter_mock
    
    req_mock = MagicMock(spec=Request)
    req_mock.client.host = "127.0.0.1"
    
    edge_identity_mock = MagicMock()
    edge_identity_mock.edge_id = "test-cam"
    
    # Mock background tasks / broadcast so it doesn't crash
    from unittest.mock import patch
    with patch("backend.api.websocket.broadcast_event") as mock_broadcast, \
         patch("asyncio.create_task") as mock_create_task:
        
        response = await ingest_event(request=req_mock, payload=payload, db=db_mock, edge_identity=edge_identity_mock)
    
    # Verify that db.add was called with OrmEvidencePackage containing the correct kid
    added_objects = [call.args[0] for call in db_mock.add.call_args_list]
    
    # Find the OrmEvidencePackage
    orm_eps = [obj for obj in added_objects if isinstance(obj, OrmEvidencePackage)]
    assert len(orm_eps) == 1, "EvidencePackage was not inserted"
    orm_ep = orm_eps[0]
    
    # 2. Assert ORM mapping is correct
    assert orm_ep.kid == test_kid
    
    # 3. Verify _event_to_response includes kid
    # _event_to_response does a query to get EvidencePackage. Mock that.
    db_mock_resp = MagicMock()
    db_mock_resp.query.return_value.filter.return_value.first.side_effect = [orm_ep, None] # EvidencePackage then Alert
    
    event_mock = MagicMock(spec=Event)
    event_mock.id = "test-event-123"
    event_mock.camera_id = "test-cam"
    event_mock.timestamp = datetime.utcnow()
    event_mock.detection_class = "person"
    event_mock.confidence = 0.95
    event_mock.scene_condition = "CLEAR_DAY"
    event_mock.camera_health_state = "OK"
    event_mock.decision_state = "DETECTED"
    event_mock.severity = "LOW"
    event_mock.event_type = "LINE_CROSSING"
    event_mock.detection_class = "person"
    event_mock.edge_device_id = "test-cam"
    event_mock.storage_status = "CREATED"
    event_mock.storage_provider = "local"
    event_mock.content_hash = ""
    event_mock.failure_reason = ""
    event_mock.corroboration_score = None
    event_mock.corroborated_by_event_id = None
    event_mock.corroboration_distance_m = None
    event_mock.corroboration_delta_t_s = None
    event_mock.corroboration_t_expected_s = None
    event_mock.corroboration_sigma_s = None
    event_mock.corroboration_status = None
    event_mock.appearance_similarity = None
    event_mock.representation_type = None
    event_mock.vehicle_subtype = None
    event_mock.face_match_person_id = None
    event_mock.face_match_person_name = None
    event_mock.face_match_confidence = None
    event_mock.bbox_x = 0.0
    event_mock.bbox_y = 0.0
    event_mock.bbox_w = 0.0
    event_mock.bbox_h = 0.0
    event_mock.score_d = 1.0
    event_mock.score_t = 1.0
    event_mock.score_s = 1.0
    event_mock.score_h = 1.0
    event_mock.score_r = 1.0
    event_mock.decision_reason = None
    event_mock.zone_id = "test-zone"
    event_mock.track_id = 1
    
    resp = _event_to_response(event_mock, db_mock_resp)
    assert resp.kid == test_kid
    assert resp.hash == orm_ep.sha256
    assert resp.signature == orm_ep.digital_signature


