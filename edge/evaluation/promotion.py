import os
import logging

logger = logging.getLogger(__name__)

class PromotionGate:
    """Evaluates whether SFace meets the strict criteria to become the production default."""
    
    def evaluate(self, dataset_status: str, eval_metrics: dict) -> str:
        """
        Returns one of:
        PROMOTE SFACE
        ENABLE SFACE BY DEFAULT
        KEEP SFACE OPT-IN
        BLOCK SFACE
        """
        # Criteria 1: Approved Dataset
        if dataset_status != "DATASET_APPROVED":
            logger.warning("Promotion Gate: Blocked due to invalid dataset status.")
            return "KEEP SFACE OPT-IN"
            
        # Criteria 2: Metrics Exist
        if eval_metrics.get("status") == "NOT MEASURABLE":
            logger.warning("Promotion Gate: Blocked due to missing metrics.")
            return "KEEP SFACE OPT-IN"
            
        # Criteria 3: Minimum TAR@FAR=1e-3 (Example threshold requirement)
        tar_at_1e_3 = eval_metrics.get("TAR_at_FAR_1e_3", 0.0)
        if tar_at_1e_3 < 0.90:  # Arbitrary threshold representing production readiness
            logger.warning(f"Promotion Gate: Blocked due to insufficient TAR@FAR=1e-3 ({tar_at_1e_3}).")
            return "KEEP SFACE OPT-IN"
            
        # If all gates pass (assuming dataset is fully validated border footage)
        logger.info("Promotion Gate: SFace satisfies all requirements for default promotion.")
        return "PROMOTE SFACE"
