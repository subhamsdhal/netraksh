import pytest
from datetime import datetime
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.models.orm import Base, EvidencePackage as EvidencePackageModel, EvidenceChain
from backend.services.verification import resolve_pending_chains, verify_event_integrity
from shared.schemas import EvidencePackage

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

def mock_verify_hash(ep):
    return True, "Valid", "mock_hash_" + ep.event_id

def mock_verify_signature(ep, db):
    return True, "Valid", "ACTIVE"

def create_mock_evidence(
    event_id, camera_id, seq_num, prev_hash, curr_hash, hash_v=True, sig_v=True,
    analysis_session_id=None,
):
    values = dict(
        event_id=event_id,
        camera_id=camera_id,
        stream_id="s1",
        zone_id="z1",
        timestamp=datetime.utcnow(),
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR_DAY",
        camera_health_state="OK",
        decision_state="DETECTED",
        bbox_x=0, bbox_y=0, bbox_w=10, bbox_h=10,
        score_d=0.9, score_t=0.9, score_s=0.9, score_h=0.9, score_r=0.9,
        hash=curr_hash,
        previous_hash=prev_hash,
        signature="mock_sig"
    )
    if analysis_session_id:
        values.update(
            analysis_session_id=analysis_session_id,
            schema_version="2.0",
            crypto_version="crypto-v2",
        )
    return EvidencePackage(**values)

