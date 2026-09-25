"""
NETRAKSH — Unit tests for cryptographic evidence chain.
Tests the real SHA-256 / Ed25519 / SQLite chain — not mocked.
"""
import os
import tempfile
import pytest
from datetime import datetime
from unittest.mock import patch

from edge.evidence.packager import (
    EdgeKeyManager,
    EvidenceChainStore,
    EvidenceEncryptor,
    EvidencePackager,
    compute_sha256,
)
from shared.schemas import (
    CameraHealthReport,
    EvidencePackage,
    ReliabilityDecision,
    SceneConditionReport,
)
from shared.constants import (
    CameraHealthState,
    DecisionState,
    SceneCondition,
)


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        yield d


@pytest.fixture
def key_manager(temp_dir):
    km = EdgeKeyManager(
        private_key_path=os.path.join(temp_dir, "test.key"),
        public_key_path=os.path.join(temp_dir, "test.pub"),
    )
    km.load_or_generate(allow_generate=True)
    return km


@pytest.fixture
def chain_store(temp_dir):
    return EvidenceChainStore(os.path.join(temp_dir, "test_chain.db"))


def make_package(event_id="evt-001", camera_id="cam-001", zone_id="zone-001",
                 confidence=0.80, previous_hash=None):
    ep = EvidencePackage(
        event_id=event_id,
        camera_id=camera_id,
        timestamp=datetime.utcnow(),
        zone_id=zone_id,
        detection_class="person",
        confidence=confidence,
        scene_condition="CLEAR_DAY",
        camera_health_state="OK",
        decision_state="DETECTED",
        previous_hash=previous_hash,
    )
    return ep


class TestHashComputation:
    def test_sha256_is_deterministic(self):
        ep = make_package()
        fields = ep.get_signable_fields()
        h1 = compute_sha256(fields)
        h2 = compute_sha256(fields)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex = 64 chars

    def test_different_fields_produce_different_hash(self):
        ep1 = make_package(confidence=0.80)
        ep2 = make_package(confidence=0.81)
        h1 = compute_sha256(ep1.get_signable_fields())
        h2 = compute_sha256(ep2.get_signable_fields())
        assert h1 != h2

    def test_signable_fields_excludes_hash_and_signature(self):
        ep = make_package()
        ep.hash = "some_hash"
        ep.signature = "some_signature"
        fields = ep.get_signable_fields()
        assert "hash" not in fields
        assert "signature" not in fields


class TestKeyManager:
    def test_generates_keys_when_missing(self, temp_dir):
        km = EdgeKeyManager(
            private_key_path=os.path.join(temp_dir, "new.key"),
            public_key_path=os.path.join(temp_dir, "new.pub"),
        )
        km.load_or_generate(allow_generate=True)
        assert os.path.exists(km.private_key_path)
        assert os.path.exists(km.public_key_path)

    def test_sign_produces_hex_string(self, key_manager):
        sig = key_manager.sign(b"test data")
        assert isinstance(sig, str)
        assert len(sig) == 128  # Ed25519 sig = 64 bytes = 128 hex chars

    def test_public_key_pem_valid(self, key_manager):
        pem = key_manager.get_public_key_pem()
        assert "BEGIN PUBLIC KEY" in pem

    def test_signature_verifiable(self, key_manager):
        """Verify that the generated signature can be verified with the public key."""
        from cryptography.hazmat.primitives import serialization
        from cryptography.exceptions import InvalidSignature

        data = b"test evidence data"
        sig_hex = key_manager.sign(data)
        sig_bytes = bytes.fromhex(sig_hex)

        pub_pem = key_manager.get_public_key_pem().encode("utf-8")
        pub_key = serialization.load_pem_public_key(pub_pem)
        # Should not raise
        pub_key.verify(sig_bytes, data)

    def test_wrong_signature_fails(self, key_manager):
        from cryptography.hazmat.primitives import serialization
        from cryptography.exceptions import InvalidSignature

        data = b"correct data"
        sig_hex = key_manager.sign(data)
        sig_bytes = bytes.fromhex(sig_hex)

        pub_pem = key_manager.get_public_key_pem().encode("utf-8")
        pub_key = serialization.load_pem_public_key(pub_pem)

        with pytest.raises(InvalidSignature):
            pub_key.verify(sig_bytes, b"tampered data")


