import logging
import numpy as np
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

class EmbeddingWatchlistIndex:
    """
    In-memory vector store mapping subject_id to normalized embeddings.
    Provides cosine similarity search.
    """
    
    def __init__(self, match_threshold: float = 0.5):
        self.match_threshold = match_threshold
        # subject_id -> List of embeddings
        self._index: Dict[str, dict] = {}
        self._ready = False
        
    def sync_from_embeddings(self, persons: List[Dict]):
        """
        persons: List of dicts [{"person_id": str, "name": str, "embeddings": List[np.ndarray]}]
        Rebuilds the index. Empties the current index.
        """
        new_index = {}
        total_embeddings = 0
        
        for p in persons:
            person_id = p.get("person_id")
            if not person_id:
                continue
                
            embeddings = p.get("embeddings", [])
            valid_embeddings = []
            
            for emb in embeddings:
                # Ensure it's a normalized 1D numpy array
                if isinstance(emb, np.ndarray) and emb.ndim == 1:
                    norm = np.linalg.norm(emb)
                    if norm > 0:
                        valid_embeddings.append(emb / norm)
            
            if valid_embeddings:
                new_index[person_id] = {
                    "name": p.get("name", "Unknown"),
                    "embeddings": valid_embeddings
                }
                total_embeddings += len(valid_embeddings)
                
        self._index = new_index
        self._ready = len(self._index) > 0
        logger.info(f"[WatchlistIndex] Synced {len(self._index)} subjects with {total_embeddings} total embeddings.")
        
    def search(self, query_embedding: np.ndarray) -> Dict:
        """
        Search for the closest match using Cosine Similarity.
        query_embedding must be a normalized 1D numpy array.
        
        Returns:
        {
            "state": "MATCH" | "UNKNOWN" | "LOW_CONFIDENCE" | "ERROR",
            "person_id": str or None,
            "name": str or None,
            "similarity": float or None,
            "threshold": float
        }
        """
        if not self._ready:
            return {
                "state": "ERROR",
                "person_id": None,
                "name": None,
                "similarity": None,
                "threshold": self.match_threshold
            }
            
        try:
            query_norm = np.linalg.norm(query_embedding)
            if query_norm == 0 or not np.isfinite(query_norm):
                return {
                    "state": "ERROR",
                    "person_id": None,
                    "name": None,
                    "similarity": None,
                    "threshold": self.match_threshold
                }
                
            query_normalized = query_embedding / query_norm
            
            best_score = -1.0
            best_person_id = None
            best_name = None
            
            for person_id, data in self._index.items():
                for emb in data["embeddings"]:
                    score = float(np.dot(query_normalized, emb))
                    if score > best_score:
                        best_score = score
                        best_person_id = person_id
                        best_name = data["name"]
                        
            if best_score >= self.match_threshold:
                state = "MATCH"
            elif best_score >= (self.match_threshold - 0.15): # Configurable margin
                state = "LOW_CONFIDENCE"
            else:
                state = "UNKNOWN"
                
            return {
                "state": state,
                "person_id": best_person_id,
                "name": best_name,
                "similarity": best_score,
                "threshold": self.match_threshold
            }
            
        except Exception as e:
            logger.error(f"[WatchlistIndex] Error during search: {e}")
            return {
                "state": "ERROR",
                "person_id": None,
                "name": None,
                "similarity": None,
                "threshold": self.match_threshold
            }
