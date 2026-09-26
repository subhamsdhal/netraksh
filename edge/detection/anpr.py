import logging
import cv2
import numpy as np
import os
from typing import List, Optional, Dict, Tuple
from collections import defaultdict, deque
import time
import re
from abc import ABC, abstractmethod
from itertools import product

from shared.constants import DetectionClass, EventType
from shared.schemas import TrackData, BoundingBox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

class PlateCrop:
    def __init__(self, crop: np.ndarray, bbox: BoundingBox, track_id: int, confidence: Optional[float] = None, method: str = "heuristic", quadrilateral: Optional[List[Tuple[float, float]]] = None):
        self.crop = crop
        self.bbox = bbox
        self.track_id = track_id
        self.confidence = confidence
        self.method = method
        self.quadrilateral = quadrilateral

class OCRResult:
    def __init__(self, text: str, confidence: float, processing_method: str = "enhanced"):
        self.text = text
        self.confidence = confidence
        self.processing_method = processing_method
        self.timestamp = time.time()

# ---------------------------------------------------------------------------
# Plate Localizer
# ---------------------------------------------------------------------------

class PlateLocalizer(ABC):
    @abstractmethod
    def locate(self, track: TrackData, frame: np.ndarray) -> List[PlateCrop]:
        pass

class HeuristicPlateLocalizer(PlateLocalizer):
    def locate(self, track: TrackData, frame: np.ndarray) -> List[PlateCrop]:
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = int(track.bbox.x1), int(track.bbox.y1), int(track.bbox.x2), int(track.bbox.y2)
        h = y2 - y1
        w = x2 - x1
        
        # Lower-middle region of vehicle
        plate_y1 = max(0, y1 + int(h * 0.55))
        plate_y2 = min(fh, y2)
        plate_x1 = max(0, x1 + int(w * 0.1))
        plate_x2 = min(fw, x2 - int(w * 0.1))
        
        if plate_y2 <= plate_y1 or plate_x2 <= plate_x1:
            return []
            
        crop = frame[plate_y1:plate_y2, plate_x1:plate_x2]
        bbox = BoundingBox(x1=plate_x1, y1=plate_y1, x2=plate_x2, y2=plate_y2)
        
        return [PlateCrop(crop=crop, bbox=bbox, track_id=track.track_id, confidence=None, method="heuristic")]

