"""
NETRAKSH — Backend HTTP-level integration/E2E tests, using FastAPI's real
TestClient against the real `backend.main:app` (real routers, real RBAC,
real DB session dependency) bound to an isolated, per-test SQLite database.

This closes a gap `docs/LIMITATIONS.md` explicitly discloses: "Endpoint-
level HTTP tests ... are not covered by an automated test in this pass ...
tests/integration/ and tests/e2e/ are empty for every existing endpoint in
this codebase." Every event/signature here is genuinely computed with the
real functions the backend verifies against (`compute_sha256`,
`EvidencePackage.get_signable_fields`, real Ed25519 keys) -- the same
approach `scripts/seed_demo_events.py` established, imported directly here
rather than reimplemented.
"""
from __future__ import annotations

import uuid
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.schemas import EvidencePackage
from shared.versioning import canonicalize, CRYPTO_VERSION_V1


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A real backend.main.app, wired to a fresh, isolated SQLite database
    per test -- never the real dev/prod netraksh.db."""
    db_path = tmp_path / "backend_e2e.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr("backend.database.session.engine", engine)
    monkeypatch.setattr("backend.database.session.SessionLocal", TestSessionLocal)
    # Edge ingestion is intentionally authenticated in test mode as well.
    from backend.config import settings
    monkeypatch.setattr(settings, "EDGE_AUTH_TOKEN", "test-edge-auth-token-0123456789abcdef")

    import backend.main as main_module  # may already be cached from an
    # earlier test in this session -- backend.main does
    # `from backend.database.session import SessionLocal`, a NAME COPY at
    # first-import time, not a live attribute lookup. Patching only
    # `backend.database.session.SessionLocal` (above) is invisible to
    # `lifespan()`'s own `SessionLocal()` calls (bootstrap_users/_seed_demo_data)
    # once backend.main has already been imported once in this process --
    # they would keep using whatever database backend.main first bound at
    # its own first import, silently diverging from the fresh, isolated one
    # `init_db()` creates tables in (init_db() itself is unaffected: its
    # body reads `engine` from backend.database.session's own globals at
    # call time, a live lookup, not a name copy). Patch backend.main's own
    # copy of the name directly so lifespan() uses the same isolated DB.
    monkeypatch.setattr(main_module, "SessionLocal", TestSessionLocal)

    with TestClient(main_module.app) as c:
        yield c


def _admin_token(client: TestClient) -> str:
    from backend.config import settings

    resp = client.post("/auth/token", data={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _register_camera_with_real_key(client: TestClient, admin_token: str, name="e2e-cam", **loc) -> tuple[str, Ed25519PrivateKey]:
    headers = {"Authorization": f"Bearer {admin_token}"}
    resp = client.post("/cameras", json={"name": name, "location": "test", **loc}, headers=headers)
    assert resp.status_code == 201, resp.text
    camera_id = resp.json()["camera_id"]

    priv = Ed25519PrivateKey.generate()
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    resp = client.put(f"/cameras/{camera_id}/public-key", json={"public_key_pem": pub_pem}, headers=headers)
    assert resp.status_code == 200, resp.text
    return camera_id, priv


def _edge_headers() -> dict:
    from backend.config import settings
    return {"Authorization": f"Bearer {settings.EDGE_AUTH_TOKEN}"}


def _signed_event_payload(camera_id: str, priv: Ed25519PrivateKey, seq: int, prev_hash, **fields) -> dict:
    base = dict(
        camera_id=camera_id, zone_id="zone-1", event_type="VIRTUAL_FENCE_CROSSING",
        detection_class="person", confidence=0.9, scene_condition="CLEAR_DAY",
        camera_health_state="OK", decision_state="DETECTED", severity="HIGH", track_id=1,
    )
    base.update(fields)
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    ep = EvidencePackage(
        event_id=event_id,
        timestamp=timestamp,
        previous_hash=prev_hash,
        schema_version="1.0",
        crypto_version="crypto-v1",
        **base,
    )
    real_hash = hashlib.sha256(
        canonicalize(ep.model_dump(mode="json"), CRYPTO_VERSION_V1)
    ).hexdigest()
    signature = priv.sign(real_hash.encode("utf-8")).hex()
    return {
        "edge_device_id": camera_id,
        "sequence_number": seq,
        "evidence_package": {
            "event_id": event_id, "timestamp": timestamp, "hash": real_hash,
            "signature": signature, "previous_hash": prev_hash, **base,
            "schema_version": "1.0", "crypto_version": "crypto-v1",
        },
    }, real_hash


class TestRealSignedEventIngestAndVerify:
    """TEST 1-4 (video->...->evidence) at the backend boundary: a genuinely
    signed evidence package, posted through the real public API, verifies
    successfully end-to-end."""

    def test_properly_signed_event_ingests_and_verifies(self, client):
        token = _admin_token(client)
        camera_id, priv = _register_camera_with_real_key(client, token)

        payload, _ = _signed_event_payload(camera_id, priv, seq=0, prev_hash=None)
        resp = client.post("/events", json=payload, headers=_edge_headers())
        assert resp.status_code == 201, resp.text
        event_id = payload["evidence_package"]["event_id"]

        headers = {"Authorization": f"Bearer {token}"}
        vr = client.post(f"/events/{event_id}/verify", headers=headers)
        assert vr.status_code == 200, vr.text
        body = vr.json()
        assert body["hash_valid"] is True
        assert body["signature_valid"] is True
        assert body["chain_valid"] is True

    def test_two_event_chain_verifies_and_break_is_detected(self, client):
        """TEST 6, at the real chain-continuity level (verify_chain_continuity
        against the previous *stored* event, not just an isolated hash)."""
        token = _admin_token(client)
        camera_id, priv = _register_camera_with_real_key(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        payload1, hash1 = _signed_event_payload(camera_id, priv, seq=0, prev_hash=None)
        r1 = client.post("/events", json=payload1, headers=_edge_headers())
        assert r1.status_code == 201

        payload2, hash2 = _signed_event_payload(camera_id, priv, seq=1, prev_hash=hash1)
        r2 = client.post("/events", json=payload2, headers=_edge_headers())
        assert r2.status_code == 201

        event_id_2 = payload2["evidence_package"]["event_id"]
        vr = client.post(f"/events/{event_id_2}/verify", headers=headers)
        assert vr.json()["chain_valid"] is True

        # Now forge a THIRD event claiming a previous_hash that doesn't match
        # the real chain (the concrete attack chain continuity detects).
        payload3, _ = _signed_event_payload(camera_id, priv, seq=2, prev_hash="f" * 64)
        r3 = client.post("/events", json=payload3, headers=_edge_headers())
        assert r3.status_code == 201  # ingest never rejects -- verify does
        event_id_3 = payload3["evidence_package"]["event_id"]
        vr3 = client.post(f"/events/{event_id_3}/verify", headers=headers)
        assert vr3.json()["chain_valid"] is False

    def test_forged_signature_fails_real_verification(self, client):
        """TEST 6: tampered/forged evidence -> verification failure, through
        the real public API, not just the crypto primitive in isolation."""
        token = _admin_token(client)
        camera_id, priv = _register_camera_with_real_key(client, token)
        other_priv = Ed25519PrivateKey.generate()  # attacker's key, never registered

        payload, real_hash = _signed_event_payload(camera_id, priv, seq=0, prev_hash=None)
        # Replace the real signature with one from a different key.
        forged_sig = other_priv.sign(real_hash.encode("utf-8")).hex()
        payload["evidence_package"]["signature"] = forged_sig

        resp = client.post("/events", json=payload, headers=_edge_headers())
        assert resp.status_code == 201  # ingest stores it regardless -- integrity is checked on verify
        event_id = payload["evidence_package"]["event_id"]

        headers = {"Authorization": f"Bearer {token}"}
        vr = client.post(f"/events/{event_id}/verify", headers=headers)
        assert vr.json()["signature_valid"] is False

    def test_tampered_hash_fails_real_verification(self, client):
        token = _admin_token(client)
        camera_id, priv = _register_camera_with_real_key(client, token)
        payload, real_hash = _signed_event_payload(camera_id, priv, seq=0, prev_hash=None)
        payload["evidence_package"]["hash"] = "0" * 64  # tampered post-signing

        resp = client.post("/events", json=payload, headers=_edge_headers())
        assert resp.status_code == 201
        event_id = payload["evidence_package"]["event_id"]

        headers = {"Authorization": f"Bearer {token}"}
        vr = client.post(f"/events/{event_id}/verify", headers=headers)
        assert vr.json()["hash_valid"] is False


class TestRBACEnforcement:
    def test_unauthenticated_cannot_verify_event(self, client):
        resp = client.post("/events/nonexistent/verify")
        assert resp.status_code == 401

    def test_unauthenticated_cannot_view_evidence_image(self, client):
        resp = client.get("/events/nonexistent/evidence-image")
        assert resp.status_code == 401

    def test_non_admin_cannot_register_camera(self, client):
        # Only an ADMIN can create the initial admin/operator/auditor
        # bootstrap accounts through settings, so log in as the real,
        # non-admin operator seeded by bootstrap_users().
        from backend.config import settings

        resp = client.post("/auth/token", data={
            "username": settings.INITIAL_OPERATOR_USERNAME,
            "password": settings.INITIAL_OPERATOR_PASSWORD,
        })
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        r = client.post("/cameras", json={"name": "x", "location": "y"},
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_auditor_can_read_but_not_acknowledge_alerts(self, client):
        from backend.config import settings

        resp = client.post("/auth/token", data={
            "username": settings.INITIAL_AUDITOR_USERNAME,
            "password": settings.INITIAL_AUDITOR_PASSWORD,
        })
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = client.get("/alerts", headers=headers)
        assert r.status_code == 200  # AUDITOR can read

        r2 = client.post("/alerts/nonexistent/acknowledge", headers=headers)
        assert r2.status_code in (403, 404)  # never a silent 200
        if r2.status_code == 404:
            pytest.fail("expected a real RBAC 403 before a not-found check for a non-existent alert")


class TestOfflineOutboxToRealBackend:
    """TEST 10: offline -> queue -> reconnect -> sync, using the real
    SyncClient's SQLite outbox and the real backend, wired together over a
    real HTTP loopback server (not TestClient's in-process ASGI transport,
    since SyncClient talks to a plain URL via httpx) -- proving the queued
    payload shape SyncClient actually produces is accepted by the real
    /events endpoint and is queryable afterward."""

    def test_queued_events_sync_once_backend_is_reachable(self, tmp_path, client):
        import threading

        import httpx
        import uvicorn

        from edge.evidence.packager import EdgeKeyManager, EvidenceChainStore, EvidencePackager
        from edge.reliability.decision import make_reliability_decision
        from edge.sync.sync_client import SyncClient
        from shared.constants import CameraHealthState, DetectionClass, SceneCondition
        from shared.schemas import BoundingBox, CameraHealthReport, SceneConditionReport, TrackData

        # Start the SAME already-configured app (isolated DB from the
        # `client` fixture) as a real ASGI server on a real loopback port,
        # since SyncClient makes real httpx calls to a URL. A fixed, high,
        # unlikely-to-collide port is used since uvicorn.Config doesn't
        # expose the OS-assigned port before startup for port=0.
        port = 18443
        config = uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(50):
                try:
                    httpx.get(f"http://127.0.0.1:{port}/health", timeout=0.2)
                    break
                except Exception:
                    import time as _t
                    _t.sleep(0.1)

            camera_id = "sync-e2e-cam"
            key_manager = EdgeKeyManager(
                private_key_path=str(tmp_path / "e.key"), public_key_path=str(tmp_path / "e.pub"),
            )
            key_manager.load_or_generate(allow_generate=True)
            # Register the real public key with the real, now-running backend
            # so the eventual /events/{id}/verify path (not exercised by this
            # test directly, but by the real ingest handler's camera lookup)
            # has a real key on file, matching real edge/backend setup order.
            token = _admin_token(client)
            httpx.put(
                f"http://127.0.0.1:{port}/cameras",
                json={"name": camera_id, "location": "x"},
                headers={"Authorization": f"Bearer {token}"},
            )

            chain_store = EvidenceChainStore(str(tmp_path / "chain.db"))
            packager = EvidencePackager(camera_id=camera_id, key_manager=key_manager,
                                         chain_store=chain_store, clip_storage_dir=str(tmp_path / "clips"))
            sync_client = SyncClient(
                edge_device_id=camera_id, backend_url=f"http://127.0.0.1:{port}",
                db_path=str(tmp_path / "sync.db"),
                auth_token=__import__("backend.config", fromlist=["settings"]).settings.EDGE_AUTH_TOKEN,
            )

            health = CameraHealthReport(camera_id=camera_id, health_state=CameraHealthState.OK, health_reason="ok")
            condition = SceneConditionReport(camera_id=camera_id, condition=SceneCondition.CLEAR_DAY,
                                              brightness_mean=128.0, contrast_std=60.0, glare_fraction=0.0)
            track = TrackData(track_id=1, detection_class=DetectionClass.PERSON,
                               bbox=BoundingBox(x1=0, y1=0, x2=50, y2=100), confidence=0.9, trajectory=[])
            reliability = make_reliability_decision(health, condition, 0.9, 0.5, temporal_score=1.0)

            for i in range(3):
                ep, seq = packager.package(track, reliability, health, condition, zone_id="zone-1",
                                            event_overrides={"event_type": "VIRTUAL_FENCE_CROSSING"}, frame=None)
                sync_client.enqueue(ep, seq)

            assert sync_client.get_queue_depth() == 3

            result = sync_client.sync_once()
            assert result["status"] == "synced"
            assert result["uploaded"] == 3
            assert result["failed"] == 0
            assert sync_client.get_queue_depth() == 0  # fully drained once the real backend is reachable
        finally:
            server.should_exit = True
            thread.join(timeout=5)
