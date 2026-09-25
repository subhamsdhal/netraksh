"""
NETRAKSH — Camera Key Backfill Utility (Phase 4 WP-3.4)

PURPOSE:
    Migrate legacy Camera.public_key_pem records into the CameraKey registry
    introduced by WP-3.1, using deterministic kid derivation.

REQUIREMENTS:
    - Dry-run by default. Use --commit to apply changes.
    - Idempotent: running twice has the same effect as running once.
    - NEVER overwrites an existing valid (ACTIVE/RETIRED) CameraKey.
    - NEVER deletes Camera.public_key_pem.
    - Deterministic kid: "ed25519-" + lowercase(hex(SHA-256(DER SubjectPublicKeyInfo)))[:32]
    - Reports all outcome categories:
        ELIGIBLE     — camera has a public_key_pem not yet in CameraKey
        ALREADY      — camera already has a matching CameraKey record
        INVALID      — public_key_pem present but cannot be parsed
        CONFLICT     — kid already mapped to a different camera_id
        MISSING      — camera has no public_key_pem

USAGE:
    # Audit without writing (safe):
    python scripts/backfill_camera_keys.py

    # Commit migration:
    python scripts/backfill_camera_keys.py --commit

    # Audit a single camera:
    python scripts/backfill_camera_keys.py --camera-id <camera_id>
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import sys
from datetime import datetime
from typing import Optional

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from cryptography.hazmat.primitives import serialization

from backend.database.session import SessionLocal
from backend.models.orm import Camera, CameraKey
from backend.security.auth import audit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# kid derivation — must match WP-3.1 spec exactly
# ---------------------------------------------------------------------------

def derive_kid(public_key_pem: str) -> str:
    """
    Deterministic Key ID derivation per WP-3.1:

        canonical_bytes = DER SubjectPublicKeyInfo encoding of the Ed25519 public key
        digest          = SHA-256(canonical_bytes)
        kid             = "ed25519-" + lowercase_hex(digest)[:32]

    This is the SAME algorithm used by:
      - edge/evidence/packager.py::EdgeKeyManager._derive_kid()
      - backend/api/cameras.py::upload_public_key()

    Raises ValueError if the PEM cannot be parsed.
    """
    pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    canonical_bytes = pub_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = hashlib.sha256(canonical_bytes).hexdigest().lower()
    return f"ed25519-{digest[:32]}"


# ---------------------------------------------------------------------------
# Result categories
# ---------------------------------------------------------------------------

ELIGIBLE  = "ELIGIBLE"     # has public_key_pem, no CameraKey yet
ALREADY   = "ALREADY"      # CameraKey already exists and matches
INVALID   = "INVALID"      # public_key_pem present but unparseable
CONFLICT  = "CONFLICT"     # kid already mapped to a different camera
MISSING   = "MISSING"      # no public_key_pem on camera record


def _categorise_camera(cam: Camera, db) -> tuple[str, Optional[str], Optional[str]]:
    """
    Returns (category, kid_or_None, error_detail_or_None).
    """
    if not cam.public_key_pem or not cam.public_key_pem.strip():
        return MISSING, None, None

    # Try to derive kid
    try:
        kid = derive_kid(cam.public_key_pem)
    except Exception as exc:
        return INVALID, None, str(exc)

    # Check if a CameraKey with this kid already exists
    existing_key = db.query(CameraKey).filter(CameraKey.kid == kid).first()

    if existing_key:
        if existing_key.camera_id == cam.id:
            return ALREADY, kid, None
        else:
            return CONFLICT, kid, f"kid {kid} already maps to camera_id={existing_key.camera_id}"

    return ELIGIBLE, kid, None


# ---------------------------------------------------------------------------
# Main backfill function
# ---------------------------------------------------------------------------

def backfill(
    dry_run: bool = True,
    camera_id: Optional[str] = None,
) -> dict:
    """
    Perform the backfill, returning a summary dict.
    """
    db = SessionLocal()

    try:
        query = db.query(Camera)
        if camera_id:
            query = query.filter(Camera.id == camera_id)
        cameras = query.all()

        counts = {
            ELIGIBLE: 0,
            ALREADY: 0,
            INVALID: 0,
            CONFLICT: 0,
            MISSING: 0,
        }
        migrated = 0
        failed = 0
        details: list[dict] = []

        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Starting backfill — "
            f"{len(cameras)} camera(s) to inspect."
        )

        for cam in cameras:
            category, kid, error = _categorise_camera(cam, db)
            counts[category] += 1

            entry = {
                "camera_id": cam.id,
                "name": cam.name,
                "category": category,
                "kid": kid,
                "error": error,
            }
            details.append(entry)

            if category == ELIGIBLE:
                if not dry_run:
                    try:
                        new_key = CameraKey(
                            kid=kid,
                            camera_id=cam.id,
                            algorithm="ed25519",
                            purpose="EVIDENCE_SIGNING",
                            public_key_pem=cam.public_key_pem,
                            status="ACTIVE",
                            created_at=datetime.utcnow(),
                            activated_at=datetime.utcnow(),
                        )
                        db.add(new_key)
                        db.flush()
                        # Do NOT touch cam.public_key_pem — preserve it.
                        migrated += 1
                        logger.info(
                            f"  MIGRATED  camera={cam.id}  kid={kid}"
                        )
                    except Exception as exc:
                        db.rollback()
                        failed += 1
                        entry["category"] = f"FAILED ({exc})"
                        logger.error(
                            f"  FAILED    camera={cam.id}  error={exc}"
                        )
                        continue
                else:
                    logger.info(
                        f"  [DRY-RUN] WOULD MIGRATE  camera={cam.id}  kid={kid}"
                    )

            elif category == ALREADY:
                logger.info(f"  SKIP      camera={cam.id}  kid={kid}  (already migrated)")

            elif category == INVALID:
                logger.warning(f"  INVALID   camera={cam.id}  error={error}")

            elif category == CONFLICT:
                logger.warning(f"  CONFLICT  camera={cam.id}  kid={kid}  error={error}")

            elif category == MISSING:
                logger.info(f"  MISSING   camera={cam.id}  (no public_key_pem)")

        if not dry_run and migrated > 0:
            db.commit()
            # Audit log — does not include any key material
            try:
                audit(
                    db,
                    action="KEY_BACKFILL_COMPLETED",
                    detail=(
                        f"migrated={migrated} failed={failed} "
                        f"already={counts[ALREADY]} invalid={counts[INVALID]} "
                        f"conflict={counts[CONFLICT]} missing={counts[MISSING]}"
                    ),
                    success=(failed == 0),
                )
            except Exception:
                pass  # Audit failure must never block migration

        summary = {
            "dry_run": dry_run,
            "total_cameras": len(cameras),
            "eligible": counts[ELIGIBLE],
            "already_migrated": counts[ALREADY],
            "invalid": counts[INVALID],
            "conflict": counts[CONFLICT],
            "missing": counts[MISSING],
            "migrated": migrated if not dry_run else 0,
            "failed": failed if not dry_run else 0,
            "details": details,
        }

        _print_summary(summary)
        return summary

    finally:
        db.close()


def _print_summary(s: dict) -> None:
    mode = "[DRY-RUN]" if s["dry_run"] else "[COMMIT]"
    logger.info("=" * 60)
    logger.info(f"BACKFILL SUMMARY {mode}")
    logger.info("=" * 60)
    logger.info(f"  Total cameras inspected : {s['total_cameras']}")
    logger.info(f"  Eligible (not yet in DB): {s['eligible']}")
    logger.info(f"  Already migrated        : {s['already_migrated']}")
    logger.info(f"  Invalid key material    : {s['invalid']}")
    logger.info(f"  Conflict (kid collision): {s['conflict']}")
    logger.info(f"  Missing public key      : {s['missing']}")
    if not s["dry_run"]:
        logger.info(f"  Successfully migrated   : {s['migrated']}")
        logger.info(f"  Failed                  : {s['failed']}")
    else:
        logger.info(f"  (no changes written — use --commit to apply)")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill legacy Camera.public_key_pem into the CameraKey registry."
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually write CameraKey records. Default is dry-run (no writes).",
    )
    parser.add_argument(
        "--camera-id",
        dest="camera_id",
        default=None,
        help="Limit backfill to a single camera_id.",
    )
    args = parser.parse_args()

    result = backfill(dry_run=not args.commit, camera_id=args.camera_id)

    # Exit non-zero if there were failures or conflicts
    if result["failed"] > 0 or result["conflict"] > 0 or result["invalid"] > 0:
        sys.exit(1)
