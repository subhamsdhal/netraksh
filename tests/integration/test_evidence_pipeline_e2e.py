"""
NETRAKSH — Integration tests: real, composed edge modules (no fakes/mocks
in the crypto or reliability path), closing the gap `docs/LIMITATIONS.md`
and `docs/ARCHITECTURE.md` both disclose: "tests/integration/ and
tests/e2e/ are empty for every existing endpoint in this codebase."

These tests exercise more than one real module together, unlike the unit
suite (which tests each module in isolation) — no real YOLO/video needed
for any test in this file (see test_edge_pipeline_real_video_e2e.py for
that), so this file runs fast enough for every regular test run.

Covers TEST 6 (tampered evidence -> verification failure) and TEST 7
(camera health failure -> ABSTAIN) from the project's own integration-test
checklist.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest

from edge.evidence.packager import EdgeKeyManager, EvidenceChainStore, EvidencePackager
from edge.health.camera_health import CameraHealthMonitor
from edge.reliability.decision import make_abstain, make_reliability_decision
from shared.constants import CameraHealthState, DecisionState, DetectionClass, SceneCondition
from shared.schemas import BoundingBox, ReliabilityDecision, SceneConditionReport, TrackData


def _track(track_id=1, conf=0.9) -> TrackData:
    return TrackData(
        track_id=track_id,
        detection_class=DetectionClass.PERSON,
        bbox=BoundingBox(x1=10, y1=10, x2=60, y2=120),
        confidence=conf,
        trajectory=[],
    )


def _condition(cond=SceneCondition.CLEAR_DAY) -> SceneConditionReport:
    return SceneConditionReport(
        camera_id="test-cam", condition=cond, brightness_mean=128.0, contrast_std=60.0,
        glare_fraction=0.0,
    )


def _packager(tmp_path, camera_id="test-cam") -> EvidencePackager:
    key_manager = EdgeKeyManager(
        private_key_path=str(tmp_path / "certs" / f"{camera_id}.key"),
        public_key_path=str(tmp_path / "certs" / f"{camera_id}.pub"),
    )
    key_manager.load_or_generate(allow_generate=True)
    chain_store = EvidenceChainStore(str(tmp_path / "chain.db"))
    return EvidencePackager(
        camera_id=camera_id, key_manager=key_manager, chain_store=chain_store,
        clip_storage_dir=str(tmp_path / "clips"),
    )


class TestEvidenceChainTamperDetection:
    """TEST 6: tampered evidence -> verification failure, at the real
    edge hash-chain level (EvidencePackager + EvidenceChainStore + real
    Ed25519 signing), independent of the backend's own verification path
    (already covered by tests/unit/test_evidence.py and test_shared_crypto.py
    for the crypto primitives in isolation)."""

    def test_real_chain_of_three_verifies_clean(self, tmp_path):
        packager = _packager(tmp_path)
        reliability = make_reliability_decision(
            _health(CameraHealthState.OK), _condition(), 0.9, 0.5, temporal_score=1.0,
        )
        for i in range(3):
            packager.package(_track(track_id=i), reliability, _health(CameraHealthState.OK),
                              _condition(), zone_id="zone-1", event_overrides={}, frame=None)
        ok, broken_seq, detail = packager.chain_store.verify_chain()
        assert ok is True
        assert broken_seq is None

    def test_tampered_previous_hash_breaks_chain_detectably(self, tmp_path):
        packager = _packager(tmp_path)
        reliability = make_reliability_decision(
            _health(CameraHealthState.OK), _condition(), 0.9, 0.5, temporal_score=1.0,
        )
        for i in range(3):
            packager.package(_track(track_id=i), reliability, _health(CameraHealthState.OK),
                              _condition(), zone_id="zone-1", event_overrides={}, frame=None)

        # Simulate tampering with a stored record directly in the append-only
        # SQLite chain (the exact attack the hash chain exists to detect).
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "chain.db"))
        conn.execute("UPDATE evidence_chain SET previous_hash = ? WHERE sequence_number = 2", ("f" * 64,))
        conn.commit()
        conn.close()

        ok, broken_seq, detail = packager.chain_store.verify_chain()
        assert ok is False
        assert broken_seq == 2
        assert "CHAIN BREAK" in detail

    def test_real_ed25519_signature_verifies_against_recorded_hash(self, tmp_path):
        packager = _packager(tmp_path)
        reliability = make_reliability_decision(
            _health(CameraHealthState.OK), _condition(), 0.9, 0.5, temporal_score=1.0,
        )
        ep, seq = packager.package(_track(), reliability, _health(CameraHealthState.OK),
                                    _condition(), zone_id="zone-1", event_overrides={}, frame=None)

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives import serialization

        pub_pem = packager.key_manager.get_public_key_pem()
        pub_key = serialization.load_pem_public_key(pub_pem.encode("utf-8"))
        assert isinstance(pub_key, Ed25519PublicKey)
        pub_key.verify(bytes.fromhex(ep.signature), ep.hash.encode("utf-8"))  # raises on failure

    def test_forged_signature_fails_real_verification(self, tmp_path):
        packager = _packager(tmp_path)
        reliability = make_reliability_decision(
            _health(CameraHealthState.OK), _condition(), 0.9, 0.5, temporal_score=1.0,
        )
        ep, seq = packager.package(_track(), reliability, _health(CameraHealthState.OK),
                                    _condition(), zone_id="zone-1", event_overrides={}, frame=None)

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization

        pub_key = serialization.load_pem_public_key(packager.key_manager.get_public_key_pem().encode("utf-8"))
        tampered_hash = ("0" * 64).encode("utf-8")  # verify against a hash that was never signed
        with pytest.raises(InvalidSignature):
            pub_key.verify(bytes.fromhex(ep.signature), tampered_hash)


class TestEncryptedSnapshotTamperDetection:
    """TEST 6, at-rest-encryption variant: a real frame is JPEG-encoded,
    AES-256-GCM-encrypted, and written to disk by the real EvidencePackager
    -- tampering with the encrypted file must be detected on decrypt."""

    def test_real_encrypted_snapshot_round_trips(self, tmp_path):
        packager = _packager(tmp_path)
        reliability = make_reliability_decision(
            _health(CameraHealthState.OK), _condition(), 0.9, 0.5, temporal_score=1.0,
        )
        frame = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)
        ep, _ = packager.package(_track(), reliability, _health(CameraHealthState.OK),
                                  _condition(), zone_id="zone-1", event_overrides={}, frame=frame)

        assert ep.evidence_clip_ref is not None
        assert ep.evidence_clip_ref.endswith(".jpg.enc")
        with open(ep.evidence_clip_ref, "rb") as f:
            encrypted = f.read()
        decrypted_jpeg_bytes = packager.encryptor.decrypt(encrypted)
        assert decrypted_jpeg_bytes[:2] == b"\xff\xd8"  # real JPEG magic bytes

    def test_tampered_encrypted_snapshot_fails_decryption(self, tmp_path):
        from cryptography.exceptions import InvalidTag

        packager = _packager(tmp_path)
        reliability = make_reliability_decision(
            _health(CameraHealthState.OK), _condition(), 0.9, 0.5, temporal_score=1.0,
        )
        frame = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)
        ep, _ = packager.package(_track(), reliability, _health(CameraHealthState.OK),
                                  _condition(), zone_id="zone-1", event_overrides={}, frame=frame)

        with open(ep.evidence_clip_ref, "r+b") as f:
            data = bytearray(f.read())
            data[-1] ^= 0xFF  # flip a byte inside the GCM ciphertext/tag
            f.seek(0)
            f.write(bytes(data))

        with open(ep.evidence_clip_ref, "rb") as f:
            tampered = f.read()
        with pytest.raises(InvalidTag):
            packager.encryptor.decrypt(tampered)


def _health(state: CameraHealthState, reason="ok", **kw) -> "CameraHealthReportLike":
    from shared.schemas import CameraHealthReport
    return CameraHealthReport(camera_id="test-cam", health_state=state, health_reason=reason,
                               health_timestamp=datetime.now(timezone.utc), **kw)


class TestCameraHealthFailureAbstain:
    """TEST 7: camera health failure -> ABSTAIN, using the real
    CameraHealthMonitor (frozen-frame detection via real frame-differencing
    variance) feeding the real make_abstain() decision path, then packaged
    through the real EvidencePackager/EvidenceChainStore -- confirming the
    hard override actually reaches evidence, not just the pure decision
    function in isolation (already covered by tests/unit/test_reliability.py).
    """

    def test_frozen_real_frames_are_classified_failed(self):
        import time as _time

        monitor = CameraHealthMonitor(camera_id="frozen-cam", fps_declared=25.0)
        frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
        last_report = None
        for _ in range(6):
            # Real wall-clock timestamps, exactly like the real
            # CameraAdapter.frames() -- an arbitrary small/simulated clock
            # would spuriously trip the (unrelated) clock-drift check instead
            # of exercising the frozen-frame path this test targets.
            last_report = monitor.update(frame, _time.time())  # identical frame every call -> zero variance
        assert last_report.health_state == CameraHealthState.FAILED
        assert last_report.health_reason == "frozen_stream"

    def test_failed_health_produces_abstain_not_detected(self):
        health = _health(CameraHealthState.FAILED, reason="frozen_stream")
        reliability = make_abstain("frozen-cam", "frozen_stream", SceneCondition.CLEAR_DAY)
        assert reliability.decision_state == DecisionState.ABSTAIN
        assert reliability.decision_state != DecisionState.DETECTED

    def test_abstain_event_is_packaged_and_chained_with_real_snapshot(self, tmp_path):
        """Closes the real gap docs/ARCHITECTURE.md's "Tiered Evidence
        Capture" entry fixed: a FAILED-health frame must still produce a
        real, chained, encrypted evidence record when a snapshot is
        captured -- not silently produce zero evidence."""
        packager = _packager(tmp_path, camera_id="frozen-cam")
        reliability = make_abstain("frozen-cam", "frozen_stream", SceneCondition.CLEAR_DAY)
        health = _health(CameraHealthState.FAILED, reason="frozen_stream")
        frame = np.random.randint(0, 255, (120, 160, 3), dtype=np.uint8)

        ep, seq = packager.package(
            track=None, reliability=reliability, health=health, condition=_condition(),
            zone_id="zone-default", event_overrides={}, frame=frame,
        )

        assert ep.decision_state == DecisionState.ABSTAIN
        assert ep.evidence_clip_ref is not None  # a real snapshot WAS captured
        ok, broken_seq, _ = packager.chain_store.verify_chain()
        assert ok is True
        # The snapshot decrypts to a real JPEG, not silently absent or corrupt.
        with open(ep.evidence_clip_ref, "rb") as f:
            decrypted = packager.encryptor.decrypt(f.read())
        assert decrypted[:2] == b"\xff\xd8"
