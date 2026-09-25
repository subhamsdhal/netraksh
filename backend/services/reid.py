"""
NETRAKSH — Appearance Embedding Engine Abstraction (Phase 3 Step 8)

This module provides a modular abstraction for appearance embeddings.
By design, it implements a CLASSICAL_APPEARANCE_DESCRIPTOR (e.g., color histogram)
and exposes a seam for a future LearnedReIDEmbeddingEngine.

Strict Privacy & Architectural Rules:
- No permanent storage of embeddings.
- In-memory TTL cache with bounded size.
- Explicit labeling of the representation type.
"""
import io
import time
import logging
import threading
from typing import Optional, Dict, Tuple
from collections import OrderedDict

import numpy as np

# We try to import cv2. In a real backend container this might be absent,
# but for the local demo it's available via the unified requirements.txt.
try:
    import cv2
except ImportError:
    cv2 = None

from backend.config import settings
from backend.models.orm import Event
from backend.services.evidence_storage import get_evidence_storage

logger = logging.getLogger(__name__)

# The required explicit representation type name.
REPRESENTATION_TYPE_CLASSICAL = "CLASSICAL_APPEARANCE_DESCRIPTOR"


class BoundedTTLCache:
    """
    A simple thread-safe TTL cache to ensure descriptors are temporary,
    never persisted to the database, and bounded in memory.
    """
    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 1800):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, Tuple[float, np.ndarray]] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[np.ndarray]:
        with self.lock:
            if key in self.cache:
                timestamp, value = self.cache[key]
                if time.time() - timestamp <= self.ttl_seconds:
                    # Move to end (LRU behavior)
                    self.cache.move_to_end(key)
                    return value
                else:
                    del self.cache[key]
            return None

    def put(self, key: str, value: np.ndarray):
        with self.lock:
            if key in self.cache:
                del self.cache[key]
            elif len(self.cache) >= self.maxsize:
                # Evict oldest
                self.cache.popitem(last=False)
            self.cache[key] = (time.time(), value)

    def size(self) -> int:
        with self.lock:
            self._prune()
            return len(self.cache)
            
    def _prune(self):
        now = time.time()
        keys_to_delete = []
        for k, (timestamp, _) in self.cache.items():
            if now - timestamp > self.ttl_seconds:
                keys_to_delete.append(k)
        for k in keys_to_delete:
            del self.cache[k]


class AppearanceEmbeddingEngine:
    """
    Base abstraction for Re-ID embeddings.
    """
    def __init__(self):
        self.representation_type = "UNKNOWN"

    def embed(self, image_bytes: bytes, bbox: Tuple[float, float, float, float]) -> Optional[np.ndarray]:
        """
        Given the raw full-frame image bytes and a normalized bounding box (x, y, w, h),
        returns a deterministic 1D numpy array representing the appearance, or None if invalid.
        """
        raise NotImplementedError


class ClassicalAppearanceDescriptor(AppearanceEmbeddingEngine):
    """
    Implements a deterministic color histogram representation.
    Explicitly NOT a neural Re-ID model.
    """
    def __init__(self):
        super().__init__()
        self.representation_type = REPRESENTATION_TYPE_CLASSICAL
        self.vector_size = 64  # Fixed bounded vector size (e.g. 8x8x8 or 64 bins total)

    def embed(self, image_bytes: bytes, bbox: Tuple[float, float, float, float]) -> Optional[np.ndarray]:
        if cv2 is None:
            logger.error("cv2 is required for ClassicalAppearanceDescriptor but is not installed.")
            return None
            
        try:
            # Decode the JPEG bytes
            np_arr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                return None
                
            h, w = img.shape[:2]
            
            # Unpack normalized bbox
            nx, ny, nw, nh = bbox
            if any(v is None for v in (nx, ny, nw, nh)):
                return None
                
            x1 = max(0, int((nx - nw / 2) * w))
            y1 = max(0, int((ny - nh / 2) * h))
            x2 = min(w, int((nx + nw / 2) * w))
            y2 = min(h, int((ny + nh / 2) * h))
            
            if x2 <= x1 or y2 <= y1:
                return None  # Invalid crop
                
            # Filter low-resolution crops (e.g. smaller than 16x16)
            crop_h, crop_w = y2 - y1, x2 - x1
            if crop_h < 16 or crop_w < 16:
                return None
                
            crop = img[y1:y2, x1:x2]
            
            # Convert to HSV for better color constancy against illumination changes
            hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
            
            # Compute a flattened 3D histogram: Hue(8), Saturation(4), Value(2) = 64 bins
            hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 2], [0, 180, 0, 256, 0, 256])
            
            # Deterministic normalization (L2)
            cv2.normalize(hist, hist, alpha=1.0, norm_type=cv2.NORM_L2)
            hist_flat = hist.flatten()
            
            # Guard against NaN/Inf
            if np.isnan(hist_flat).any() or np.isinf(hist_flat).any():
                return None
                
            return hist_flat
            
        except Exception as e:
            logger.warning(f"Failed to generate classical descriptor: {e}")
            return None


# Global singleton instances
_descriptor_engine = ClassicalAppearanceDescriptor()
_embedding_cache = BoundedTTLCache(
    maxsize=5000, 
    ttl_seconds=settings.REID_EMBEDDING_TTL_SECONDS
)

def compute_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Computes cosine similarity between two 1D numpy arrays."""
    # Dot product of L2 normalized vectors is cosine similarity
    dot = np.dot(vec1, vec2)
    norm = np.linalg.norm(vec1) * np.linalg.norm(vec2)
    if norm < 1e-6:
        return 0.0
    return float(dot / norm)

def get_or_compute_embedding(event: Event) -> Optional[np.ndarray]:
    """
    Retrieves the appearance embedding for the event from cache, or computes
    and caches it if it's missing (and if conditions allow).
    """
    if settings.CROSS_CAMERA_REID == "disabled":
        return None
        
    vec = _embedding_cache.get(event.id)
    if vec is not None:
        return vec
        
    # We need to compute it. Check if we have evidence and bbox.
    if not event.evidence_clip_ref or event.bbox_w is None:
        return None
        
    try:
        storage = get_evidence_storage(settings.EVIDENCE_STORAGE_BACKEND, settings.EVIDENCE_CLIPS_DIR)
        image_bytes = storage.read_evidence_bytes(event.evidence_clip_ref)
        
        # Guard against encrypted clips in this offline matching context
        if event.evidence_clip_ref.endswith(".enc"):
            # A real implementation would unwrap the camera's evidence_key_wrapped and decrypt here,
            # but to keep it safe from key leakage in the background, we skip encrypted crops if we 
            # don't have the key readily available, or we just fail gracefully.
            # In the local demo, some tests run with unencrypted images.
            return None
        
        bbox = (event.bbox_x, event.bbox_y, event.bbox_w, event.bbox_h)
        vec = _descriptor_engine.embed(image_bytes, bbox)
        
        if vec is not None:
            _embedding_cache.put(event.id, vec)
        return vec
        
    except Exception as e:
        logger.warning(f"Could not compute embedding for event {event.id}: {e}")
        return None

def get_representation_type() -> str:
    return _descriptor_engine.representation_type

def get_cache_metrics() -> Dict[str, int]:
    return {
        "size": _embedding_cache.size(),
        "maxsize": _embedding_cache.maxsize,
        "ttl_seconds": _embedding_cache.ttl_seconds
    }
