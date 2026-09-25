"""
NETRAKSH — Server-side integrity verification service.
Verifies:
  1. SHA-256 hash validity
  2. Ed25519 signature validity
  3. Hash-chain continuity

This is the REAL cryptographic verification — not cosmetic.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from sqlalchemy.orm import Session

from backend.models.orm import EvidenceChain, CameraKey, Camera
from shared.schemas import EvidencePackage, VerificationResponse
from shared.versioning import (
    detect_profile,
    lookup_profile,
    canonicalize,
    PartialVersionMetadataError,
    UnsupportedProfileError,
)

logger = logging.getLogger(__name__)


def _would_create_cycle(db: Session, edge_device_id: str, current_hash: str, predecessor: EvidenceChain) -> bool:
    """Follow known signed links backwards and reject a cyclic predecessor graph."""
    # A current demo chain can contain thousands of records.  Load only this
    # source's hash-link columns once; issuing one SQL query per predecessor
    # made a normal Evidence Vault re-check appear to time out.
    links = {
        row.current_hash: row.previous_hash
        for row in db.query(EvidenceChain.current_hash, EvidenceChain.previous_hash).filter(
            EvidenceChain.edge_device_id == edge_device_id,
        ).all()
    }
    seen_hashes = {current_hash}
    cursor_hash = predecessor.current_hash
    for _ in range(1000):
        if cursor_hash in seen_hashes:
            return True
        seen_hashes.add(cursor_hash)
        previous_hash = links.get(cursor_hash)
        if not previous_hash:
            return False
        if previous_hash in seen_hashes:
            return True
        if previous_hash not in links:
            return False
        cursor_hash = previous_hash
    # A chain that cannot be bounded is not trustworthy.
    return True


def compute_sha256(fields: dict) -> str:
    """Deterministic SHA-256 of a sorted JSON serialization of the fields dict."""
    # Deprecated for evidence verification, retained for legacy usage elsewhere
    serialized = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_sha256_for_payload(payload_dict: dict) -> str:
    """
    Standalone tamper-evident hashing utility.

    PURPOSE:
      Generates a SHA-256 fingerprint for an arbitrary event payload dict.
      Used both server-side (on ingest) and by edge devices before signing,
      so both parties compute the hash identically and can compare them.

    ALGORITHM:
      1. Sort all keys alphabetically (deterministic regardless of insertion order)
      2. Serialize to JSON using ASCII-only encoding (no multi-byte escape issues)
      3. Hash the UTF-8 bytes with SHA-256

      The sort_keys=True and ensure_ascii=True flags are critical for
      cross-platform reproducibility: Python dicts have insertion-order semantics
      since 3.7, but a C-based edge node may serialize in a different order.
      Sorting eliminates that ambiguity entirely.

    SECURITY NOTES:
      - This hash is over the *payload content*, not the transmitted bytes.
        It is NOT a MAC and does NOT authenticate the sender.
      - The Ed25519 signature (verify_signature, below) signs this hash,
        which is what binds the hash to a specific camera's private key.
      - Together: hash proves content integrity; signature proves origin.
      - A valid hash + invalid signature means the event content wasn't tampered
        with, but it may have been replayed from a different device.
      - An invalid hash means the payload was modified after the edge computed it.

    USAGE (edge device, Python):
        from backend.services.verification import compute_sha256_for_payload
        hash_hex = compute_sha256_for_payload({
            "event_id": "...",
            "camera_id": "cam-border-01",
            "timestamp": "2026-09-12T17:51:51.574Z",
            "detection_class": "person",
            # ... all signable fields ...
        })

    USAGE (frontend display, JavaScript equivalent):
        // SubtleCrypto SHA-256:
        const encoder = new TextEncoder();
        const sorted = JSON.stringify(Object.fromEntries(
            Object.entries(payload).sort(([a], [b]) => a.localeCompare(b))
        ));
        const hashBuffer = await crypto.subtle.digest('SHA-256',
            encoder.encode(sorted));
        const hashHex = Array.from(new Uint8Array(hashBuffer))
            .map(b => b.toString(16).padStart(2, '0')).join('');

    Args:
        payload_dict: Any dict of event fields to hash.
                      Nested dicts and lists are supported (json.dumps handles them).
                      Datetime values should be serialised to ISO-8601 strings first.

    Returns:
        Lowercase hexadecimal SHA-256 digest (64 characters).
    """
    return compute_sha256(payload_dict)

def verify_hash(evidence_package: EvidencePackage) -> tuple[bool, str, Optional[str]]:
    """Recompute SHA-256 and check against stored hash.
    Returns: (is_valid, status_detail, calculated_hash)
    """
    if not evidence_package.hash:
        return False, "MISSING_HASH", None
    
    # 1. Convert to dict (simulating what gets shipped over JSON)
    envelope_dict = evidence_package.model_dump(mode="json") if hasattr(evidence_package, "model_dump") else evidence_package.dict()
    
    # 2. Detect profile
    try:
        profile_id = detect_profile(envelope_dict)
    except PartialVersionMetadataError:
        return False, "PARTIAL_VERSION_METADATA", None
        
    # 3. Lookup profile (fail closed if unknown/unsupported)
    try:
        profile = lookup_profile(profile_id)
    except UnsupportedProfileError:
        return False, "UNSUPPORTED_PROFILE", None
        
    # 4. Canonicalize
    try:
        canonical_bytes = canonicalize(envelope_dict, profile_id)
        calculated_hash = hashlib.sha256(canonical_bytes).hexdigest()
    except Exception as e:
        logger.error(f"Canonicalization error: {e}")
        return False, "CANONICALIZATION_ERROR", None
        
    is_valid = (calculated_hash == evidence_package.hash)
    return is_valid, ("VALID" if is_valid else "HASH_MISMATCH"), calculated_hash


def verify_signature(evidence_package: EvidencePackage, db: Session) -> tuple[bool, str, Optional[str]]:
    """
    Verify Ed25519 signature against the stored hash using exact kid match or legacy resolution.
    Returns: (is_valid: bool, status_message: str, key_status: Optional[str])
    """
    if not evidence_package.hash or not evidence_package.signature:
        logger.warning(f"[Verification] Missing hash or signature | event_id={evidence_package.event_id} camera_id={evidence_package.camera_id}")
        return False, "MISSING_SIGNATURE", None

    # Resolution step
    candidate_keys = []
    if evidence_package.kid:
        # EXACT resolution
        exact_key = db.query(CameraKey).filter(CameraKey.kid == evidence_package.kid).first()
        if not exact_key:
            logger.warning(f"[Verification] UNKNOWN_KID | kid={evidence_package.kid} event_id={evidence_package.event_id} camera_id={evidence_package.camera_id}")
            return False, "UNKNOWN_KID", None
        if exact_key.camera_id != evidence_package.camera_id:
            logger.warning(f"[Verification] KEY_CAMERA_MISMATCH | kid={evidence_package.kid} event_camera={evidence_package.camera_id} key_camera={exact_key.camera_id}")
            return False, "KEY_CAMERA_MISMATCH", exact_key.status
        candidate_keys = [exact_key]
    else:
        # LEGACY resolution
        candidate_keys = db.query(CameraKey).filter(CameraKey.camera_id == evidence_package.camera_id).all()
        # Fallback to legacy cameras.public_key_pem if no CameraKey records exist yet
        if not candidate_keys:
            legacy_cam = db.query(Camera).filter(Camera.id == evidence_package.camera_id).first()
            if legacy_cam and legacy_cam.public_key_pem:
                # create a dummy object for verification
                class LegacyKey:
                    public_key_pem = legacy_cam.public_key_pem
                    status = "ACTIVE"
                candidate_keys = [LegacyKey()]

    if not candidate_keys:
        logger.warning(f"[Verification] LEGACY_KEY_UNAVAILABLE | camera_id={evidence_package.camera_id} event_id={evidence_package.event_id}")
        return False, "LEGACY_KEY_UNAVAILABLE", None

    valid_count = 0
    key_status = None
    for ck in candidate_keys:
        try:
            pub_key_bytes = ck.public_key_pem.encode("utf-8") if isinstance(ck.public_key_pem, str) else ck.public_key_pem
            pub_key = serialization.load_pem_public_key(pub_key_bytes)
            sig_bytes = bytes.fromhex(evidence_package.signature)
            hash_bytes = evidence_package.hash.encode("utf-8")
            pub_key.verify(sig_bytes, hash_bytes)  # Ed25519 verify
            valid_count += 1
            key_status = ck.status
        except InvalidSignature:
            continue
        except Exception as exc:
            logger.error(f"Signature verification error for event {evidence_package.event_id}: {exc}")
            continue

    if valid_count == 1:
        return True, "VALID", key_status
    elif valid_count == 0:
        if evidence_package.kid:
            return False, "SIGNATURE_INVALID", candidate_keys[0].status
        else:
            return False, "LEGACY_KEY_UNAVAILABLE", None
    else:
        return False, "AMBIGUOUS_LEGACY_RESOLUTION", None


def verify_chain_continuity(
    db: Session,
    edge_device_id: str,
    sequence_number: int,
    current_hash: str,
    previous_hash: Optional[str],
    event_id: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Verify signed predecessor linkage within one authenticated edge source.

    ``sequence_number`` is a delivery/order hint, not cryptographic chain
    identity.  Store-and-forward clients can legitimately upload evidence out
    of order (and old installations did not always retain contiguous sequence
    numbers).  The signed ``previous_hash`` is the authority.  This keeps
    chains independent per camera while allowing a missing predecessor to be
    resolved later without classifying authentic evidence as tampered.
    Returns (is_valid: bool, status: str)
    """
    same_source = db.query(EvidenceChain).filter(
        EvidenceChain.edge_device_id == edge_device_id,
    )

    # A root is only legitimate when this source has no other root.  This
    # permits an out-of-order root to arrive after pending descendants, but
    # prevents an unannounced source replacement from silently starting a
    # second chain.
    if not previous_hash:
        roots = same_source.filter(EvidenceChain.previous_hash.is_(None)).all()
        if any(root.event_id != event_id for root in roots):
            logger.warning("Unexpected second genesis record for device %s", edge_device_id)
            return False, "INVALID"
        return True, "VALID"

    if previous_hash == current_hash:
        logger.warning("Self-referential evidence chain for device %s", edge_device_id)
        return False, "INVALID"

    predecessors = same_source.filter(
        EvidenceChain.current_hash == previous_hash,
        EvidenceChain.event_id != "",
    ).all()
    # On a re-verify the current record is in this query only if a corrupted
    # package points to its own hash; that is a cycle, never a predecessor.
    predecessors = [row for row in predecessors if row.event_id != event_id]
    if not predecessors:
        # Compatibility guard for contiguous legacy senders: if the claimed
        # immediate predecessor is already present but its hash differs, this
        # is a real splice/tamper attempt, not an out-of-order gap.
        sequence_predecessor = same_source.filter(
            EvidenceChain.sequence_number == sequence_number - 1,
            EvidenceChain.event_id != event_id,
        ).first()
        if sequence_predecessor is not None:
            logger.warning("CHAIN BREAK at sequence %s for device %s", sequence_number, edge_device_id)
            return False, "INVALID"
        logger.warning(
            f"Chain gap: predecessor hash {previous_hash} for device {edge_device_id} "
            f"not found. Setting status to PENDING."
        )
        return False, "PENDING"
    if len(predecessors) != 1:
        logger.warning("Ambiguous predecessor hash for device %s", edge_device_id)
        return False, "INVALID"

    prev_chain = predecessors[0]

    if _would_create_cycle(db, edge_device_id, current_hash, prev_chain):
        logger.warning("Cyclic evidence chain detected for device %s", edge_device_id)
        return False, "INVALID"

    if prev_chain.chain_status == "PENDING":
        logger.warning(
            f"Chain gap earlier for device {edge_device_id}; predecessor is PENDING."
        )
        return False, "PENDING"
        
    if prev_chain.chain_status == "INVALID":
        logger.warning(
            f"Predecessor {sequence_number - 1} for device {edge_device_id} is INVALID. "
            f"Chain cannot be validated."
        )
        return False, "INVALID"

    # Reject a fork at the point it is introduced.  The already accepted
    # branch remains immutable evidence; the competing branch is not marked
    # trusted merely because it shares a predecessor.
    children = same_source.filter(EvidenceChain.previous_hash == previous_hash).all()
    if any(child.event_id != prev_chain.event_id and child.current_hash != current_hash for child in children):
        logger.warning("Evidence-chain fork detected for device %s", edge_device_id)
        return False, "INVALID"
    return True, "VALID"