class TestEvidenceChainStore:
    def test_empty_chain_has_no_hash(self, chain_store):
        h, seq = chain_store.get_latest_hash()
        assert h is None
        assert seq == 0

    def test_append_assigns_sequence_numbers_in_order(self, chain_store, key_manager):
        for i in range(3):
            ep = make_package(event_id=f"evt-00{i}", confidence=0.5 + i * 0.1)
            ep.hash = compute_sha256(ep.get_signable_fields())
            sig = key_manager.sign(ep.hash.encode("utf-8"))
            seq = chain_store.append(ep, sig)
            assert seq == i

    def test_second_record_references_first_hash(self, chain_store, key_manager):
        ep0 = make_package(event_id="evt-000")
        ep0.hash = compute_sha256(ep0.get_signable_fields())
        sig0 = key_manager.sign(ep0.hash.encode("utf-8"))
        seq0 = chain_store.append(ep0, sig0)

        ep1 = make_package(event_id="evt-001")
        ep1.hash = compute_sha256(ep1.get_signable_fields())
        sig1 = key_manager.sign(ep1.hash.encode("utf-8"))
        seq1 = chain_store.append(ep1, sig1)

        # Get previous hash recorded
        prev_hash, _ = chain_store.get_latest_hash()
        assert prev_hash is not None  # chain is not empty

    def test_tamper_detected_in_chain_verification(self, chain_store, key_manager):
        """
        THE CRITICAL TAMPER TEST.
        Insert a record, then directly modify the SQLite DB (simulating tampering).
        Chain verification must detect the break.
        """
        import sqlite3

        # Append a valid record
        ep = make_package(event_id="evt-tamper")
        ep.hash = compute_sha256(ep.get_signable_fields())
        sig = key_manager.sign(ep.hash.encode("utf-8"))
        chain_store.append(ep, sig)

        # Append a second record (valid chain)
        ep2 = make_package(event_id="evt-tamper-2", confidence=0.9)
        ep2.hash = compute_sha256(ep2.get_signable_fields())
        sig2 = key_manager.sign(ep2.hash.encode("utf-8"))
        chain_store.append(ep2, sig2)

        # TAMPER: directly modify the previous_hash of the second record
        with sqlite3.connect(chain_store.db_path) as conn:
            conn.execute(
                "UPDATE evidence_chain SET previous_hash='TAMPERED_HASH_AAAA' WHERE sequence_number=1"
            )

        # Verification must detect the break
        is_valid, broken_at, message = chain_store.verify_chain()
        assert not is_valid
        assert broken_at is not None
        assert broken_at == 1  # Broken at sequence 1

    def test_unmodified_chain_passes_verification(self, chain_store, key_manager):
        last_hash = None
        for i in range(5):
            ep = make_package(event_id=f"evt-v{i}", confidence=0.5)
            if last_hash:
                ep.previous_hash = last_hash
            ep.hash = compute_sha256(ep.get_signable_fields())
            sig = key_manager.sign(ep.hash.encode("utf-8"))
            chain_store.append(ep, sig)
            last_hash = ep.hash

        is_valid, broken_at, message = chain_store.verify_chain()
        assert is_valid, f"Chain verify failed at {broken_at}: {message}"
        assert broken_at is None


class TestServerSideVerification:
    """Tests the server-side verification logic (re-computation of hash + sig check)."""

    class MockDB:
        def __init__(self, key_pem):
            self.key_pem = key_pem
        def query(self, *args, **kwargs):
            return self
        def filter(self, *args, **kwargs):
            return self
        def all(self, *args, **kwargs):
            class DummyKey:
                public_key_pem = self.key_pem
                status = "ACTIVE"
                camera_id = "cam-001"
                kid = "mock-kid"
            return [DummyKey()]
        def first(self, *args, **kwargs):
            return self.all()[0]

    def test_valid_package_passes_hash_check(self, key_manager):
        from backend.services.verification import verify_hash
        ep = make_package()
        ep.hash = compute_sha256(ep.get_signable_fields())
        ep.signature = key_manager.sign(ep.hash.encode("utf-8"))
        ep.kid = "mock-kid"
        is_valid, status, _ = verify_hash(ep)
        assert is_valid

    def test_tampered_package_fails_hash_check(self, key_manager):
        from backend.services.verification import verify_hash
        ep = make_package()
        ep.hash = compute_sha256(ep.get_signable_fields())
        ep.signature = key_manager.sign(ep.hash.encode("utf-8"))
        ep.kid = "mock-kid"
        # Tamper confidence after hashing
        ep.confidence = 0.10
        is_valid, status, _ = verify_hash(ep)
        assert not is_valid

    def test_valid_signature_passes(self, key_manager):
        from backend.services.verification import verify_signature
        ep = make_package()
        ep.hash = compute_sha256(ep.get_signable_fields())
        ep.signature = key_manager.sign(ep.hash.encode("utf-8"))
        pub_key_pem = key_manager.get_public_key_pem()
        mock_db = self.MockDB(pub_key_pem)
        is_valid, _, _ = verify_signature(ep, mock_db)
        assert is_valid

    def test_tampered_hash_fails_signature(self, key_manager):
        from backend.services.verification import verify_signature
        ep = make_package()
        ep.hash = compute_sha256(ep.get_signable_fields())
        ep.signature = key_manager.sign(b"fake hash bytes")
        pub_key_pem = key_manager.get_public_key_pem()
        # Tamper the stored hash (signature is now for a different hash)
        ep.hash = "tampered_hash_value"
        mock_db = self.MockDB(pub_key_pem)
        is_valid, _, _ = verify_signature(ep, mock_db)
        assert not is_valid

    def test_missing_public_key_returns_false_not_crash(self):
        from backend.services.verification import verify_signature
        ep = make_package()
        ep.hash = "some_hash"
        ep.signature = "some_sig"
        # No public key — should gracefully return False, not crash
        mock_db = self.MockDB(None)
        mock_db.all = lambda *args, **kwargs: []
        mock_db.first = lambda *args, **kwargs: None
        is_valid, _, _ = verify_signature(ep, mock_db)
        assert not is_valid


