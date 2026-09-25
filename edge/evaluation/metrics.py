import numpy as np
from typing import List, Dict, Tuple, Optional

class ThresholdSweeper:
    """Calculates evaluation metrics across a configurable sweep of thresholds."""
    
    def __init__(self, thresholds: Optional[np.ndarray] = None):
        if thresholds is None:
            self.thresholds = np.linspace(-1.0, 1.0, 201)
        else:
            self.thresholds = thresholds

    def evaluate(self, pairs_with_scores: List[Dict]) -> Dict:
        """
        pairs_with_scores: [{"pair_type": "GENUINE"/"IMPOSTOR", "score": float}]
        Returns explicit "NOT MEASURABLE" if data is empty.
        """
        if not pairs_with_scores:
            return {"status": "NOT MEASURABLE"}

        metrics_over_threshold = []
        for th in self.thresholds:
            tp = tn = fp = fn = 0
            for p in pairs_with_scores:
                is_match = p["score"] >= th
                if p["pair_type"] == "GENUINE":
                    if is_match: tp += 1
                    else: fn += 1
                else:
                    if is_match: fp += 1
                    else: tn += 1
                    
            far = fp / max(fp + tn, 1)
            frr = fn / max(fn + tp, 1)
            tar = tp / max(tp + fn, 1)
            metrics_over_threshold.append({
                "threshold": float(th),
                "FAR": float(far),
                "FRR": float(frr),
                "TAR": float(tar)
            })

        # Calculate EER
        eer = None
        min_diff = float("inf")
        eer_threshold = None
        for m in metrics_over_threshold:
            diff = abs(m["FAR"] - m["FRR"])
            if diff < min_diff:
                min_diff = diff
                eer = (m["FAR"] + m["FRR"]) / 2
                eer_threshold = m["threshold"]

        # Calculate TAR @ FAR variants
        def get_tar_at_far(target_far):
            best_tar = 0.0
            for m in metrics_over_threshold:
                if m["FAR"] <= target_far and m["TAR"] > best_tar:
                    best_tar = m["TAR"]
            return best_tar

        return {
            "status": "EVALUATED",
            "EER": eer,
            "EER_threshold": eer_threshold,
            "TAR_at_FAR_1e_2": get_tar_at_far(0.01),
            "TAR_at_FAR_1e_3": get_tar_at_far(0.001),
            "TAR_at_FAR_1e_4": get_tar_at_far(0.0001),
            "sweep": metrics_over_threshold
        }
