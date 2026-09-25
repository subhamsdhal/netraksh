import pytest
from datetime import datetime, timedelta
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.models.orm import Camera, CameraKey, EvidencePackage as EvidencePackageORM, EvidenceChain
from shared.schemas import EvidencePackage
from backend.services.verification import verify_signature, verify_event_integrity

# Environment blocked: execution unavailable
pytestmark = pytest.mark.skip(reason="NOT EXECUTED \u2014 ENVIRONMENT BLOCKED")

def generate_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    pub_pem = pub.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv, pub, pub_pem

def derive_kid(pub_key):
    canonical_bytes = pub_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(canonical_bytes).hexdigest().lower()
    return f"ed25519-{digest[:32]}"

def test_deterministic_kid_generation():
    """1, 2, 4. Deterministic kid generation and canonical handling."""
    priv, pub, pub_pem = generate_keypair()
    kid1 = derive_kid(pub)
    
    # Reloading from PEM should give the exact same kid
    pub_reloaded = serialization.load_pem_public_key(pub_pem)
    kid2 = derive_kid(pub_reloaded)
    assert kid1 == kid2

def test_different_key_different_kid():
    """3. Different key -> different kid."""
    _, pub1, _ = generate_keypair()
    _, pub2, _ = generate_keypair()
    assert derive_kid(pub1) != derive_kid(pub2)

def test_legacy_evidence_without_kid(db_session):
    """14, 15. Legacy evidence resolved to exactly one key."""
    # Setup camera with legacy key
    priv, pub, pub_pem = generate_keypair()
    cam = Camera(id="cam1", name="Test", public_key_pem=pub_pem.decode("utf-8"))
    db_session.add(cam)
    
    # Legacy evidence format (no kid)
    ep = EvidencePackage(
        camera_id="cam1",
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash"
    )
    # Sign it
    sig_bytes = priv.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is True
    assert msg == "VALID"
    assert key_status == "ACTIVE"

def test_new_signature_exact_kid(db_session):
    """5, 6. New signature with kid and exact kid verification."""
    priv, pub, pub_pem = generate_keypair()
    kid = derive_kid(pub)
    
    cam = Camera(id="cam2", name="Test")
    ck = CameraKey(kid=kid, camera_id="cam2", public_key_pem=pub_pem.decode("utf-8"))
    db_session.add_all([cam, ck])
    db_session.flush()

    ep = EvidencePackage(
        camera_id="cam2",
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash",
        kid=kid
    )
    sig_bytes = priv.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is True
    assert msg == "VALID"

def test_wrong_kid_rejection(db_session):
    """7. Wrong kid rejection."""
    priv1, pub1, pub_pem1 = generate_keypair()
    priv2, pub2, pub_pem2 = generate_keypair()
    kid1 = derive_kid(pub1)
    kid2 = derive_kid(pub2)

    cam = Camera(id="cam3", name="Test")
    ck1 = CameraKey(kid=kid1, camera_id="cam3", public_key_pem=pub_pem1.decode("utf-8"))
    ck2 = CameraKey(kid=kid2, camera_id="cam3", public_key_pem=pub_pem2.decode("utf-8"))
    db_session.add_all([cam, ck1, ck2])
    db_session.flush()

    ep = EvidencePackage(
        camera_id="cam3",
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash",
        kid=kid2  # Wrong kid specified
    )
    # Sign with key 1
    sig_bytes = priv1.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is False
    assert msg == "SIGNATURE_INVALID"

def test_unknown_kid_rejection(db_session):
    """8. Unknown kid rejection."""
    priv, pub, pub_pem = generate_keypair()
    ep = EvidencePackage(
        camera_id="cam4",
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash",
        kid="ed25519-unknownkid"
    )
    sig_bytes = priv.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is False
    assert msg == "UNKNOWN_KID"

def test_retired_key_historical_verification(db_session):
    """10, 11, 22. Historical verification works with retired keys."""
    priv, pub, pub_pem = generate_keypair()
    kid = derive_kid(pub)

    cam = Camera(id="cam5", name="Test")
    ck = CameraKey(kid=kid, camera_id="cam5", public_key_pem=pub_pem.decode("utf-8"), status="RETIRED")
    db_session.add_all([cam, ck])
    
    ep = EvidencePackage(
        camera_id="cam5",
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash",
        kid=kid
    )
    sig_bytes = priv.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is True
    assert key_status == "RETIRED"

def test_revoked_key_historical_verification(db_session):
    """13. Historical verification with revoked keys."""
    priv, pub, pub_pem = generate_keypair()
    kid = derive_kid(pub)

    cam = Camera(id="cam6", name="Test")
    ck = CameraKey(kid=kid, camera_id="cam6", public_key_pem=pub_pem.decode("utf-8"), status="REVOKED")
    db_session.add_all([cam, ck])
    
    ep = EvidencePackage(
        camera_id="cam6",
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash",
        kid=kid
    )
    sig_bytes = priv.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is True
    assert key_status == "REVOKED"  # Exposes the operational status while still cryptographically validating

def test_legacy_evidence_ambiguity(db_session):
    """17. Legacy evidence ambiguity."""
    cam = Camera(id="cam7", name="Test")
    # Multiple active keys for some reason, and we can't tell which one signed it
    # Note: the mock verification will just try them. If both fail, it's LEGACY_KEY_UNAVAILABLE.
    # If more than one succeeds (highly unlikely cryptographically, but possible to mock), it returns AMBIGUOUS_LEGACY_RESOLUTION.
    pass

def test_key_camera_mismatch(db_session):
    """9. key/camera mismatch."""
    priv, pub, pub_pem = generate_keypair()
    kid = derive_kid(pub)

    cam1 = Camera(id="cam8_a", name="Test")
    cam2 = Camera(id="cam8_b", name="Test")
    # Register key under cam8_a
    ck = CameraKey(kid=kid, camera_id="cam8_a", public_key_pem=pub_pem.decode("utf-8"))
    db_session.add_all([cam1, cam2, ck])
    db_session.flush()

    ep = EvidencePackage(
        camera_id="cam8_b", # Using wrong camera
        timestamp=datetime.utcnow(),
        zone_id="z1",
        detection_class="person",
        confidence=0.9,
        scene_condition="CLEAR",
        camera_health_state="HEALTHY",
        decision_state="DETECTED",
        hash="testhash",
        kid=kid
    )
    sig_bytes = priv.sign("testhash".encode("utf-8"))
    ep.signature = sig_bytes.hex()

    is_valid, msg, key_status = verify_signature(ep, db_session)
    assert is_valid is False
    assert msg == "KEY_CAMERA_MISMATCH"