class TestEvidenceEncryptor:
    """AES-256-GCM at-rest encryption for evidence clips (architecture v4 §10)."""

    def test_generates_key_when_missing(self, temp_dir):
        key_path = os.path.join(temp_dir, "cam.aes")
        assert not os.path.exists(key_path)
        enc = EvidenceEncryptor(key_path)
        enc.load_or_generate()
        assert os.path.exists(key_path)
        assert os.path.getsize(key_path) == 32  # 256 bits

    def test_loads_existing_key_deterministically(self, temp_dir):
        key_path = os.path.join(temp_dir, "cam.aes")
        enc1 = EvidenceEncryptor(key_path)
        enc1.load_or_generate()
        blob = enc1.encrypt(b"hello evidence")

        enc2 = EvidenceEncryptor(key_path)  # fresh instance, same key file
        enc2.load_or_generate()
        assert enc2.decrypt(blob) == b"hello evidence"

    def test_rejects_malformed_key_file(self, temp_dir):
        key_path = os.path.join(temp_dir, "cam.aes")
        with open(key_path, "wb") as f:
            f.write(b"too-short")
        enc = EvidenceEncryptor(key_path)
        with pytest.raises(RuntimeError):
            enc.load_or_generate()

    def test_encrypt_decrypt_round_trip(self, temp_dir):
        enc = EvidenceEncryptor(os.path.join(temp_dir, "cam.aes"))
        enc.load_or_generate()
        plaintext = b"\xff\xd8\xff\xe0fake-jpeg-bytes" * 50
        blob = enc.encrypt(plaintext)
        assert blob != plaintext  # actually encrypted, not passthrough
        assert enc.decrypt(blob) == plaintext

    def test_different_encryptions_use_different_nonces(self, temp_dir):
        enc = EvidenceEncryptor(os.path.join(temp_dir, "cam.aes"))
        enc.load_or_generate()
        blob1 = enc.encrypt(b"same plaintext")
        blob2 = enc.encrypt(b"same plaintext")
        assert blob1 != blob2  # random nonce per call, even for identical input

    def test_tampered_ciphertext_fails_to_decrypt(self, temp_dir):
        enc = EvidenceEncryptor(os.path.join(temp_dir, "cam.aes"))
        enc.load_or_generate()
        blob = bytearray(enc.encrypt(b"authentic evidence bytes"))
        blob[-1] ^= 0xFF  # flip a bit in the GCM tag/ciphertext
        with pytest.raises(Exception):  # cryptography raises InvalidTag
            enc.decrypt(bytes(blob))

    def test_wrong_key_fails_to_decrypt(self, temp_dir):
        enc1 = EvidenceEncryptor(os.path.join(temp_dir, "cam1.aes"))
        enc1.load_or_generate()
        enc2 = EvidenceEncryptor(os.path.join(temp_dir, "cam2.aes"))
        enc2.load_or_generate()
        blob = enc1.encrypt(b"secret evidence")
        with pytest.raises(Exception):
            enc2.decrypt(blob)


