import os
import pytest
import sqlite3
from edge.evidence.packager import EvidenceChainStore
from shared.schemas import EvidencePackage
from datetime import datetime

@pytest.fixture
def temp_chain_db(tmp_path):
    db_path = tmp_path / "test_chain.db"
    store = EvidenceChainStore(str(db_path))
    yield store
    # Teardown
    import gc
    gc.collect() # Force close any dangling connections
    try:
        if os.path.exists(str(db_path)):
            os.remove(str(db_path))
    except PermissionError:
        pass

def test_hash_chain_tamper_detection(temp_chain_db):
    store = temp_chain_db
    
    # Generate mock packages
    packages = []
    for i in range(3):
        ep = EvidencePackage(
            event_id=f"evt_{i}",
            camera_id="cam_test",
            timestamp=datetime.utcnow(),
            zone_id="zone_1",
            detection_class="person",
            confidence=0.9,
            scene_condition="CLEAR_DAY",
            camera_health_state="OK",
            decision_state="DETECTED"
        )
        # We don't need real Ed25519 signatures to test the linkage itself
        ep.previous_hash = store.get_latest_hash()[0]
        # set mock hash
        ep.hash = f"mock_hash_{i}"
        store.append(ep, signature=f"mock_sig_{i}")
        packages.append(ep)
        
    # Verify the clean chain is valid
    is_valid, bad_seq, msg = store.verify_chain()
    assert is_valid is True
    assert bad_seq is None
    
    # Tamper with the chain directly in SQLite (simulating an attacker modifying record 1)
    conn = sqlite3.connect(store.db_path)
    # We change the current_hash of sequence 1. This means sequence 2's previous_hash 
    # will no longer match sequence 1's current_hash.
    conn.execute("UPDATE evidence_chain SET current_hash = 'TAMPERED_HASH' WHERE sequence_number = 1")
    conn.commit()
    conn.close()
    
    # Verify the chain detects the break
    is_valid, bad_seq, msg = store.verify_chain()
    assert is_valid is False
    assert bad_seq == 2  # The break is detected AT sequence 2, which expected a different previous_hash
    assert "CHAIN BREAK" in msg
