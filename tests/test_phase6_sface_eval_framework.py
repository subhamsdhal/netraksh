import pytest
import numpy as np

from edge.evaluation.dataset import DatasetProvenance, DatasetValidator
from edge.evaluation.pair_generation import EvaluationPair, PairGenerator
from edge.evaluation.metrics import ThresholdSweeper
from edge.evaluation.promotion import PromotionGate

def create_mock_provenance(approval="PENDING_REVIEW"):
    return DatasetProvenance(
        dataset_id="test_ds_01",
        dataset_name="Mock Border CCTV",
        dataset_version="v1.0",
        source_url_or_source_reference="internal",
        provider_or_owner="NETRAKSH",
        dataset_owner="NETRAKSH",
        data_controller="NETRAKSH_DATA_CONTROLLER",
        download_date="2026-09-14",
        license_name="internal-use",
        license_url="",
        license_verified=True,
        permitted_use="evaluation only",
        commercial_use_status="denied",
        redistribution_status="denied",
        collection_protocol_version="v1.0",
        consent_policy_version="v1.0",
        legal_review_reference="LEGAL-2026-001",
        capture_equipment="CCTV_1080P",
        capture_environment="BORDER_SIMULATION",
        collection_operator="AUTHORIZED_STAFF",
        capture_conditions="DAY_NIGHT_MIX",
        retention_policy="30_DAYS",
        deletion_policy="SECURE_WIPE",
        identity_label_policy="strict",
        ground_truth_type="STRONG_IDENTITY",
        annotation_format="json",
        image_count=5000,
        identity_count=200,
        genuine_pair_availability=True,
        impostor_pair_availability=True,
        condition_metadata_availability=True,
        train_split=False,
        validation_split=True,
        test_split=True,
        hash_algorithm="sha256",
        dataset_hash="fakehash",
        artifact_hash="fakeartifacthash",
        notes="",
        approval_status=approval
    )

def test_01_provenance_schema_validation():
    prov = create_mock_provenance(approval="APPROVED")
    val = DatasetValidator()
    assert val.validate(prov) == "DATASET_APPROVED"

def test_02_dataset_rejection():
    val = DatasetValidator()
    
    # Missing License
    prov = create_mock_provenance(approval="APPROVED")
    prov.license_verified = False
    assert val.validate(prov) == "LICENSE_UNVERIFIED"
    
    # Missing Ground Truth
    prov = create_mock_provenance(approval="APPROVED")
    prov.ground_truth_type = "WEAK_GUESS"
    assert val.validate(prov) == "GROUND_TRUTH_UNAVAILABLE"
    
    # Missing sample counts
    prov = create_mock_provenance(approval="APPROVED")
    prov.identity_count = 0
    assert val.validate(prov) == "INSUFFICIENT_SAMPLE_COUNT"
    
    # Blocked
    prov = create_mock_provenance(approval="BLOCKED")
    assert val.validate(prov) == "DATASET_BLOCKED"

def test_03_duplicate_leakage_detection():
    prov = create_mock_provenance(approval="APPROVED")
    prov.notes = "Warning: possible leakage between splits"
    val = DatasetValidator()
    assert val.validate(prov) == "SPLIT_LEAKAGE_DETECTED"

def test_04_deterministic_pair_generation():
    pg = PairGenerator(seed=42)
    pairs = pg.generate_pairs({}, {})
    assert isinstance(pairs, list)
    assert len(pairs) == 0
    
    # We must explicitly NOT fake data
    assert pg.hash_pairs([]) == "empty"

def test_05_threshold_sweep_correctness():
    sw = ThresholdSweeper(thresholds=np.array([0.1, 0.5, 0.9]))
    # Mock data to test math
    data = [
        {"pair_type": "GENUINE", "score": 0.8},
        {"pair_type": "GENUINE", "score": 0.6},
        {"pair_type": "IMPOSTOR", "score": 0.2},
        {"pair_type": "IMPOSTOR", "score": 0.4}
    ]
    res = sw.evaluate(data)
    assert res["status"] == "EVALUATED"
    
    metrics = res["sweep"]
    assert len(metrics) == 3
    
    # at th=0.5, TP=2, FN=0, TN=2, FP=0
    # FAR = 0, FRR = 0, TAR = 1.0
    th_05 = next(m for m in metrics if np.isclose(m["threshold"], 0.5))
    assert np.isclose(th_05["FAR"], 0.0)
    assert np.isclose(th_05["FRR"], 0.0)
    assert np.isclose(th_05["TAR"], 1.0)
    
    assert res["EER"] == 0.0
    assert np.isclose(res["TAR_at_FAR_1e_3"], 1.0)

def test_06_insufficient_sample_handling():
    sw = ThresholdSweeper()
    res = sw.evaluate([])
    assert res["status"] == "NOT MEASURABLE"

def test_07_promotion_gate():
    gate = PromotionGate()
    
    # Blocked dataset
    res = gate.evaluate("DATASET_BLOCKED", {"status": "NOT MEASURABLE"})
    assert res == "KEEP SFACE OPT-IN"
    
    # Missing metrics
    res = gate.evaluate("DATASET_APPROVED", {"status": "NOT MEASURABLE"})
    assert res == "KEEP SFACE OPT-IN"
    
    # Failed metrics
    res = gate.evaluate("DATASET_APPROVED", {"status": "EVALUATED", "TAR_at_FAR_1e_3": 0.5})
    assert res == "KEEP SFACE OPT-IN"
    
    # Passed metrics
    res = gate.evaluate("DATASET_APPROVED", {"status": "EVALUATED", "TAR_at_FAR_1e_3": 0.95})
    assert res == "PROMOTE SFACE"
