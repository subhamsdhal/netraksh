from dataclasses import dataclass
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

@dataclass
class DatasetProvenance:
    dataset_id: str
    dataset_name: str
    dataset_version: str
    source_url_or_source_reference: str
    provider_or_owner: str
    dataset_owner: str
    data_controller: str
    download_date: str
    license_name: str
    license_url: str
    license_verified: bool
    permitted_use: str
    commercial_use_status: str
    redistribution_status: str
    collection_protocol_version: str
    consent_policy_version: str
    legal_review_reference: str
    capture_equipment: str
    capture_environment: str
    collection_operator: str
    capture_conditions: str
    retention_policy: str
    deletion_policy: str
    identity_label_policy: str
    ground_truth_type: str
    annotation_format: str
    image_count: int
    identity_count: int
    genuine_pair_availability: bool
    impostor_pair_availability: bool
    condition_metadata_availability: bool
    train_split: bool
    validation_split: bool
    test_split: bool
    hash_algorithm: str
    dataset_hash: str
    artifact_hash: str
    notes: str
    approval_status: str  # PENDING_REVIEW, APPROVED, REJECTED, BLOCKED


class DatasetValidator:
    """Validates the schema and completeness of a dataset provenance record."""

    ALLOWED_STATUSES = {"PENDING_REVIEW", "APPROVED", "REJECTED", "BLOCKED"}

    def validate(self, prov: DatasetProvenance) -> str:
        """
        Returns a status string.
        """
        if prov.approval_status not in self.ALLOWED_STATUSES:
            return "INVALID_DATASET"
        
        if prov.approval_status in ("REJECTED", "BLOCKED"):
            return "DATASET_BLOCKED"

        if not prov.dataset_hash or not prov.artifact_hash:
            return "INVALID_DATASET"

        if not prov.license_verified:
            return "LICENSE_UNVERIFIED"

        if prov.image_count <= 0 or prov.identity_count <= 0:
            return "INSUFFICIENT_SAMPLE_COUNT"

        if prov.ground_truth_type not in ("EXPLICIT_IDENTITY", "STRONG_IDENTITY"):
            return "GROUND_TRUTH_UNAVAILABLE"
            
        if not prov.genuine_pair_availability or not prov.impostor_pair_availability:
            return "PAIR_GENERATION_UNAVAILABLE"
            
        if prov.approval_status == "PENDING_REVIEW":
            return "DATASET_BLOCKED"
            
        # Simulating leakage check conceptually.
        if "leakage" in prov.notes.lower() or "duplicate" in prov.notes.lower():
            return "SPLIT_LEAKAGE_DETECTED"
            
        return "DATASET_APPROVED"
