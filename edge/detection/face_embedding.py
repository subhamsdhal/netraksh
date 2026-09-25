import os
import logging
import numpy as np
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)

class FaceEmbeddingEngine(ABC):
    """
    Interface for extracting face embeddings.
    """
    
    @property
    @abstractmethod
    def embedding_dimension(self) -> int:
        pass
        
    @abstractmethod
    def embed(self, aligned_face: np.ndarray) -> Optional[np.ndarray]:
        """
        Extracts a normalized embedding from an aligned face crop.
        Must return None on failure.
        """
        pass

class ONNXFaceEmbeddingEngine(FaceEmbeddingEngine):
    """
    ONNX-based face embedding extractor.
    Validates the ONNX model at initialization.
    If the model is missing or invalid, raises ValueError.
    """
    
    def __init__(self, model_path: str):
        if not model_path or not os.path.exists(model_path):
            raise ValueError(f"ONNX model path not found or invalid: {model_path}")
            
        try:
            import onnxruntime as ort
        except ImportError:
            raise ValueError("onnxruntime is not installed. Cannot load ONNX models.")
            
        logger.info(f"[FaceEmbedding] Validating ONNX model at {model_path}")
        
        # Load session with bounded memory / CPU only
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = 1
        sess_options.inter_op_num_threads = 1
        
        self.session = ort.InferenceSession(
            model_path, 
            sess_options=sess_options,
            providers=['CPUExecutionProvider']
        )
        
        inputs = self.session.get_inputs()
        if len(inputs) != 1:
            raise ValueError(f"Expected exactly 1 input tensor, got {len(inputs)}")
            
        self.input_name = inputs[0].name
        self.input_shape = inputs[0].shape
        
        # Typically shape is [1, 3, 112, 112]
        if len(self.input_shape) != 4 or self.input_shape[1] != 3:
            raise ValueError(f"Unexpected input shape: {self.input_shape}. Expected [batch, 3, H, W]")
            
        outputs = self.session.get_outputs()
        if len(outputs) != 1:
            raise ValueError(f"Expected exactly 1 output tensor, got {len(outputs)}")
            
        self.output_name = outputs[0].name
        self.output_shape = outputs[0].shape
        
        # Output shape is typically [1, 512] or [1, 128]
        if len(self.output_shape) != 2:
            raise ValueError(f"Unexpected output shape: {self.output_shape}. Expected [batch, dim]")
            
        self._dim = int(self.output_shape[1])
        logger.info(f"[FaceEmbedding] Model validated successfully. Input: {self.input_shape}, Output: {self.output_shape}")

    @property
    def embedding_dimension(self) -> int:
        return self._dim

    def embed(self, aligned_face: np.ndarray) -> Optional[np.ndarray]:
        """
        Extracts a normalized embedding.
        aligned_face: expected to be a BGR image from cv2, sized (112, 112, 3) or similar to input_shape.
        """
        try:
            import cv2
            # Resize if necessary
            target_h, target_w = self.input_shape[2], self.input_shape[3]
            # Handle dynamic dimensions (sometimes 'None' or string in shape)
            if not isinstance(target_h, int): target_h = 112
            if not isinstance(target_w, int): target_w = 112
                
            if aligned_face.shape[:2] != (target_h, target_w):
                aligned_face = cv2.resize(aligned_face, (target_w, target_h))
                
            # Preprocessing: BGR -> RGB
            rgb = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2RGB)
            
            # Preprocessing: Normalize (typically (x - 127.5) / 128.0 for InsightFace)
            # This should be configurable, but assuming InsightFace standard for now.
            img = (np.float32(rgb) - 127.5) / 128.0
            
            # HWC -> CHW
            img = np.transpose(img, (2, 0, 1))
            
            # Add batch dimension
            blob = np.expand_dims(img, axis=0)
            
            # Inference
            net_out = self.session.run([self.output_name], {self.input_name: blob})[0]
            
            # Flatten and Normalize
            embedding = net_out.flatten()
            norm = np.linalg.norm(embedding)
            if norm == 0 or not np.isfinite(norm):
                logger.warning("[FaceEmbedding] Embedding norm is 0 or non-finite.")
                return None
                
            embedding = embedding / norm
            return embedding

        except Exception as e:
            logger.error(f"[FaceEmbedding] Error during embedding extraction: {e}")
            return None

class SFaceEmbeddingModel(FaceEmbeddingEngine):
    """
    SFace ONNX embedding extractor (OpenCV Zoo 2021dec version).
    Validates model artifact and uses exact validated preprocessing.
    """
    def __init__(self, model_path: str):
        if not model_path or not os.path.exists(model_path):
            raise ValueError(f"ONNX model path not found or invalid: {model_path}")
            
        try:
            import onnxruntime as ort
        except ImportError:
            raise ValueError("onnxruntime is not installed. Cannot load ONNX models.")
            
        logger.info(f"[SFaceEmbedding] Validating ONNX model at {model_path}")
        
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = 1
        sess_options.inter_op_num_threads = 1
        
        self.session = ort.InferenceSession(
            model_path, 
            sess_options=sess_options,
            providers=['CPUExecutionProvider']
        )
        
        inputs = self.session.get_inputs()
        if len(inputs) != 1:
            raise ValueError(f"Expected exactly 1 input tensor, got {len(inputs)}")
            
        self.input_name = inputs[0].name
        self.input_shape = inputs[0].shape
        
        if len(self.input_shape) != 4 or self.input_shape[1] != 3:
            raise ValueError(f"Unexpected input shape: {self.input_shape}. Expected [batch, 3, H, W]")
            
        outputs = self.session.get_outputs()
        if len(outputs) != 1:
            raise ValueError(f"Expected exactly 1 output tensor, got {len(outputs)}")
            
        self.output_name = outputs[0].name
        self.output_shape = outputs[0].shape
        
        if len(self.output_shape) != 2 or self.output_shape[1] != 128:
            raise ValueError(f"Unexpected output shape: {self.output_shape}. Expected [batch, 128]")
            
        self._dim = int(self.output_shape[1])
        logger.info(f"[SFaceEmbedding] Model validated successfully. Input: {self.input_shape}, Output: {self.output_shape}")

    @property
    def embedding_dimension(self) -> int:
        return self._dim

    def embed(self, aligned_face: np.ndarray) -> Optional[np.ndarray]:
        """
        Extracts a normalized embedding using SFace canonical preprocessing.
        aligned_face: BGR image from FaceAligner.
        """
        try:
            import cv2
            
            if aligned_face.shape[:2] != (112, 112):
                aligned_face = cv2.resize(aligned_face, (112, 112))
                
            # Canonical preprocessing established by reference-equivalence test:
            # scale=1.0, mean=(0,0,0), swapRB=True
            blob = cv2.dnn.blobFromImage(aligned_face, 1.0, (112, 112), (0, 0, 0), swapRB=True, crop=False)
            
            net_out = self.session.run([self.output_name], {self.input_name: blob})[0]
            
            embedding = net_out.flatten()
            norm = np.linalg.norm(embedding)
            if norm == 0 or not np.isfinite(norm):
                logger.warning("[SFaceEmbedding] Embedding norm is 0 or non-finite.")
                return None
                
            embedding = embedding / norm
            return embedding

        except Exception as e:
            logger.error(f"[SFaceEmbedding] Error during embedding extraction: {e}")
            return None