class LPD_YuNetPlateLocalizer(PlateLocalizer):
    def __init__(self, model_path="lpd_yunet.onnx", conf_threshold=0.8, nms_threshold=0.3, keep_top_k=5):
        self.model_path = model_path
        self.input_size = (320, 240) # (w, h)
        self.confidence_threshold = conf_threshold
        self.nms_threshold = nms_threshold
        self.keep_top_k = keep_top_k
        self.session = None
        
        self.output_names = ['loc', 'conf', 'iou']
        self.min_sizes = [[10, 16, 24], [32, 48], [64, 96], [128, 192, 256]]
        self.steps = [8, 16, 32, 64]
        self.variance = [0.1, 0.2]
        
        self._init_session()
        if self.session is not None:
            self._priorGen()

    def _init_session(self):
        if not os.path.exists(self.model_path):
            logger.warning(f"[ANPR] LPD_YuNet model not found at {self.model_path}")
            return
            
        try:
            import onnxruntime as ort
            self.session = ort.InferenceSession(self.model_path, providers=['CPUExecutionProvider'])
            logger.info("[ANPR] LPD_YuNet ONNX session initialized.")
        except Exception as e:
            logger.error(f"[ANPR] LPD_YuNet session init failed: {e}")
            self.session = None

    def _priorGen(self):
        w, h = self.input_size
        feature_map_2th = [int(int((h + 1) / 2) / 2),
                           int(int((w + 1) / 2) / 2)]
        feature_map_3th = [int(feature_map_2th[0] / 2),
                           int(feature_map_2th[1] / 2)]
        feature_map_4th = [int(feature_map_3th[0] / 2),
                           int(feature_map_3th[1] / 2)]
        feature_map_5th = [int(feature_map_4th[0] / 2),
                           int(feature_map_4th[1] / 2)]
        feature_map_6th = [int(feature_map_5th[0] / 2),
                           int(feature_map_5th[1] / 2)]

        feature_maps = [feature_map_3th, feature_map_4th,
                        feature_map_5th, feature_map_6th]

        priors = []
        for k, f in enumerate(feature_maps):
            min_sizes = self.min_sizes[k]
            for i, j in product(range(f[0]), range(f[1])): # i->h, j->w
                for min_size in min_sizes:
                    s_kx = min_size / w
                    s_ky = min_size / h
                    cx = (j + 0.5) * self.steps[k] / w
                    cy = (i + 0.5) * self.steps[k] / h
                    priors.append([cx, cy, s_kx, s_ky])
        self.priors = np.array(priors, dtype=np.float32)

    def _decode(self, blob):
        loc, conf, iou = blob
        cls_scores = conf[:, 1]
        iou_scores = iou[:, 0]
        
        _idx = np.where(iou_scores < 0.)
        iou_scores[_idx] = 0.
        _idx = np.where(iou_scores > 1.)
        iou_scores[_idx] = 1.
        scores = np.sqrt(cls_scores * iou_scores)
        scores = scores[:, np.newaxis]

        scale = np.array(self.input_size)

        # 4 corners corresponding to loc 4:6, 6:8, 10:12, 12:14
        bboxes = np.hstack((
            (self.priors[:, 0:2] + loc[:,  4: 6] * self.variance[0] * self.priors[:, 2:4]) * scale,
            (self.priors[:, 0:2] + loc[:,  6: 8] * self.variance[0] * self.priors[:, 2:4]) * scale,
            (self.priors[:, 0:2] + loc[:, 10:12] * self.variance[0] * self.priors[:, 2:4]) * scale,
            (self.priors[:, 0:2] + loc[:, 12:14] * self.variance[0] * self.priors[:, 2:4]) * scale
        ))

        dets = np.hstack((bboxes, scores))
        return dets

    def locate(self, track: TrackData, frame: np.ndarray) -> List[PlateCrop]:
        if self.session is None:
            return []
            
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = int(track.bbox.x1), int(track.bbox.y1), int(track.bbox.x2), int(track.bbox.y2)
        
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(fw, x2), min(fh, y2)
        
        if y2 <= y1 or x2 <= x1:
            return []
            
        vehicle_crop = frame[y1:y2, x1:x2]
        if vehicle_crop.size == 0:
            return []
            
        cw, ch = (x2 - x1), (y2 - y1)
        
        input_blob = cv2.dnn.blobFromImage(vehicle_crop, size=self.input_size)
        
        try:
            loc, conf, iou = self.session.run(self.output_names, {"input": input_blob})
        except Exception as e:
            logger.error(f"[ANPR] ONNXRuntime inference failed: {e}")
            return []
            
        # Published LPD-YuNet artifacts exist both with and without an
        # explicit batch dimension.  Normalise either contract to [N, C].
        blob = tuple(output[0] if output.ndim == 3 else output for output in (loc, conf, iou))
        dets = self._decode(blob)
        
        # Following exact OpenCV Zoo reference implementation NMS logic
        keepIdx = cv2.dnn.NMSBoxes(
            bboxes=dets[:, 0:4].tolist(),
            scores=dets[:, -1].tolist(),
            score_threshold=self.confidence_threshold,
            nms_threshold=self.nms_threshold,
            top_k=5000
        )
        
        if len(keepIdx) == 0:
            return []
            
        if isinstance(keepIdx, tuple):
            keepIdx = list(keepIdx)
            
        # In newer OpenCV, NMSBoxes returns a tuple or 1D array, sometimes 2D array [[idx]].
        keepIdx = np.array(keepIdx).flatten()
            
        dets = dets[keepIdx]
        dets = dets[:self.keep_top_k]
        
        results = []
        for det in dets:
            pts = det[0:8].reshape(4, 2)
            score = float(det[-1])
            
            # Scale coordinates back to original vehicle crop size
            pts[:, 0] = pts[:, 0] * (cw / self.input_size[0])
            pts[:, 1] = pts[:, 1] * (ch / self.input_size[1])
            
            # Map back to original frame coordinates
            pts[:, 0] += x1
            pts[:, 1] += y1
            
            # Derive axis-aligned bounding box from quadrilateral for fallback
            p_x = pts[:, 0]
            p_y = pts[:, 1]
            box_x1, box_y1 = max(0, int(np.min(p_x))), max(0, int(np.min(p_y)))
            box_x2, box_y2 = min(fw, int(np.max(p_x))), min(fh, int(np.max(p_y)))
            
            # Handle out-of-bounds or degenerate
            if box_x2 <= box_x1 or box_y2 <= box_y1:
                continue
                
            plate_frame_crop = frame[box_y1:box_y2, box_x1:box_x2]
            
            quad = [(float(pt[0]), float(pt[1])) for pt in pts]
            
            results.append(PlateCrop(
                crop=plate_frame_crop,
                bbox=BoundingBox(x1=box_x1, y1=box_y1, x2=box_x2, y2=box_y2),
                track_id=track.track_id,
                confidence=score,
                method="lpd_yunet",
                quadrilateral=quad
            ))
            
        return results

