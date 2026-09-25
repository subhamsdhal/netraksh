import numpy as np

def calculate_iou(boxA, boxB):
    """Calculate Intersection over Union for two bounding boxes [x1, y1, x2, y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    interArea = max(0, xB - xA) * max(0, yB - yA)
    if interArea == 0:
        return 0.0

    boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

    iou = interArea / float(boxAArea + boxBArea - interArea)
    return iou

def calculate_cer(reference: str, hypothesis: str) -> float:
    """Calculates Character Error Rate using Levenshtein distance."""
    if not reference:
        return 1.0 if hypothesis else 0.0
    dist = calculate_edit_distance(reference, hypothesis)
    return dist / len(reference)

def calculate_edit_distance(reference: str, hypothesis: str) -> int:
    """Return Levenshtein distance without requiring a native extension."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, reference_char in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_char in enumerate(hypothesis, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (reference_char != hypothesis_char),
            ))
        previous = current
    return previous[-1]

class ANPRMetricsEngine:
    def __init__(self, iou_threshold=0.5):
        self.iou_threshold = iou_threshold

    def evaluate_localization(self, predictions: list, ground_truths: list) -> dict:
        """
        predictions: list of [x1, y1, x2, y2]
        ground_truths: list of [x1, y1, x2, y2]
        """
        if not ground_truths:
            return {"status": "NOT MEASURABLE"}

        tp = 0
        fp = 0
        
        # Simple greedy matching
        matched_gt = set()
        for pred in predictions:
            best_iou = 0.0
            best_gt_idx = -1
            for idx, gt in enumerate(ground_truths):
                if idx in matched_gt:
                    continue
                iou = calculate_iou(pred, gt)
                if iou > best_iou:
                    best_iou = iou
                    best_gt_idx = idx
            
            if best_iou >= self.iou_threshold:
                tp += 1
                matched_gt.add(best_gt_idx)
            else:
                fp += 1
                
        fn = len(ground_truths) - len(matched_gt)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * (precision * recall) / max(precision + recall, 1e-6)
        
        return {
            "status": "EVALUATED",
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "sample_count": len(ground_truths)
        }

    def evaluate_ocr(self, predictions: list, ground_truths: list) -> dict:
        """
        predictions: list of dicts {"raw": str, "normalized": str}
        ground_truths: list of dicts {"raw": str, "normalized": str}
        """
        if not ground_truths:
            return {"status": "NOT MEASURABLE"}

        exact_matches_raw = 0
        exact_matches_norm = 0
        total_cer_raw = 0.0
        total_cer_norm = 0.0

        for pred, gt in zip(predictions, ground_truths):
            # Raw
            if pred["raw"] == gt["raw"]:
                exact_matches_raw += 1
            total_cer_raw += calculate_cer(gt["raw"], pred["raw"])
            
            # Normalized
            if pred["normalized"] == gt["normalized"]:
                exact_matches_norm += 1
            total_cer_norm += calculate_cer(gt["normalized"], pred["normalized"])

        n = len(ground_truths)
        return {
            "status": "EVALUATED",
            "exact_match_raw": exact_matches_raw / n,
            "exact_match_normalized": exact_matches_norm / n,
            "avg_cer_raw": total_cer_raw / n,
            "avg_cer_normalized": total_cer_norm / n,
            "sample_count": n
        }
