import logging

logger = logging.getLogger(__name__)

class ANPRPromotionGate:
    """Evaluates whether enhanced ANPR meets the strict criteria to become the production default."""
    
    def evaluate(self, dataset_status: str, loc_metrics: dict, ocr_metrics: dict) -> str:
        """
        Returns one of:
        PROMOTE ANPR
        ENABLE ENHANCED ANPR BY DEFAULT
        KEEP ANPR OPT-IN
        BLOCK ANPR ENHANCEMENT
        """
        # Criteria 1: Approved Dataset
        if dataset_status != "DATASET_APPROVED":
            logger.warning("ANPR Promotion Gate: Blocked due to invalid dataset status.")
            return "KEEP ANPR OPT-IN"
            
        # Criteria 2: Metrics Exist
        if loc_metrics.get("status") == "NOT MEASURABLE" or ocr_metrics.get("status") == "NOT MEASURABLE":
            logger.warning("ANPR Promotion Gate: Blocked due to missing metrics.")
            return "KEEP ANPR OPT-IN"
            
        # Criteria 3: Minimum F1 for localization and Exact Match for OCR
        loc_f1 = loc_metrics.get("f1", 0.0)
        ocr_match = ocr_metrics.get("exact_match_normalized", 0.0)
        
        if loc_f1 < 0.90:
            logger.warning(f"ANPR Promotion Gate: Blocked due to insufficient Localization F1 ({loc_f1}).")
            return "KEEP ANPR OPT-IN"
            
        if ocr_match < 0.85:
            logger.warning(f"ANPR Promotion Gate: Blocked due to insufficient OCR Exact Match ({ocr_match}).")
            return "KEEP ANPR OPT-IN"
            
        # If all gates pass
        logger.info("ANPR Promotion Gate: Enhanced ANPR satisfies all requirements for default promotion.")
        return "PROMOTE ANPR"
