import logging
import cv2
import numpy as np
from typing import Optional, Tuple, Dict, Any

from shared.schemas import BoundingBox, TrackData

logger = logging.getLogger(__name__)

# Standard 112x112 layout for ArcFace/MobileFaceNet
# Based on deepinsight/insightface standard points (left eye, right eye, nose, left mouth, right mouth)
STANDARD_LANDMARKS_112 = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041]
], dtype=np.float32)

class FaceAligner:
    """
    Modular face-alignment stage.
    Uses 5-point landmarks if available (from RetinaFace) to perform affine alignment.
    Falls back to a safe centered crop for Haar cascades or missing landmarks.
    """

    def __init__(self, output_size: Tuple[int, int] = (112, 112)):
        self.output_size = output_size
        
    def align(
        self, 
        frame: np.ndarray, 
        bbox: BoundingBox, 
        landmarks: Optional[np.ndarray] = None
    ) -> Dict[str, Any]:
        """
        Aligns the face.
        Returns a dict:
        {
            "aligned_face": np.ndarray (RGB or BGR depending on input),
            "alignment_method": "LANDMARK_ALIGNMENT" | "BBOX_ALIGNMENT",
            "success": bool
        }
        """
        if landmarks is not None and landmarks.shape == (5, 2):
            return self._landmark_alignment(frame, landmarks)
        else:
            return self._bbox_alignment(frame, bbox)
            
    def _landmark_alignment(self, frame: np.ndarray, landmarks: np.ndarray) -> Dict[str, Any]:
        try:
            from skimage import transform as trans
            
            tform = trans.SimilarityTransform()
            tform.estimate(landmarks, STANDARD_LANDMARKS_112)
            M = tform.params[0:2, :]
            
            aligned = cv2.warpAffine(frame, M, self.output_size, borderValue=0.0)
            return {
                "aligned_face": aligned,
                "alignment_method": "LANDMARK_ALIGNMENT",
                "success": True
            }
        except Exception as e:
            logger.debug(f"[FaceAligner] Landmark alignment failed: {e}. Falling back.")
            return {"aligned_face": None, "alignment_method": "LANDMARK_ALIGNMENT", "success": False}

    def _bbox_alignment(self, frame: np.ndarray, bbox: BoundingBox) -> Dict[str, Any]:
        try:
            h, w = frame.shape[:2]
            
            # Safe bounding box bounds
            x1 = max(0, int(bbox.x1))
            y1 = max(0, int(bbox.y1))
            x2 = min(w, int(bbox.x2))
            y2 = min(h, int(bbox.y2))
            
            if x2 <= x1 or y2 <= y1:
                return {"aligned_face": None, "alignment_method": "BBOX_ALIGNMENT", "success": False}
                
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                return {"aligned_face": None, "alignment_method": "BBOX_ALIGNMENT", "success": False}
                
            aligned = cv2.resize(crop, self.output_size)
            return {
                "aligned_face": aligned,
                "alignment_method": "BBOX_ALIGNMENT",
                "success": True
            }
        except Exception as e:
            logger.debug(f"[FaceAligner] Bbox alignment failed: {e}")
            return {"aligned_face": None, "alignment_method": "BBOX_ALIGNMENT", "success": False}