# ---------------------------------------------------------------------------
# Plate Quality Filter
# ---------------------------------------------------------------------------

class PlateQualityFilter:
    def __init__(self, min_width=30, min_height=10, max_aspect_ratio=6.0, min_aspect_ratio=1.0, min_contrast=15.0):
        self.min_width = min_width
        self.min_height = min_height
        self.max_aspect_ratio = max_aspect_ratio
        self.min_aspect_ratio = min_aspect_ratio
        self.min_contrast = min_contrast

    def check(self, crop: np.ndarray, quad: Optional[List[Tuple[float, float]]] = None) -> Tuple[bool, Optional[str]]:
        if crop.size == 0:
            return False, "INVALID_CROP"
            
        h, w = crop.shape[:2]
        
        # If we have a quadrilateral, compute exact area and bounding aspect ratio
        if quad:
            pts = np.array(quad, dtype=np.float32)
            # Shoelace formula for area
            x = pts[:, 0]
            y = pts[:, 1]
            area = 0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1)))

            # Aspect ratio of the quadrilateral based on edge lengths
            width_top = np.linalg.norm(pts[1] - pts[0])
            width_bottom = np.linalg.norm(pts[2] - pts[3])
            height_left = np.linalg.norm(pts[3] - pts[0])
            height_right = np.linalg.norm(pts[2] - pts[1])
            avg_w = (width_top + width_bottom) / 2.0
            avg_h = (height_left + height_right) / 2.0

            if avg_h == 0 or avg_w == 0:
                return False, "DEGENERATE_QUADRILATERAL"
            if area < (self.min_width * self.min_height * 0.5):
                return False, "LOW_RESOLUTION"
                
            aspect_ratio = avg_w / avg_h
        else:
            if w < self.min_width or h < self.min_height:
                return False, "LOW_RESOLUTION"
            aspect_ratio = w / h
            
        if aspect_ratio < self.min_aspect_ratio or aspect_ratio > self.max_aspect_ratio:
            return False, "EXTREME_ASPECT_RATIO"
            
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        contrast = np.std(gray)
        if contrast < self.min_contrast:
            return False, "LOW_CONTRAST"
            
        return True, None

# ---------------------------------------------------------------------------
# Preprocessor
# ---------------------------------------------------------------------------