def verify_event_integrity(
    evidence_package: EvidencePackage,
    db: Session,
    edge_device_id: str,
    sequence_number: int,
) -> VerificationResponse:
    """
    Run all three verification checks and return a structured result.
    This is called both on ingest and when the dashboard 'verify integrity' button is clicked.
    """
    hash_valid, hash_msg, calculated_hash = verify_hash(evidence_package)
    sig_valid, sig_msg, key_status = verify_signature(evidence_package, db)
    chain_valid, chain_status = verify_chain_continuity(
        db, edge_device_id, sequence_number,
        evidence_package.hash or "",
        evidence_package.previous_hash,
        evidence_package.event_id,
    )

    # Record in server-side chain table
    existing = (
        db.query(EvidenceChain)
        .filter(
            EvidenceChain.edge_device_id == edge_device_id,
            EvidenceChain.event_id == evidence_package.event_id,
        )
        .first()
    )
    if existing is None:
        chain_record = EvidenceChain(
            edge_device_id=edge_device_id,
            sequence_number=sequence_number,
            event_id=evidence_package.event_id,
            previous_hash=evidence_package.previous_hash,
            current_hash=evidence_package.hash or "",
            kid=evidence_package.kid,
            signature=evidence_package.signature or "",
            verified_at=datetime.utcnow(),
            chain_valid=chain_valid,
            chain_status=chain_status,
        )
        db.add(chain_record)
        db.flush()
    else:
        existing.previous_hash = evidence_package.previous_hash
        existing.current_hash = evidence_package.hash or ""
        existing.kid = evidence_package.kid
        existing.signature = evidence_package.signature or ""
        existing.verified_at = datetime.utcnow()
        existing.chain_valid = chain_valid
        existing.chain_status = chain_status

    detail_parts = []
    detail_parts.append(f"HASH: {hash_msg}")
    
    sig_detail = f"{sig_msg}"
    if key_status:
        sig_detail += f" (KEY:{key_status})"
    detail_parts.append(f"SIGNATURE: {sig_detail}")
    
    detail_parts.append(f"CHAIN: {chain_status}")

    logger.info(
        f"Verification for event {evidence_package.event_id}: "
        f"hash={hash_valid} ({hash_msg}), sig={sig_valid}, chain={chain_status}"
    )

    stored_hash = evidence_package.hash or ""
    # If canonicalization failed entirely, fallback to old get_signable_fields for the response object
    if calculated_hash is None:
        calculated_hash = compute_sha256(evidence_package.get_signable_fields())

    return VerificationResponse(
        event_id=evidence_package.event_id,
        hash_valid=hash_valid,
        signature_valid=sig_valid,
        chain_valid=chain_valid,
        chain_status=chain_status,
        detail=" | ".join(detail_parts),
        calculated_hash=calculated_hash,
        stored_hash=stored_hash,
        verified_at=datetime.utcnow(),
    )

