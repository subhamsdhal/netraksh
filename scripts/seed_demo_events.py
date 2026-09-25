"""
NETRAKSH — Seed realistic, properly-signed demo events against a running
deployment (local or live), via its real public API — not a database
backdoor.

Every event carries a REAL Ed25519 signature, computed with the exact
same hash/sign algorithm the backend verifies against
(backend/services/verification.py's compute_sha256 +
EvidencePackage.get_signable_fields, imported directly here rather than
reimplemented by hand, to guarantee an exact match). A real keypair is
generated per camera and its public key registered via the real
PUT /cameras/{id}/public-key endpoint before any event references it —
without that, GET /system/verify-chain would correctly report every one
of these as a failed signature, the same way an earlier version of this
script (which sent a stub "demo-seed-not-a-real-signature" string) was
found doing during a full UI button audit — see docs/ARCHITECTURE.md's
"Full Button Audit" and "Real Data on the Live Deployment" entries.

Usage:
    NETRAKSH_BASE_URL=https://your-deployment.onrender.com \
    NETRAKSH_ADMIN_PASSWORD=<the real one, never hardcode it> \
    python scripts/seed_demo_events.py

Run from the repo root so `shared`/`backend` imports resolve.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.schemas import EvidencePackage
from backend.services.verification import compute_sha256

BASE = os.environ.get("NETRAKSH_BASE_URL", "http://localhost:8443")
ADMIN_PASSWORD = os.environ.get("NETRAKSH_ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    print("Set NETRAKSH_ADMIN_PASSWORD (never hardcode a real password into this file).")
    sys.exit(1)

now = datetime.now(timezone.utc)


def iso(minutes_ago: float) -> str:
    return (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# One real Ed25519 keypair per camera — architecturally each edge device
# signs with its own key; these stand in for the demo cameras' edge
# devices. Must match cameras that already exist on the target deployment
# (backend/main.py's _seed_demo_data creates cam-border-01/
# cam-checkpoint-01 on first boot against an empty database).
CAMERAS = {
    "cam-border-01": Ed25519PrivateKey.generate(),
    "cam-checkpoint-01": Ed25519PrivateKey.generate(),
}

EVENTS = [
    dict(
        camera_id="cam-border-01", zone_id="zone-fence-01",
        minutes_ago=18, event_type="VIRTUAL_FENCE_CROSSING", detection_class="person",
        confidence=0.94, scene_condition="CLEAR_DAY", camera_health_state="OK",
        decision_state="DETECTED", severity="HIGH", track_id=301,
        decision_reason="R_ABOVE_THRESHOLD:R=0.912>=0.750 (D=0.95,T=0.90,S=0.93,H=0.90)",
    ),
    dict(
        camera_id="cam-border-01", zone_id="zone-fence-01",
        minutes_ago=52, event_type="VIRTUAL_FENCE_CROSSING", detection_class="person",
        confidence=0.86, scene_condition="LOW_LIGHT_NIGHT", camera_health_state="OK",
        decision_state="DETECTED", severity="MEDIUM", track_id=297,
        decision_reason="R_ABOVE_THRESHOLD:R=0.803>=0.750 (D=0.86,T=0.75,S=0.70,H=0.90)",
    ),
    dict(
        camera_id="cam-border-01", zone_id="zone-fence-01",
        minutes_ago=75, event_type="LOITERING", detection_class="person",
        confidence=0.61, scene_condition="FOG_RAIN", camera_health_state="OK",
        decision_state="UNCERTAIN", severity="LOW", track_id=288,
        decision_reason="R_BELOW_THRESHOLD:R=0.612<0.750 (D=0.60,T=0.55,S=0.45,H=0.90)",
    ),
    dict(
        camera_id="cam-border-01", zone_id="zone-fence-01",
        minutes_ago=130, event_type="VIRTUAL_FENCE_CROSSING", detection_class="person",
        confidence=0.91, scene_condition="CLEAR_DAY", camera_health_state="OK",
        decision_state="DETECTED", severity="HIGH", track_id=276,
        decision_reason="R_ABOVE_THRESHOLD:R=0.885>=0.750 (D=0.92,T=0.88,S=0.85,H=0.90)",
    ),
    dict(
        camera_id="cam-checkpoint-01", zone_id="zone-checkpoint-01",
        minutes_ago=35, event_type="WRONG_DIRECTION", detection_class="vehicle",
        confidence=0.83, scene_condition="FOG_RAIN", camera_health_state="DEGRADED",
        decision_state="DETECTED", severity="MEDIUM", track_id=254,
        decision_reason="R_ABOVE_THRESHOLD_DEGRADED_CAMERA:R=0.781>=0.750 "
                         "(D=0.83,T=0.80,S=0.60,H=0.50),health=excessive_blur",
    ),
    dict(
        camera_id="cam-checkpoint-01", zone_id="zone-checkpoint-01",
        minutes_ago=60, event_type="ANPR_READ", detection_class="vehicle",
        confidence=0.97, scene_condition="CLEAR_DAY", camera_health_state="OK",
        decision_state="DETECTED", severity="LOW", track_id=245,
        decision_reason="R_ABOVE_THRESHOLD:R=0.940>=0.750 (D=0.97,T=0.92,S=0.95,H=0.90)",
    ),
]


def main() -> None:
    print(f"Logging in as admin against {BASE} ...")
    r = httpx.post(f"{BASE}/auth/token", data={"username": "admin", "password": ADMIN_PASSWORD}, timeout=30)
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    for cam_id, priv in CAMERAS.items():
        pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        r = httpx.put(f"{BASE}/cameras/{cam_id}/public-key", json={"public_key_pem": pub_pem}, headers=headers, timeout=30)
        print(f"  registered public key for {cam_id}: {r.status_code} {r.text}")

    # Chain state per camera — sequence numbers start at 0 so
    # verify_chain_continuity's "no previous to check" branch applies to
    # each camera's first event in this run.
    seq = {cam_id: 0 for cam_id in CAMERAS}
    prev_hash = {cam_id: None for cam_id in CAMERAS}

    print(f"\nSeeding {len(EVENTS)} properly-signed demo events...")
    for e in EVENTS:
        e = dict(e)
        minutes_ago = e.pop("minutes_ago")
        cam_id = e["camera_id"]
        event_id = str(uuid.uuid4())

        ep = EvidencePackage(event_id=event_id, timestamp=iso(minutes_ago), previous_hash=prev_hash[cam_id], **e)
        real_hash = compute_sha256(ep.get_signable_fields())
        signature = CAMERAS[cam_id].sign(real_hash.encode("utf-8")).hex()

        payload = {
            "edge_device_id": cam_id,
            "sequence_number": seq[cam_id],
            "evidence_package": {
                "event_id": event_id, "timestamp": iso(minutes_ago),
                "hash": real_hash, "signature": signature, "previous_hash": prev_hash[cam_id],
                **e,
            },
        }
        r = httpx.post(f"{BASE}/events", json=payload, timeout=30)
        print(f"  {e['event_type']} @ {cam_id} (seq {seq[cam_id]}, {minutes_ago}min ago): {r.status_code} {r.text}")
        seq[cam_id] += 1
        prev_hash[cam_id] = real_hash

    print("\nDone. Checking chain integrity...")
    r = httpx.get(f"{BASE}/system/verify-chain", timeout=30)
    print(r.status_code, r.json())


if __name__ == "__main__":
    main()