class OCRPreprocessor:
    @staticmethod
    def process(crop: np.ndarray, quad: Optional[List[Tuple[float, float]]] = None, frame: Optional[np.ndarray] = None) -> np.ndarray:
        
        image_to_process = crop
        
        # If quadrilateral is provided and frame is provided, we can warp it directly from the original frame
        # For now, if quad is provided, we can warp from the already cropped `crop` image if we map coordinates.
        if quad and crop is not None:
            # Map quadrilateral points relative to the crop
            # The crop is axis aligned box from (box_x1, box_y1)
            p_x = [p[0] for p in quad]
            p_y = [p[1] for p in quad]
            box_x1, box_y1 = min(p_x), min(p_y)
            
            local_pts = np.array([
                [quad[0][0] - box_x1, quad[0][1] - box_y1],
                [quad[1][0] - box_x1, quad[1][1] - box_y1],
                [quad[2][0] - box_x1, quad[2][1] - box_y1],
                [quad[3][0] - box_x1, quad[3][1] - box_y1]
            ], dtype=np.float32)
            
            width_top = np.linalg.norm(local_pts[1] - local_pts[0])
            width_bottom = np.linalg.norm(local_pts[2] - local_pts[3])
            max_w = max(int(width_top), int(width_bottom))
            
            height_left = np.linalg.norm(local_pts[3] - local_pts[0])
            height_right = np.linalg.norm(local_pts[2] - local_pts[1])
            max_h = max(int(height_left), int(height_right))
            
            dst_pts = np.array([
                [0, 0],
                [max_w - 1, 0],
                [max_w - 1, max_h - 1],
                [0, max_h - 1]
            ], dtype=np.float32)
            
            if max_w > 0 and max_h > 0:
                M = cv2.getPerspectiveTransform(local_pts, dst_pts)
                warped = cv2.warpPerspective(crop, M, (max_w, max_h))
                image_to_process = warped

        gray = cv2.cvtColor(image_to_process, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        enhanced = clahe.apply(gray)
        denoised = cv2.bilateralFilter(enhanced, 9, 75, 75)
        _, thresh = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

# ---------------------------------------------------------------------------
# OCR Engine Wrapper
# ---------------------------------------------------------------------------

class OCREngine(ABC):
    @abstractmethod
    def read(self, image: np.ndarray) -> Optional[OCRResult]:
        pass

class EasyOCREngine(OCREngine):
    def __init__(self, languages: List[str] = None):
        self._languages = languages or ["en"]
        self._reader = None
        self._attempted = False
        
    def _init_reader(self):
        if self._attempted:
            return
        self._attempted = True
        try:
            import easyocr
            self._reader = easyocr.Reader(self._languages, gpu=False, verbose=False)
            logger.info("[ANPR] EasyOCREngine initialized")
        except Exception as exc:
            logger.error(f"[ANPR] EasyOCR init failed: {exc}")

    def read(self, image: np.ndarray) -> Optional[OCRResult]:
        self._init_reader()
        if self._reader is None:
            return None
            
        try:
            results = self._reader.readtext(image, detail=1, paragraph=False)
            if not results:
                return None
                
            best = max(results, key=lambda r: r[2])
            text = best[1].strip()
            conf = float(best[2])
            
            return OCRResult(text=text, confidence=conf, processing_method="easyocr+clahe")
        except Exception as exc:
            logger.debug(f"[ANPR] OCR failed: {exc}")
            return None

# ---------------------------------------------------------------------------
# Plate Normalizer
# ---------------------------------------------------------------------------

class PlateNormalizer:
    _compact = re.compile(r"^[A-Z0-9]{4,12}$")

    @staticmethod
    def normalize(raw_text: str) -> str:
        text = str(raw_text or "").upper()
        text = text.replace(" ", "").replace("-", "").replace(".", "")
        return re.sub(r"[^A-Z0-9]", "", text)

    @classmethod
    def validation_status(cls, raw_text: str, confidence: float = 0.0) -> str:
        text = cls.normalize(raw_text)
        if not text or len(text) < 4 or not cls._compact.fullmatch(text):
            return "INVALID"
        if confidence < float(os.environ.get("ANPR_OCR_MIN_CONFIDENCE", "0.55")):
            return "LOW_CONFIDENCE"
        return "VALID" if len(text) >= 7 else "PLAUSIBLE"

# ---------------------------------------------------------------------------
# Temporal Fusion
# ---------------------------------------------------------------------------

class TemporalOCRFusion:
    def __init__(self, max_history=10, confirm_threshold=2):
        self.history: Dict[int, deque] = defaultdict(lambda: deque(maxlen=max_history))
        self.confirm_threshold = confirm_threshold
        
    def add_observation(self, track_id: int, result: OCRResult) -> dict:
        self.history[track_id].append(result)
        
        obs_list = self.history[track_id]
        observations_count = len(obs_list)
        
        freq = defaultdict(float)
        for obs in obs_list:
            norm_text = PlateNormalizer.normalize(obs.text)
            freq[norm_text] += obs.confidence
            
        if not freq:
            return {"fusion_state": "NO_VALID_READ", "text": None, "raw_text": None, "count": 0, "conf": 0.0}
            
        best_text, best_score = max(freq.items(), key=lambda item: item[1])
        raw_count = sum(1 for obs in obs_list if PlateNormalizer.normalize(obs.text) == best_text)
        
        best_obs = [obs for obs in obs_list if PlateNormalizer.normalize(obs.text) == best_text]
        avg_conf = sum(o.confidence for o in best_obs) / len(best_obs) if best_obs else 0.0
        best_conf = max((o.confidence for o in best_obs), default=0.0)
        
        if raw_count >= self.confirm_threshold:
            state = "CONFIRMED"
        elif len(freq) > 3 and raw_count == 1:
            state = "UNSTABLE"
        else:
            state = "TENTATIVE"
            
        return {
            "fusion_state": state,
            "text": best_text,
            "raw_text": best_obs[-1].text if best_obs else best_text,
            "count": observations_count,
            "conf": avg_conf,
            "best_conf": best_conf
        }
        
    def cleanup_track(self, track_id: int):
        self.history.pop(track_id, None)

# ---------------------------------------------------------------------------
# Watchlist Interface
# ---------------------------------------------------------------------------

class PlateWatchlist:
    """Explicit edge-configured plate watchlist; empty means disabled."""
    def __init__(self):
        configured = os.environ.get("ANPR_WATCHLIST_PLATES", "")
        self._plates = {
            PlateNormalizer.normalize(value)
            for value in configured.split(",") if PlateNormalizer.normalize(value)
        }

    def match(self, normalized_plate: str) -> Optional[dict]:
        plate = PlateNormalizer.normalize(normalized_plate)
        return {"normalized_plate": plate, "source": "edge_config"} if plate in self._plates else None

# ---------------------------------------------------------------------------
# Enhanced ANPR Module
# ---------------------------------------------------------------------------

class EnhancedANPRModule:
    def __init__(self, engine: str = "lpd_yunet", model_path: str = "lpd_yunet.onnx"):
        if not os.path.isabs(model_path):
            repo_model = os.path.join(os.path.dirname(__file__), "..", "..", model_path)
            if os.path.exists(repo_model):
                model_path = os.path.abspath(repo_model)
        if engine == "lpd_yunet":
            self.localizer = LPD_YuNetPlateLocalizer(model_path=model_path)
        else:
            self.localizer = HeuristicPlateLocalizer()
            
        self.engine = engine
        self.quality_filter = PlateQualityFilter()
        constrained = os.environ.get("EDGE_CONSTRAINED_CLOUD", "false").lower() == "true"
        self.ocr_backend = os.environ.get(
            "ANPR_OCR_BACKEND", "disabled" if constrained else "easyocr"
        ).lower()
        # In constrained cloud mode there is intentionally no OCR engine.
        # Local/full installations retain lazy EasyOCR loading on first real
        # plate crop; no model is imported merely by constructing the pipeline.
        self.ocr_engine = EasyOCREngine() if self.ocr_backend == "easyocr" else None
        if self.ocr_engine is None:
            logger.info("[ANPR] OCR unavailable by configured constrained-cloud policy; localization remains active")
        self.fusion = TemporalOCRFusion()
        self.watchlist = PlateWatchlist()
        
    def process(self, track: TrackData, frame: np.ndarray) -> dict:
        result = {
            'rule': 'anpr_enhanced',
            'severity': 'LOW',
            'plate_text': None,
            'raw_plate_text': None,
            'normalized_plate_text': None,
            'plate_confidence': None,
            'localization_confidence': None,
            'ocr_confidence': None,
            'observations_count': 0,
            'processing_method': None,
            'fusion_state': 'NO_VALID_READ',
            'validation_status': 'INVALID',
            'watchlist_match': None,
        }
        
        crops = self.localizer.locate(track, frame)
        if not crops:
            return result
            
        crop_data = crops[0]
        result['localization_confidence'] = crop_data.confidence
        
        ok, reason = self.quality_filter.check(crop_data.crop, crop_data.quadrilateral)
        if not ok:
            result['processing_method'] = f'PLATE_REJECTED_{reason}'
            return result
            
        processed_img = OCRPreprocessor.process(crop_data.crop, quad=crop_data.quadrilateral)
        
        if self.ocr_engine is None:
            result['processing_method'] = f'{crop_data.method}+OCR_UNAVAILABLE'
            result['validation_status'] = 'OCR_UNAVAILABLE'
            return result

        ocr_res = self.ocr_engine.read(processed_img)
        if not ocr_res:
            return result
        min_confidence = float(os.environ.get("ANPR_OCR_MIN_CONFIDENCE", "0.55"))
        if ocr_res.confidence < min_confidence:
            result['processing_method'] = f'{ocr_res.processing_method}+REJECTED_LOW_CONFIDENCE'
            result['ocr_confidence'] = ocr_res.confidence
            result['validation_status'] = 'LOW_CONFIDENCE'
            return result
            
        fusion_res = self.fusion.add_observation(track.track_id, ocr_res)
        
        result['fusion_state'] = fusion_res['fusion_state']
        result['plate_text'] = fusion_res['text']
        result['raw_plate_text'] = fusion_res['raw_text']
        result['normalized_plate_text'] = fusion_res['text']
        result['plate_confidence'] = fusion_res['conf']
        result['ocr_confidence'] = ocr_res.confidence
        result['observations_count'] = fusion_res['count']
        result['processing_method'] = ocr_res.processing_method
        result['validation_status'] = PlateNormalizer.validation_status(
            fusion_res['text'], fusion_res.get('best_conf', fusion_res['conf'])
        )
        
        if result['fusion_state'] == 'CONFIRMED' and result['normalized_plate_text'] and result['validation_status'] in ('VALID', 'PLAUSIBLE'):
            match = self.watchlist.match(result['normalized_plate_text'])
            if match:
                result['severity'] = 'CRITICAL'
                result['watchlist_match'] = match
                
        return result
        
    def cleanup_track(self, track_id: int):
        self.fusion.cleanup_track(track_id)