def resolve_pending_chains(db: Session, edge_device_id: str, start_sequence_number: int, start_hash: str):
    """
    Iteratively heals PENDING chain gaps going forward.
    Bound: max 1000 records to prevent infinite loops.
    """
    # Import EvidencePackage model here to avoid circular imports if necessary
    from backend.models.orm import EvidencePackage as EvidencePackageModel
    
    MAX_RESOLUTIONS = 1000
    resolutions = 0
    current_hashes = [start_hash]
    
    while current_hashes and resolutions < MAX_RESOLUTIONS:
        current_hash = current_hashes.pop(0)
        next_chains = db.query(EvidenceChain).filter(
            EvidenceChain.edge_device_id == edge_device_id,
            EvidenceChain.previous_hash == current_hash,
            EvidenceChain.chain_status == "PENDING",
        ).all()
        if len(next_chains) > 1:
            for next_chain in next_chains:
                next_chain.chain_status = "INVALID"
                next_chain.chain_valid = False
                next_ep = db.query(EvidencePackageModel).filter(EvidencePackageModel.event_id == next_chain.event_id).first()
                if next_ep:
                    next_ep.chain_status = "INVALID"
                    next_ep.chain_valid = False
                    next_ep.verified_ok = False
            logger.warning("Evidence-chain fork detected while resolving device %s", edge_device_id)
            continue
        for next_chain in next_chains:
            if next_chain.previous_hash == current_hash and next_chain.current_hash != current_hash:
                next_ep = db.query(EvidencePackageModel).filter(EvidencePackageModel.event_id == next_chain.event_id).first()
                if next_ep and next_ep.hash_valid and next_ep.signature_valid:
                    next_chain.chain_status = "VALID"
                    next_chain.chain_valid = True
                    next_ep.chain_status = "VALID"
                    next_ep.chain_valid = True
                    next_ep.verified_ok = True
                    logger.info(f"[Healer] Healed evidence {next_chain.event_id} for device {edge_device_id}")
                    current_hashes.append(next_chain.current_hash)
                else:
                    next_chain.chain_status = "INVALID"
                    next_chain.chain_valid = False
                    if next_ep:
                        next_ep.chain_status = "INVALID"
                        next_ep.chain_valid = False
                        next_ep.verified_ok = False
                    logger.warning(f"[Healer] Evidence {next_chain.event_id} for device {edge_device_id} had crypto failures, marking INVALID")
            else:
                next_chain.chain_status = "INVALID"
                next_chain.chain_valid = False
                next_ep = db.query(EvidencePackageModel).filter(EvidencePackageModel.event_id == next_chain.event_id).first()
                if next_ep:
                    next_ep.chain_status = "INVALID"
                    next_ep.chain_valid = False
                    next_ep.verified_ok = False
                logger.warning(f"[Healer] CHAIN BREAK for device {edge_device_id} during healing")
            resolutions += 1
        
    if resolutions > 0:
        db.flush()
        logger.info(f"[Healer] Finished healing {resolutions} dependent blocks for {edge_device_id}")