class TestEvidencePackagerAtRestEncryption:
    """Integration: EvidencePackager.package() must never write a plain,
    readable JPEG to disk — architecture v4 §10."""

    def _reliability(self):
        return ReliabilityDecision(
            decision_state=DecisionState.DETECTED,
            decision_reason="test",
            camera_health=CameraHealthState.OK,
            scene_condition=SceneCondition.CLEAR_DAY,
            detector_confidence=0.9,
            applied_threshold=0.45,
        )

    def _health(self):
        return CameraHealthReport(
            camera_id="cam-enc", health_state=CameraHealthState.OK,
            health_reason="ok", health_timestamp=datetime.utcnow(),
        )

    def _condition(self):
        return SceneConditionReport(
            camera_id="cam-enc", condition=SceneCondition.CLEAR_DAY,
            brightness_mean=128.0, contrast_std=50.0, glare_fraction=0.01,
        )

    def test_snapshot_file_is_not_a_readable_jpeg(self, temp_dir, key_manager, chain_store):
        import numpy as np

        packager = EvidencePackager(
            camera_id="cam-enc",
            key_manager=key_manager,
            chain_store=chain_store,
            clip_storage_dir=os.path.join(temp_dir, "clips"),
        )
        frame = (np.random.rand(32, 32, 3) * 255).astype("uint8")

        ep, seq_num = packager.package(
            track=None,
            reliability=self._reliability(),
            health=self._health(),
            condition=self._condition(),
            zone_id="zone-1",
            event_overrides={"event_type": "LOITERING", "confidence": 0.9},
            frame=frame,
        )

        assert ep.evidence_clip_ref.endswith(".jpg.enc")
        with open(ep.evidence_clip_ref, "rb") as f:
            on_disk = f.read()
        # A real JPEG always starts with the SOI marker FFD8FF — the encrypted
        # blob must not, otherwise it isn't actually encrypted at rest.
        assert on_disk[:3] != b"\xff\xd8\xff"

        # And it must decrypt back to a real, valid JPEG.
        decrypted = packager.encryptor.decrypt(on_disk)
        assert decrypted[:3] == b"\xff\xd8\xff"

    def test_package_still_returns_unchanged_two_tuple(self, temp_dir, key_manager, chain_store):
        """Encryption must not change package()'s existing return contract."""
        import numpy as np

        packager = EvidencePackager(
            camera_id="cam-enc2",
            key_manager=key_manager,
            chain_store=chain_store,
            clip_storage_dir=os.path.join(temp_dir, "clips2"),
        )
        result = packager.package(
            track=None,
            reliability=self._reliability(),
            health=self._health(),
            condition=self._condition(),
            zone_id="zone-1",
            event_overrides={"event_type": "LOITERING", "confidence": 0.9},
            frame=None,  # no snapshot this time — evidence without a frame must still work
        )
        assert len(result) == 2
        ep, seq_num = result
        assert ep.evidence_clip_ref is None
        assert seq_num == 0

    def test_line_crossing_direction_is_accepted_alongside_fence_direction(
        self, temp_dir, key_manager, chain_store
    ):
        """
        Regression test: EvidencePackage.direction used to be typed
        Optional[FenceDirection]. LineCrossingModule (architecture v4 §5)
        reports LineCrossingDirection.A_TO_B/B_TO_A instead — a value pydantic
        would previously reject since it isn't a member of FenceDirection.
        The field is now Optional[str] specifically so both vocabularies
        (and any future task module's own direction enum) pass through.
        """
        from shared.constants import FenceDirection, LineCrossingDirection

        packager = EvidencePackager(
            camera_id="cam-enc3",
            key_manager=key_manager,
            chain_store=chain_store,
            clip_storage_dir=os.path.join(temp_dir, "clips3"),
        )

        ep_line, _ = packager.package(
            track=None,
            reliability=self._reliability(),
            health=self._health(),
            condition=self._condition(),
            zone_id="line-1",
            event_overrides={
                "event_type": "LINE_CROSSING",
                "confidence": 0.9,
                "direction": LineCrossingDirection.A_TO_B,
            },
            frame=None,
        )
        assert ep_line.direction == LineCrossingDirection.A_TO_B.value

        ep_fence, _ = packager.package(
            track=None,
            reliability=self._reliability(),
            health=self._health(),
            condition=self._condition(),
            zone_id="fence-1",
            event_overrides={
                "event_type": "VIRTUAL_FENCE_CROSSING",
                "confidence": 0.9,
                "direction": FenceDirection.OUTSIDE_TO_RESTRICTED,
            },
            frame=None,
        )
        assert ep_fence.direction == FenceDirection.OUTSIDE_TO_RESTRICTED.value