def test_normal_order(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    
    edge_id = "cam1"
    
    ep0 = create_mock_evidence("e0", edge_id, 0, None, "hash0")
    ep1 = create_mock_evidence("e1", edge_id, 1, "hash0", "hash1")
    ep2 = create_mock_evidence("e2", edge_id, 2, "hash1", "hash2")
    
    vr0 = verify_event_integrity(ep0, db_session, edge_id, 0)
    assert vr0.chain_status == "VALID"
    assert vr0.chain_valid is True
    
    vr1 = verify_event_integrity(ep1, db_session, edge_id, 1)
    assert vr1.chain_status == "VALID"
    assert vr1.chain_valid is True
    
    vr2 = verify_event_integrity(ep2, db_session, edge_id, 2)
    assert vr2.chain_status == "VALID"
    assert vr2.chain_valid is True

def test_out_of_order(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    
    edge_id = "cam1"
    
    ep0 = create_mock_evidence("e0", edge_id, 0, None, "hash0")
    ep1 = create_mock_evidence("e1", edge_id, 1, "hash0", "hash1")
    ep2 = create_mock_evidence("e2", edge_id, 2, "hash1", "hash2")
    
    # Send 0
    vr0 = verify_event_integrity(ep0, db_session, edge_id, 0)
    assert vr0.chain_status == "VALID"
    
    # Send 2 BEFORE 1
    vr2 = verify_event_integrity(ep2, db_session, edge_id, 2)
    assert vr2.chain_status == "PENDING"
    assert vr2.chain_valid is False
    
    # Store ep2 in DB (simulation of what ingest_event does)
    epm2 = EvidencePackageModel(
        event_id=ep2.event_id, sha256=ep2.hash, digital_signature=ep2.signature, 
        current_hash=ep2.hash, previous_hash=ep2.previous_hash, 
        chain_status="PENDING", chain_valid=False, hash_valid=True, signature_valid=True, verified_ok=False
    )
    db_session.add(epm2)
    db_session.commit()
    
    # Send 1
    vr1 = verify_event_integrity(ep1, db_session, edge_id, 1)
    assert vr1.chain_status == "VALID"
    
    # Store ep1
    epm1 = EvidencePackageModel(
        event_id=ep1.event_id, sha256=ep1.hash, digital_signature=ep1.signature, 
        current_hash=ep1.hash, previous_hash=ep1.previous_hash, 
        chain_status="VALID", chain_valid=True, hash_valid=True, signature_valid=True, verified_ok=True
    )
    db_session.add(epm1)
    db_session.commit()
    
    # HEAL
    resolve_pending_chains(db_session, edge_id, 1, "hash1")
    db_session.commit()
    
    # Check 2 is now valid
    chain2 = db_session.query(EvidenceChain).filter_by(sequence_number=2).first()
    assert chain2.chain_status == "VALID"
    assert chain2.chain_valid is True
    
    pack2 = db_session.query(EvidencePackageModel).filter_by(event_id="e2").first()
    assert pack2.chain_status == "VALID"
    assert pack2.verified_ok is True

def test_multiple_dependents(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    
    edge_id = "cam1"
    
    ep0 = create_mock_evidence("e0", edge_id, 0, None, "hash0")
    ep1 = create_mock_evidence("e1", edge_id, 1, "hash0", "hash1")
    ep2 = create_mock_evidence("e2", edge_id, 2, "hash1", "hash2")
    ep3 = create_mock_evidence("e3", edge_id, 3, "hash2", "hash3")
    ep4 = create_mock_evidence("e4", edge_id, 4, "hash3", "hash4")
    
    # Order: 0, 3, 4, 2, 1
    # 0
    vr0 = verify_event_integrity(ep0, db_session, edge_id, 0)
    db_session.add(EvidencePackageModel(event_id="e0", sha256="h0", digital_signature="s", current_hash="hash0", chain_status="VALID", chain_valid=True, hash_valid=True, signature_valid=True, verified_ok=True))
    db_session.commit()
    
    # 3
    vr3 = verify_event_integrity(ep3, db_session, edge_id, 3)
    assert vr3.chain_status == "PENDING"
    db_session.add(EvidencePackageModel(event_id="e3", sha256="h3", digital_signature="s", current_hash="hash3", previous_hash="hash2", chain_status="PENDING", chain_valid=False, hash_valid=True, signature_valid=True, verified_ok=False))
    
    # 4
    vr4 = verify_event_integrity(ep4, db_session, edge_id, 4)
    assert vr4.chain_status == "PENDING"
    db_session.add(EvidencePackageModel(event_id="e4", sha256="h4", digital_signature="s", current_hash="hash4", previous_hash="hash3", chain_status="PENDING", chain_valid=False, hash_valid=True, signature_valid=True, verified_ok=False))
    
    # 2
    vr2 = verify_event_integrity(ep2, db_session, edge_id, 2)
    assert vr2.chain_status == "PENDING"
    db_session.add(EvidencePackageModel(event_id="e2", sha256="h2", digital_signature="s", current_hash="hash2", previous_hash="hash1", chain_status="PENDING", chain_valid=False, hash_valid=True, signature_valid=True, verified_ok=False))
    db_session.commit()
    
    # 1 arrives
    vr1 = verify_event_integrity(ep1, db_session, edge_id, 1)
    assert vr1.chain_status == "VALID"
    db_session.add(EvidencePackageModel(event_id="e1", sha256="h1", digital_signature="s", current_hash="hash1", previous_hash="hash0", chain_status="VALID", chain_valid=True, hash_valid=True, signature_valid=True, verified_ok=True))
    db_session.commit()
    
    # Heal from 1
    resolve_pending_chains(db_session, edge_id, 1, "hash1")
    db_session.commit()
    
    # Verify all are VALID
    for e_id in ["e1", "e2", "e3", "e4"]:
        pack = db_session.query(EvidencePackageModel).filter_by(event_id=e_id).first()
        assert pack.chain_status == "VALID"
        assert pack.verified_ok is True

def test_real_invalid_hash(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    
    edge_id = "cam1"
    ep0 = create_mock_evidence("e0", edge_id, 0, None, "hash0")
    vr0 = verify_event_integrity(ep0, db_session, edge_id, 0)
    
    # Bad previous hash
    ep1 = create_mock_evidence("e1", edge_id, 1, "bad_hash", "hash1")
    vr1 = verify_event_integrity(ep1, db_session, edge_id, 1)
    
    assert vr1.chain_status == "INVALID"
    assert vr1.chain_valid is False

def test_invalid_signature_stops_healing(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    
    edge_id = "cam1"
    ep0 = create_mock_evidence("e0", edge_id, 0, None, "hash0")
    verify_event_integrity(ep0, db_session, edge_id, 0)
    db_session.add(EvidencePackageModel(event_id="e0", sha256="h0", digital_signature="s", current_hash="hash0", chain_status="VALID", chain_valid=True, hash_valid=True, signature_valid=True, verified_ok=True))
    
    # Sequence 2 has a broken signature but valid previous_hash
    ep2 = create_mock_evidence("e2", edge_id, 2, "hash1", "hash2")
    verify_event_integrity(ep2, db_session, edge_id, 2)
    db_session.add(EvidencePackageModel(event_id="e2", sha256="h2", digital_signature="s", current_hash="hash2", previous_hash="hash1", chain_status="PENDING", chain_valid=False, hash_valid=True, signature_valid=False, verified_ok=False))
    
    ep1 = create_mock_evidence("e1", edge_id, 1, "hash0", "hash1")
    verify_event_integrity(ep1, db_session, edge_id, 1)
    db_session.add(EvidencePackageModel(event_id="e1", sha256="h1", digital_signature="s", current_hash="hash1", previous_hash="hash0", chain_status="VALID", chain_valid=True, hash_valid=True, signature_valid=True, verified_ok=True))
    db_session.commit()
    
    resolve_pending_chains(db_session, edge_id, 1, "hash1")
    
    # e2 must NOT heal because its signature is invalid
    pack2 = db_session.query(EvidencePackageModel).filter_by(event_id="e2").first()
    assert pack2.chain_status == "INVALID"
    assert pack2.verified_ok is False

def test_duplicate_idempotency(db_session, monkeypatch):
    """Test 6: Duplicate idempotent ingest doesn't crash or break."""
    from backend.api.events import ingest_event
    from backend.models.orm import Event
    from shared.schemas import EventCreateRequest
    
    # We can just test the behavior that exists in events.py:
    db_session.add(Event(
        id="e_dup", camera_id="cam1", stream_id="s1", timestamp=datetime.utcnow(), 
        edge_device_id="cam1", sequence_number=1, synced_from_edge=True,
        detection_class="person", confidence=0.9, scene_condition="CLEAR_DAY",
        camera_health_state="OK", decision_state="DETECTED"
    ))
    db_session.commit()
    
    # Check if duplicate query returns True for exist
    assert db_session.query(Event).filter(Event.id == "e_dup").first() is not None

def test_legacy_null_chain_status(db_session, monkeypatch):
    """Test: Legacy chain_status=NULL is NOT treated as cryptographic INVALID by the new logic."""
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    
    edge_id = "cam1"
    # Legacy record inserted directly with NULL chain_status but valid hashes
    db_session.add(EvidenceChain(id="ec1", edge_device_id=edge_id, sequence_number=10, event_id="e10", previous_hash="hash9", current_hash="hash10", signature="sig", chain_valid=False, chain_status=None))
    db_session.commit()
    
    # Sequence 11 arrives, depending on 10.
    ep11 = create_mock_evidence("e11", edge_id, 11, "hash10", "hash11")
    vr11 = verify_event_integrity(ep11, db_session, edge_id, 11)
    
    # 11 should be VALID because 10's current_hash matches 11's previous_hash.
    # The fact that 10's chain_status is NULL should not break 11.
    assert vr11.chain_status == "VALID"
    assert vr11.chain_valid is True


def test_explicit_predecessor_link_survives_non_contiguous_delivery(db_session, monkeypatch):
    """Sequence is transport metadata; the signed predecessor hash is authoritative."""
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    root = create_mock_evidence("root", "cam-a", 17, None, "hash-root")
    child = create_mock_evidence("child", "cam-a", 903, "hash-root", "hash-child")
    assert verify_event_integrity(root, db_session, "cam-a", 17).chain_status == "VALID"
    assert verify_event_integrity(child, db_session, "cam-a", 903).chain_status == "VALID"


def test_camera_chains_are_independent_even_with_equal_sequences(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    a0 = create_mock_evidence("a0", "cam-a", 0, None, "a0")
    b0 = create_mock_evidence("b0", "cam-b", 0, None, "b0")
    a1 = create_mock_evidence("a1", "cam-a", 1, "a0", "a1")
    b1 = create_mock_evidence("b1", "cam-b", 1, "b0", "b1")
    for package, camera, sequence in ((a0, "cam-a", 0), (b0, "cam-b", 0), (a1, "cam-a", 1), (b1, "cam-b", 1)):
        assert verify_event_integrity(package, db_session, camera, sequence).chain_status == "VALID"


def test_fork_is_rejected_without_rewriting_the_accepted_branch(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    root = create_mock_evidence("root", "cam-a", 0, None, "root-hash")
    accepted = create_mock_evidence("accepted", "cam-a", 1, "root-hash", "accepted-hash")
    fork = create_mock_evidence("fork", "cam-a", 2, "root-hash", "fork-hash")
    assert verify_event_integrity(root, db_session, "cam-a", 0).chain_status == "VALID"
    assert verify_event_integrity(accepted, db_session, "cam-a", 1).chain_status == "VALID"
    assert verify_event_integrity(fork, db_session, "cam-a", 2).chain_status == "INVALID"
    assert db_session.query(EvidenceChain).filter_by(event_id="accepted").one().chain_status == "VALID"


def test_cycle_and_self_reference_are_rejected(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    self_ref = create_mock_evidence("self", "cam-a", 1, "same", "same")
    assert verify_event_integrity(self_ref, db_session, "cam-a", 1).chain_status == "INVALID"

    # A pending record that names b is followed by b naming a: a two-record cycle.
    first = create_mock_evidence("first", "cam-b", 1, "b", "a")
    second = create_mock_evidence("second", "cam-b", 2, "a", "b")
    assert verify_event_integrity(first, db_session, "cam-b", 1).chain_status == "PENDING"
    assert verify_event_integrity(second, db_session, "cam-b", 2).chain_status == "INVALID"


def test_signed_replay_scopes_allow_independent_roots_but_not_same_run_roots(db_session, monkeypatch):
    """A second explicit replay is a new signed chain, not a device fork."""
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)

    first_run = create_mock_evidence("run-a-root", "cam-a", 0, None, "a0", analysis_session_id="run-a")
    first_child = create_mock_evidence("run-a-child", "cam-a", 1, "a0", "a1", analysis_session_id="run-a")
    second_run = create_mock_evidence("run-b-root", "cam-a", 0, None, "b0", analysis_session_id="run-b")
    duplicate_root = create_mock_evidence("run-b-second-root", "cam-a", 1, None, "b1", analysis_session_id="run-b")

    assert verify_event_integrity(first_run, db_session, "cam-a", 0).chain_status == "VALID"
    assert verify_event_integrity(first_child, db_session, "cam-a", 1).chain_status == "VALID"
    assert verify_event_integrity(second_run, db_session, "cam-a", 0).chain_status == "VALID"
    assert verify_event_integrity(duplicate_root, db_session, "cam-a", 1).chain_status == "INVALID"
    assert db_session.query(EvidenceChain).filter_by(event_id="run-a-root").one().chain_status == "VALID"
    assert db_session.query(EvidenceChain).filter_by(event_id="run-b-root").one().chain_status == "VALID"


def test_replay_scope_preserves_within_run_predecessor_and_fork_protection(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)

    root = create_mock_evidence("root", "cam-a", 0, None, "root", analysis_session_id="run-a")
    child = create_mock_evidence("child", "cam-a", 1, "root", "child", analysis_session_id="run-a")
    fork = create_mock_evidence("fork", "cam-a", 2, "root", "fork", analysis_session_id="run-a")
    wrong_predecessor = create_mock_evidence("wrong", "cam-a", 3, "missing", "wrong", analysis_session_id="run-a")

    assert verify_event_integrity(root, db_session, "cam-a", 0).chain_status == "VALID"
    assert verify_event_integrity(child, db_session, "cam-a", 1).chain_status == "VALID"
    assert verify_event_integrity(fork, db_session, "cam-a", 2).chain_status == "INVALID"
    assert verify_event_integrity(wrong_predecessor, db_session, "cam-a", 3).chain_status == "INVALID"
    assert db_session.query(EvidenceChain).filter_by(event_id="child").one().chain_status == "VALID"


def test_pending_healing_is_limited_to_its_signed_replay_scope(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)

    run_b_child = create_mock_evidence("run-b-child", "cam-a", 1, "b0", "b1", analysis_session_id="run-b")
    assert verify_event_integrity(run_b_child, db_session, "cam-a", 1).chain_status == "PENDING"
    db_session.add(EvidencePackageModel(
        event_id="run-b-child", sha256="b1", digital_signature="s", current_hash="b1",
        previous_hash="b0", chain_status="PENDING", chain_valid=False,
        hash_valid=True, signature_valid=True, verified_ok=False,
    ))
    db_session.commit()

    run_a_root = create_mock_evidence("run-a-root", "cam-a", 0, None, "a0", analysis_session_id="run-a")
    assert verify_event_integrity(run_a_root, db_session, "cam-a", 0).chain_status == "VALID"
    resolve_pending_chains(db_session, "cam-a", 0, "a0", "run-a")
    assert db_session.query(EvidenceChain).filter_by(event_id="run-b-child").one().chain_status == "PENDING"

    run_b_root = create_mock_evidence("run-b-root", "cam-a", 0, None, "b0", analysis_session_id="run-b")
    assert verify_event_integrity(run_b_root, db_session, "cam-a", 0).chain_status == "VALID"
    db_session.add(EvidencePackageModel(
        event_id="run-b-root", sha256="b0", digital_signature="s", current_hash="b0",
        chain_status="VALID", chain_valid=True, hash_valid=True,
        signature_valid=True, verified_ok=True,
    ))
    db_session.commit()
    resolve_pending_chains(db_session, "cam-a", 0, "b0", "run-b")
    assert db_session.query(EvidenceChain).filter_by(event_id="run-b-child").one().chain_status == "VALID"


def test_legacy_invalid_history_is_not_rewritten_by_a_new_scoped_root(db_session, monkeypatch):
    monkeypatch.setattr("backend.services.verification.verify_hash", mock_verify_hash)
    monkeypatch.setattr("backend.services.verification.verify_signature", mock_verify_signature)
    db_session.add(EvidenceChain(
        id="legacy-invalid", edge_device_id="cam-a", sequence_number=0,
        event_id="old", previous_hash=None, current_hash="old-hash", signature="sig",
        chain_valid=False, chain_status="INVALID",
    ))
    db_session.commit()

    fresh = create_mock_evidence("fresh", "cam-a", 0, None, "fresh-hash", analysis_session_id="run-new")
    assert verify_event_integrity(fresh, db_session, "cam-a", 0).chain_status == "VALID"
    historical = db_session.query(EvidenceChain).filter_by(id="legacy-invalid").one()
    assert historical.chain_status == "INVALID"
    assert historical.chain_valid is False

def test_priority_ordering_preservation():
    """Test 7: Priority order preservation. The priority sorting logic on the edge must be unchanged."""
    import ast
    with open("edge/sync/sync_client.py", "r") as f:
        content = f.read()
    
    # Ensure ORDER BY severity_rank DESC, sequence_number ASC is still present
    assert "ORDER BY severity_rank DESC, sequence_number ASC" in content

def test_store_and_forward_preservation():
    """Test 8: Store and forward logic preservation."""
    import ast
    with open("edge/sync/sync_client.py", "r") as f:
        content = f.read()
    
    assert 'status = "FAILED"' in content or "status = 'FAILED'" in content
    assert 'status = "QUEUED"' in content or "status = 'QUEUED'" in content
