import hashlib
import json
import random
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

@dataclass
class EvaluationPair:
    identity_a: str
    identity_b: str
    sample_a: str
    sample_b: str
    pair_type: str  # GENUINE or IMPOSTOR
    condition_metadata: Dict[str, str]
    dataset_version: str
    seed: int

class PairGenerator:
    """Generates deterministic genuine/impostor pairs without raw image duplication."""
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(self.seed)

    def generate_pairs(self, 
                       dataset_info: dict, 
                       identities: dict, 
                       max_genuine: int = 1000, 
                       max_impostor: int = 1000) -> List[EvaluationPair]:
        """
        identities: Dict mapping identity_id -> List of sample_ids
        """
        pairs = []
        # In a real scenario, this would sample deterministically from the dataset splits.
        # But since NO DATASET exists, we will not fake the pairs.
        if not identities:
            return pairs
            
        # Example generation logic (stub for when data arrives)
        for identity_id, samples in identities.items():
            if len(samples) > 1:
                # add genuine pairs...
                pass
                
        return pairs

    def hash_pairs(self, pairs: List[EvaluationPair]) -> str:
        """Computes a deterministic hash of the evaluation set."""
        if not pairs:
            return "empty"
        data = json.dumps([asdict(p) for p in pairs], sort_keys=True).encode("utf-8")
        return hashlib.sha256(data).hexdigest()
