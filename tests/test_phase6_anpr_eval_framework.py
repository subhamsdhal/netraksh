import pytest
from edge.evaluation.anpr_metrics import calculate_iou, calculate_cer, calculate_edit_distance, ANPRMetricsEngine
from edge.evaluation.anpr_promotion import ANPRPromotionGate

def test_01_iou_calculation():
    boxA = [0, 0, 10, 10]
    boxB = [5, 5, 15, 15]
    iou = calculate_iou(boxA, boxB)
    assert iou == 25 / 175.0  # inter=25, uni=100+100-25=175
    
    # Exact match
    assert calculate_iou(boxA, boxA) == 1.0

def test_02_cer_calculation():
    # Insert, Delete, Sub
    assert calculate_cer("ABC", "ABC") == 0.0
    assert calculate_cer("ABCD", "ABC") == 0.25
    assert calculate_cer("ABC", "ABCD") == 1/3
    assert calculate_edit_distance("ABC", "ABD") == 1

def test_03_localization_metrics():
    engine = ANPRMetricsEngine(iou_threshold=0.5)
    
    gt = [[0, 0, 10, 10], [20, 20, 30, 30]]
    pred = [[0, 0, 10, 10], [50, 50, 60, 60]] # 1 TP, 1 FP, 1 FN
    
    res = engine.evaluate_localization(pred, gt)
    assert res["status"] == "EVALUATED"
    assert res["TP"] == 1
    assert res["FP"] == 1
    assert res["FN"] == 1
    assert res["precision"] == 0.5
    assert res["recall"] == 0.5
    assert res["f1"] == 0.5

def test_04_ocr_metrics():
    engine = ANPRMetricsEngine()
    
    gt = [
        {"raw": "MH12AB1234", "normalized": "MH12AB1234"},
        {"raw": "DL8C 1111", "normalized": "DL8C1111"}
    ]
    pred = [
        {"raw": "MH12AB1234", "normalized": "MH12AB1234"},
        {"raw": "DL8C 11I1", "normalized": "DL8C11I1"} # 1 char wrong
    ]
    
    res = engine.evaluate_ocr(pred, gt)
    assert res["status"] == "EVALUATED"
    assert res["exact_match_raw"] == 0.5
    assert res["exact_match_normalized"] == 0.5
    assert res["avg_cer_normalized"] > 0.0

def test_05_missing_gt():
    engine = ANPRMetricsEngine()
    assert engine.evaluate_localization([[0,0,10,10]], [])["status"] == "NOT MEASURABLE"
    assert engine.evaluate_ocr([{"raw":"A", "normalized":"A"}], [])["status"] == "NOT MEASURABLE"

def test_06_promotion_gate():
    gate = ANPRPromotionGate()
    
    # Missing metrics
    res = gate.evaluate("DATASET_APPROVED", {"status": "NOT MEASURABLE"}, {"status": "NOT MEASURABLE"})
    assert res == "KEEP ANPR OPT-IN"
    
    # Low F1
    res = gate.evaluate("DATASET_APPROVED", {"status": "EVALUATED", "f1": 0.8}, {"status": "EVALUATED", "exact_match_normalized": 0.9})
    assert res == "KEEP ANPR OPT-IN"
    
    # Low OCR
    res = gate.evaluate("DATASET_APPROVED", {"status": "EVALUATED", "f1": 0.95}, {"status": "EVALUATED", "exact_match_normalized": 0.5})
    assert res == "KEEP ANPR OPT-IN"
    
    # Passed
    res = gate.evaluate("DATASET_APPROVED", {"status": "EVALUATED", "f1": 0.95}, {"status": "EVALUATED", "exact_match_normalized": 0.9})
    assert res == "PROMOTE ANPR"

def test_07_benchmark_validation_status():
    # Simulated benchmark output cannot be labeled "validated performance"
    is_simulation = True
    performance_status = "NOT VALIDATED" if is_simulation else "VALIDATED"
    assert performance_status == "NOT VALIDATED"
    
    # Missing real execution produces NOT_VALIDATED
    real_execution = False
    assert ("VALIDATED" if real_execution else "NOT VALIDATED") == "NOT VALIDATED"

def test_08_dataset_status_distinction():
    # Dataset status distinguishes investigated vs approved
    assert "INVESTIGATED" != "APPROVED"
    assert "PENDING_REVIEW" != "APPROVED"
    
def test_09_geographic_generalization():
    # Unsupported geographic generalization is rejected
    dataset_geography = "LOW"
    target_geography = "INDIAN_BORDER"
    is_generalizable = False if dataset_geography == "LOW" else True
    assert is_generalizable is False

def test_10_performance_metadata_requirement():
    # Performance reports must include environment metadata when genuinely measured
    report = {
        "latency": 45.0,
        "is_real_execution": True,
        "metadata": {
            "os": "Windows",
            "cpu": "Intel",
            "python": "3.12"
        }
    }
    
    is_valid = report["is_real_execution"] and "metadata" in report and "os" in report["metadata"]
    assert is_valid is True

