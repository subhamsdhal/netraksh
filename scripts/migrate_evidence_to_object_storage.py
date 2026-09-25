import os
import sys
import logging
import hashlib
from datetime import datetime

# Adjust path to import backend modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.database.session import SessionLocal
from backend.models.orm import Event
from backend.services.evidence_storage import get_evidence_storage
from backend.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_evidence(dry_run: bool = True):
    """
    Idempotent migration script to move existing local evidence to object storage
    and populate the new WP-3.3 storage metadata fields.

    Run with --dry-run (default) to audit without writing.
    Run with --commit to actually upload and update the database.

    Source files are NEVER deleted by this script.
    """
    logger.info(f"Starting evidence migration. Dry run: {dry_run}")
    db = SessionLocal()
    storage = get_evidence_storage()

    # Migrate events that have no binary object yet.
    # The ORM default for storage_status is 'CREATED' (not NULL), so we must
    # include both NULL (pre-migration rows from before the model change) and
    # 'CREATED' (rows inserted after the WP-3.3 model change but before any upload).
    from sqlalchemy import or_
    unmigrated_events = (
        db.query(Event)
        .filter(or_(Event.storage_status == None, Event.storage_status == "CREATED"))
        .all()
    )
    logger.info(f"Found {len(unmigrated_events)} events to migrate (status NULL or CREATED).")
    
    migrated_count = 0
    missing_count = 0
    failed_count = 0
    
    for event in unmigrated_events:
        if not event.evidence_clip_ref:
            logger.info(f"Event {event.id} has no evidence_clip_ref. Skipping.")
            continue
            
        local_path = event.evidence_clip_ref
        
        # In a real deployed setup, local_path might just be the path where clips were saved.
        # We need to resolve it relative to EVIDENCE_CLIPS_DIR if it's relative.
        if not os.path.isabs(local_path):
            local_path = os.path.join(settings.EVIDENCE_CLIPS_DIR, local_path)
            
        if not os.path.exists(local_path):
            logger.warning(f"File not found for event {event.id}: {local_path}")
            if not dry_run:
                event.storage_status = "MISSING"
                event.storage_provider = "local"
                db.commit()
            missing_count += 1
            continue
            
        try:
            with open(local_path, "rb") as f:
                binary_data = f.read()

            content_hash = hashlib.sha256(binary_data).hexdigest()
            content_size = len(binary_data)

            # If an existing content_hash is stored, verify it matches before overwriting.
            # A mismatch indicates either a hash computed with different bytes, or corruption.
            if event.content_hash and event.content_hash != content_hash:
                logger.error(
                    f"Event {event.id}: stored content_hash {event.content_hash[:12]}... "
                    f"does not match computed hash {content_hash[:12]}... — SKIPPING (investigate manually)."
                )
                failed_count += 1
                continue

            date_str = event.timestamp.strftime("%Y%m%d") if event.timestamp else "unknown"
            ext = ".jpg.enc" if local_path.endswith(".enc") else ".jpg"
            object_key = f"evidence/{event.camera_id}/{date_str}/{event.id}{ext}"

            logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Migrating event {event.id} -> {object_key} (hash: {content_hash[:12]}...)")

            if not dry_run:
                storage.put_object(object_key, binary_data, content_type="application/octet-stream")
                event.object_key = object_key
                event.storage_provider = settings.OBJECT_STORAGE_PROVIDER or "local"
                event.storage_status = "AVAILABLE"
                event.content_hash = content_hash
                event.content_size = content_size
                event.uploaded_at = datetime.utcnow()
                db.commit()

            migrated_count += 1
            
        except Exception as exc:
            logger.error(f"Failed to migrate event {event.id}: {exc}")
            failed_count += 1
            
    logger.info("Migration complete.")
    logger.info(f"Total processed: {len(unmigrated_events)}")
    logger.info(f"Migrated: {migrated_count}")
    logger.info(f"Missing files: {missing_count}")
    logger.info(f"Failed: {failed_count}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Migrate local evidence files to WP-3.3 Object Storage")
    parser.add_argument("--commit", action="store_true", help="Run without dry_run (actually upload and update DB)")
    args = parser.parse_args()
    
    migrate_evidence(dry_run=not args.commit)
