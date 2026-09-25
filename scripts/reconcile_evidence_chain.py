"""Safely reconstruct missing server ledger metadata from an edge's local ledger.

This is intentionally a narrow, operator-invoked migration.  It never edits
evidence packages, events, hashes, signatures, or an existing server-chain
row.  A reconstructed row is labelled ``LEGACY_ANCHORED``: its signed hash and
link were recovered from the append-only edge ledger, but its full historical
package is not invented or claimed to have been re-verified by the server.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from backend.database.session import SessionLocal
from backend.models.orm import Camera, CameraKey, EvidenceChain


def _edge_rows(path: Path) -> list[tuple]:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT sequence_number, event_id, current_hash, previous_hash, signature "
            "FROM evidence_chain ORDER BY sequence_number"
        ).fetchall()


def _matching_key_id(db, camera_id: str, current_hash: str, signature: str) -> str | None:
    keys = db.query(CameraKey).filter(CameraKey.camera_id == camera_id).all()
    if not keys:
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        keys = [camera] if camera and camera.public_key_pem else []
    matches = []
    for key in keys:
        try:
            pem = key.public_key_pem.encode("utf-8") if isinstance(key.public_key_pem, str) else key.public_key_pem
            serialization.load_pem_public_key(pem).verify(bytes.fromhex(signature), current_hash.encode("utf-8"))
            matches.append(getattr(key, "kid", None))
        except (InvalidSignature, ValueError, TypeError):
            continue
    if len(matches) != 1:
        raise RuntimeError("each recovered row must validate against exactly one registered camera key")
    return matches[0]


def reconcile(edge_db: Path, camera_id: str, apply: bool = False) -> int:
    rows = _edge_rows(edge_db)
    if not rows:
        raise RuntimeError("edge ledger is empty")
    for previous, current in zip(rows, rows[1:]):
        if current[0] != previous[0] + 1 or current[3] != previous[2]:
            raise RuntimeError("edge ledger is not a contiguous, linked append-only chain")

    db = SessionLocal()
    try:
        existing = {row.sequence_number: row for row in db.query(EvidenceChain).filter(
            EvidenceChain.edge_device_id == camera_id
        ).all()}
        missing = [row for row in rows if row[0] not in existing]
        if not missing:
            print("No missing server-chain rows; no changes made.")
            return 0

        for sequence, event_id, current_hash, previous_hash, signature in missing:
            _matching_key_id(db, camera_id, current_hash, signature)
            if sequence - 1 in existing and existing[sequence - 1].current_hash != previous_hash:
                raise RuntimeError(f"server predecessor mismatch at sequence {sequence}")
            if sequence + 1 in existing and existing[sequence + 1].previous_hash != current_hash:
                raise RuntimeError(f"server successor mismatch at sequence {sequence}")

        print(f"Validated {len(missing)} missing signed ledger rows for {camera_id}: "
              f"{missing[0][0]}..{missing[-1][0]}.")
        if not apply:
            print("Dry run only. Re-run with --apply to insert LEGACY_ANCHORED metadata rows.")
            return 0

        for sequence, event_id, current_hash, previous_hash, signature in missing:
            db.add(EvidenceChain(
                edge_device_id=camera_id,
                sequence_number=sequence,
                event_id=event_id,
                previous_hash=previous_hash,
                current_hash=current_hash,
                kid=_matching_key_id(db, camera_id, current_hash, signature),
                signature=signature,
                verified_at=datetime.utcnow(),
                chain_valid=True,
                chain_status="LEGACY_ANCHORED",
            ))
        db.commit()
        print("Inserted immutable compatibility metadata; no evidence payload was modified.")
        return len(missing)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge-db", required=True, type=Path)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raise SystemExit(reconcile(args.edge_db, args.camera_id, args.apply))
