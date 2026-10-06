"""
NETRAKSH Edge — Detector Runtime Abstractions
Supports PyTorch (via ultralytics YOLO), ONNX CPU, ONNX CUDA, and TensorRT.
Enforces STRICT fallback semantics.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from shared.constants import DetectionClass, VehicleSubtype
from shared.schemas import BoundingBox, Point, TrackData

logger = logging.getLogger(__name__)

# YOLO class ID mappings (COCO)
_YOLO_CLASS_MAP: Dict[int, DetectionClass] = {
    0: DetectionClass.PERSON,
    2: DetectionClass.VEHICLE,  
    3: DetectionClass.VEHICLE,  
    5: DetectionClass.VEHICLE,  
    7: DetectionClass.VEHICLE,  
}

_YOLO_VEHICLE_SUBTYPE_MAP: Dict[int, VehicleSubtype] = {
    2: VehicleSubtype.CAR,
    3: VehicleSubtype.MOTORCYCLE,
    5: VehicleSubtype.BUS,
    7: VehicleSubtype.TRUCK,
}


class DetectionResult:
    """Normalized output from any detector runtime before tracking."""
    def __init__(self, bbox: BoundingBox, confidence: float, class_id: int):
        self.bbox = bbox
        # Normalise NumPy scalar precision for stable API/telemetry values.
        self.confidence = round(float(confidence), 6)
        self.class_id = class_id


class DetectorRuntime(ABC):
    """Abstract base class for all detector runtimes."""
    def __init__(self, model_path: str):
        self.model_path = model_path
        self._fps_measurements: List[float] = []
        self._last_fps_report = time.time()
        self.last_stage_ms: Dict[str, float] = {}
        self.last_input_shape = None
        self.last_candidate_count = 0
        self.last_threshold_count = 0
        self.last_nms_count = 0

    @abstractmethod
    def load(self) -> None:
        """Initialize the model and warm up the runtime."""
        pass

    @abstractmethod
    def detect(self, frame: np.ndarray, confidence_threshold: float) -> List[DetectionResult]:
        """Perform inference and return normalized DetectionResults."""
        pass

    def get_avg_fps(self) -> float:
        if not self._fps_measurements:
            return 0.0
        return sum(self._fps_measurements) / len(self._fps_measurements)

    def _record_fps(self, elapsed: float) -> None:
        self._fps_measurements.append(1.0 / elapsed if elapsed > 0 else 0)
        if time.time() - self._last_fps_report > 5.0 and self._fps_measurements:
            avg_fps = sum(self._fps_measurements) / len(self._fps_measurements)
            logger.info(f"[{self.__class__.__name__}] Inference FPS (avg last {len(self._fps_measurements)}): {avg_fps:.1f}")
            self._fps_measurements.clear()
            self._last_fps_report = time.time()


class PyTorchRuntime(DetectorRuntime):
    """Uses native Ultralytics PyTorch YOLO model."""
    def __init__(self, model_path: str):
        super().__init__(model_path)
        self._model = None
        self.device = "cuda" if os.environ.get("DETECTOR_RUNTIME") == "pytorch_cuda" else "cpu"

    def load(self) -> None:
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model artifact unavailable: {self.model_path}")
        
        try:
            from ultralytics import YOLO
            import torch
            
            # Hardware check for explicit pytorch_cuda
            if self.device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("STRICT FAILURE: PyTorch CUDA requested but torch.cuda is not available.")

            self._model = YOLO(self.model_path)
            # Warm up
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self._model.predict(dummy, verbose=False, device=self.device)
            logger.info(f"[PyTorchRuntime] Loaded and warmed up on {self.device}")
        except ImportError:
            raise RuntimeError("STRICT FAILURE: PyTorch/Ultralytics not installed.")

    def detect(self, frame: np.ndarray, confidence_threshold: float) -> List[DetectionResult]:
        if self._model is None:
            raise RuntimeError("Model not loaded.")

        t_start = time.perf_counter()
        results = self._model.predict(
            frame, 
            conf=confidence_threshold, 
            device=self.device, 
            verbose=False, 
            classes=list(_YOLO_CLASS_MAP.keys())
        )
        t_end = time.perf_counter()
        self._record_fps(t_end - t_start)

        detections = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            import torch
            
            # The most robust way to handle Ultralytics Boxes across versions
            # is to extract the underlying tensor (boxes.data), which is always [x1, y1, x2, y2, conf, cls]
            if hasattr(boxes, "data") and isinstance(boxes.data, torch.Tensor):
                boxes_np = boxes.data.detach().cpu().numpy()
            elif isinstance(boxes, torch.Tensor):
                boxes_np = boxes.detach().cpu().numpy()
            elif hasattr(boxes, "cpu"): # fallback for other wrappers
                boxes_np = boxes.cpu().numpy()
                if hasattr(boxes_np, "data"):
                    boxes_np = boxes_np.data
            else:
                boxes_np = np.array(boxes) # Last resort

            if boxes_np.ndim == 1 and len(boxes_np) == 6:
                boxes_np = np.expand_dims(boxes_np, axis=0)
            elif boxes_np.ndim == 0 or len(boxes_np) == 0:
                boxes_np = []
                
            for i in range(len(boxes_np)):
                row = boxes_np[i]
                cls_id = int(row[5])
                if cls_id not in _YOLO_CLASS_MAP:
                    continue
                conf = float(row[4])
                if conf < confidence_threshold:
                    continue
                bbox = BoundingBox(x1=float(row[0]), y1=float(row[1]), x2=float(row[2]), y2=float(row[3]))
                detections.append(DetectionResult(bbox=bbox, confidence=conf, class_id=cls_id))

        return detections


class BaseONNXRuntime(DetectorRuntime):
    """Abstract ONNX runtime. Concrete classes define the providers."""
    def __init__(self, model_path: str, providers: List[str]):
        super().__init__(model_path)
        self.providers = providers
        self.session = None
        constrained_cloud = os.environ.get("EDGE_CONSTRAINED_CLOUD", "false").lower() == "true"
        default_input_size = (
            "640"
            if not constrained_cloud or os.environ.get("CAMERA_ID") == "cam-border-01"
            else "320"
        )
        self.input_size = max(160, int(os.environ.get(
            "DETECTOR_INPUT_SIZE",
            default_input_size,
        )))

    def load(self) -> None:
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"Model artifact unavailable: {self.model_path}")
            
        try:
            import onnxruntime as ort
            import cv2
        except ImportError:
            raise RuntimeError("STRICT FAILURE: onnxruntime is not installed.")

        # Prevent OpenCV preprocessing/NMS workers from competing with the
        # ONNX worker for the single fractional CPU available on the edge
        # service.  This is process-wide and is set once at model load.
        cv2.setNumThreads(max(1, int(os.environ.get("OPENCV_NUM_THREADS", "1"))))

        # Check if the requested providers are actually available in the environment
        available_providers = ort.get_available_providers()
        for p in self.providers:
            if p not in available_providers:
                raise RuntimeError(
                    f"STRICT FAILURE: Requested provider {p} is unavailable. "
                    f"Available providers: {available_providers}"
                )

        try:
            # Enforce single session creation per instance
            sess_options = ort.SessionOptions()
            sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            sess_options.intra_op_num_threads = max(1, int(os.environ.get("ORT_INTRA_OP_THREADS", "1")))
            sess_options.inter_op_num_threads = max(1, int(os.environ.get("ORT_INTER_OP_THREADS", "1")))
            sess_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            sess_options.enable_cpu_mem_arena = True
            sess_options.enable_mem_pattern = True
            try:
                sess_options.add_session_config_entry("session.intra_op.allow_spinning", "0")
                sess_options.add_session_config_entry("session.inter_op.allow_spinning", "0")
            except Exception:
                pass
            
            self.session = ort.InferenceSession(self.model_path, sess_options, providers=self.providers)
            
            # Warm up
            dummy = np.zeros((1, 3, self.input_size, self.input_size), dtype=np.float32)
            input_name = self.session.get_inputs()[0].name
            self.session.run(None, {input_name: dummy})
            logger.info(
                "[%s] Loaded once; providers=%s input=%dx%d intra_op=%d inter_op=%d graph=ALL",
                self.__class__.__name__, self.providers, self.input_size, self.input_size,
                sess_options.intra_op_num_threads, sess_options.inter_op_num_threads,
            )
        except Exception as exc:
            raise RuntimeError(f"STRICT FAILURE: Failed to initialize ONNX session: {exc}")

    def _preprocess(self, frame: np.ndarray) -> Tuple[np.ndarray, float, float]:
        """Resize with letterboxing, HWC -> CHW, BGR -> RGB, and normalize."""
        import cv2
        # Target size for YOLOv8n
        target_size = (self.input_size, self.input_size)
        h, w = frame.shape[:2]
        
        r = min(target_size[0] / h, target_size[1] / w)
        new_unpad = int(round(w * r)), int(round(h * r))
        dw, dh = target_size[1] - new_unpad[0], target_size[0] - new_unpad[1]
        dw, dh = np.mod(dw, 32), np.mod(dh, 32)
        dw /= 2
        dh /= 2
        
        if (w, h) != new_unpad:
            im = cv2.resize(frame, new_unpad, interpolation=cv2.INTER_LINEAR)
        else:
            im = frame.copy()
            
        top, bottom = int(round(dh - 0.1)), int(round(dh + 0.1))
        left, right = int(round(dw - 0.1)), int(round(dw + 0.1))
        im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        
        im = im.transpose((2, 0, 1))[::-1]  # HWC to CHW, BGR to RGB
        im = np.ascontiguousarray(im, dtype=np.float32) / 255.0
        im = np.expand_dims(im, axis=0)
        self.last_input_shape = tuple(int(value) for value in im.shape)
        
        return im, r, (left, top)

    def detect(self, frame: np.ndarray, confidence_threshold: float) -> List[DetectionResult]:
        if self.session is None:
            raise RuntimeError("Model not loaded.")

        t_start = time.perf_counter()
        blob, ratio, (pad_w, pad_h) = self._preprocess(frame)
        t_preprocessed = time.perf_counter()
        input_name = self.session.get_inputs()[0].name
        outputs = self.session.run(None, {input_name: blob})
        t_inferred = time.perf_counter()
        preds = outputs[0]  # shape: (1, 84, 8400)
        detections = self._postprocess(preds, ratio, pad_w, pad_h, confidence_threshold)
        t_end = time.perf_counter()
        self.last_stage_ms = {
            "preprocess": (t_preprocessed - t_start) * 1000.0,
            "inference": (t_inferred - t_preprocessed) * 1000.0,
            "postprocess_nms": (t_end - t_inferred) * 1000.0,
            "total": (t_end - t_start) * 1000.0,
        }
        self._record_fps(t_end - t_start)
        
        return detections

    def _postprocess(self, preds: np.ndarray, ratio: float, pad_w: float, pad_h: float, conf_thresh: float) -> List[DetectionResult]:
        """Basic NMS and box rescaling for YOLOv8 ONNX outputs."""
        import cv2
        preds = np.squeeze(preds)  # (84, 8400)
        preds = preds.transpose()  # (8400, 84)
        
        boxes = preds[:, :4]
        # Only COCO classes the product actually supports participate in the
        # argmax/NMS.  The old path scanned all 80 classes and could discard a
        # valid person/vehicle because an unsupported class happened to win.
        supported_ids = np.asarray(sorted(_YOLO_CLASS_MAP), dtype=np.int64)
        supported_scores = preds[:, 4:][:, supported_ids]
        self.last_candidate_count = int(len(supported_scores))
        supported_argmax = np.argmax(supported_scores, axis=1)
        class_ids = supported_ids[supported_argmax]
        confidences = supported_scores[np.arange(len(supported_scores)), supported_argmax]
        
        mask = confidences > conf_thresh
        self.last_threshold_count = int(np.count_nonzero(mask))
        boxes = boxes[mask]
        class_ids = class_ids[mask]
        confidences = confidences[mask]
        
        # cx, cy, w, h to x1, y1, x2, y2
        x1 = boxes[:, 0] - boxes[:, 2] / 2
        y1 = boxes[:, 1] - boxes[:, 3] / 2
        x2 = boxes[:, 0] + boxes[:, 2] / 2
        y2 = boxes[:, 1] + boxes[:, 3] / 2
        
        # apply NMS
        indices = cv2.dnn.NMSBoxes(
            np.column_stack((x1, y1, boxes[:, 2], boxes[:, 3])).tolist(),
            confidences.tolist(),
            conf_thresh,
            0.45  # NMS threshold
        )
        self.last_nms_count = int(len(indices))
        
        detections = []
        if len(indices) > 0:
            for i in indices.flatten():
                cid = int(class_ids[i])
                if cid not in _YOLO_CLASS_MAP:
                    continue
                
                # Rescale back to original image coordinates
                rx1 = (x1[i] - pad_w) / ratio
                ry1 = (y1[i] - pad_h) / ratio
                rx2 = (x2[i] - pad_w) / ratio
                ry2 = (y2[i] - pad_h) / ratio
                
                bbox = BoundingBox(x1=rx1, y1=ry1, x2=rx2, y2=ry2)
                detections.append(DetectionResult(bbox=bbox, confidence=confidences[i], class_id=cid))
                
        return detections


class ONNXRuntimeCPU(BaseONNXRuntime):
    def __init__(self, model_path: str):
        super().__init__(model_path, providers=["CPUExecutionProvider"])


class ONNXRuntimeCUDA(BaseONNXRuntime):
    def __init__(self, model_path: str):
        # We explicitly request CUDA. If unavailable, BaseONNXRuntime load() will fail strictly.
        super().__init__(model_path, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])


class TensorRTRuntime(BaseONNXRuntime):
    def __init__(self, model_path: str):
        super().__init__(model_path, providers=["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"])


def create_runtime() -> DetectorRuntime:
    """Factory function for strict runtime selection based on DETECTOR_RUNTIME."""
    runtime_type = os.environ.get("DETECTOR_RUNTIME", "pytorch").lower()
    
    if runtime_type == "pytorch":
        return PyTorchRuntime(os.environ.get("DETECTOR_MODEL", "yolov8n.pt"))
    elif runtime_type == "onnx_cpu":
        return ONNXRuntimeCPU(os.environ.get("DETECTOR_MODEL_ONNX", "yolov8n.onnx"))
    elif runtime_type == "onnx_cuda":
        return ONNXRuntimeCUDA(os.environ.get("DETECTOR_MODEL_ONNX", "yolov8n.onnx"))
    elif runtime_type == "tensorrt":
        return TensorRTRuntime(os.environ.get("DETECTOR_MODEL_ONNX", "yolov8n.onnx"))
    else:
        raise ValueError(f"STRICT FAILURE: Unknown DETECTOR_RUNTIME: {runtime_type}")
