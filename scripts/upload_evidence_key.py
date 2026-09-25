#!/usr/bin/env python
"""
NETRAKSH — Uploads an edge device's AES-256 evidence-encryption key to the
backend so an authorized dashboard viewer can decrypt that camera's
evidence (architecture v4 §10). Run this once per camera, after the edge
pipeline has generated its key (edge/evidence/packager.py::EvidenceEncryptor
creates certs/edge/<camera_id>.aes on first run).

Until this is run for a camera, its evidence stays encrypted at rest (as it
always has) but GET /events/{event_id}/evidence-image will return 409 for
that camera's events — encrypted evidence with no registered key to decrypt
it, not a bug.

Usage:
    python scripts/upload_evidence_key.py --camera-id edge-001 \\
        --backend-url http://localhost:8443 \\
        --username admin --password <admin-password>

    # Or set NETRAKSH_ADMIN_USERNAME / NETRAKSH_ADMIN_PASSWORD env vars
    # instead of --username/--password.

Requires ADMIN role — this is the same trust level as uploading a camera's
Ed25519 public key (PUT /cameras/{id}/public-key).
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path


# Ensure project root is on path when run as `python scripts/upload_evidence_key.py`
sys.path.insert(0, str(Path(__file__).parent.parent))


def _read_key_b64(key_path: str) -> str:
    with open(key_path, "rb") as f:
        raw = f.read()
    if len(raw) != 32:
        raise SystemExit(f"Key file {key_path} is {len(raw)} bytes, expected 32 (AES-256) — refusing to upload")
    return base64.b64encode(raw).decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload a camera's evidence-encryption key to the NETRAKSH backend")
    parser.add_argument("--camera-id", required=True, help="Camera ID, matching EdgePipeline's camera_id")
    parser.add_argument("--backend-url", default="http://localhost:8443", help="Backend base URL")
    parser.add_argument(
        "--key-path", default=None,
        help="Path to the .aes key file. Defaults to certs/edge/<camera-id>.aes",
    )
    parser.add_argument("--username", default=os.environ.get("NETRAKSH_ADMIN_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("NETRAKSH_ADMIN_PASSWORD"))
    args = parser.parse_args()

    if not args.username or not args.password:
        raise SystemExit(
            "Missing credentials: pass --username/--password or set "
            "NETRAKSH_ADMIN_USERNAME/NETRAKSH_ADMIN_PASSWORD"
        )

    key_path = args.key_path or os.path.join("certs", "edge", f"{args.camera_id}.aes")
    if not os.path.exists(key_path):
        raise SystemExit(
            f"No key file at {key_path}. It's created by EvidenceEncryptor.load_or_generate() "
            f"the first time the edge pipeline runs for this camera — run it first."
        )
    key_b64 = _read_key_b64(key_path)

    import urllib.request
    import urllib.parse
    import json
    
    base_url = args.backend_url.rstrip("/")
    
    # Get token
    data = urllib.parse.urlencode({"username": args.username, "password": args.password}).encode("utf-8")
    req = urllib.request.Request(f"{base_url}/auth/token", data=data)
    req.add_header('Content-Type', 'application/x-www-form-urlencoded')
    
    try:
        with urllib.request.urlopen(req) as response:
            resp_data = json.loads(response.read().decode())
            token = resp_data["access_token"]
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Login failed ({e.code}): {e.read().decode()}")

    # Upload key
    put_data = json.dumps({"evidence_key_b64": key_b64}).encode("utf-8")
    req2 = urllib.request.Request(f"{base_url}/cameras/{args.camera_id}/evidence-key", data=put_data, method="PUT")
    req2.add_header("Authorization", f"Bearer {token}")
    req2.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req2) as response:
            pass
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Upload failed ({e.code}): {e.read().decode()}")

    print(f"Evidence key registered for camera '{args.camera_id}'. "
          f"GET /events/{{event_id}}/evidence-image can now decrypt this camera's evidence.")


if __name__ == "__main__":
    main()
