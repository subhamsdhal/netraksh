import time
import logging
from typing import Dict, List, Optional
from collections import deque

logger = logging.getLogger(__name__)

class TemporalFaceFusion:
    """
    Maintains bounded recent face observations for a track_id.
    Fuses multiple frames of face recognition to a stable conclusion.
    """
    
    def __init__(self, max_history: int = 10, confirm_threshold: int = 3, expiration_seconds: float = 5.0):
        self.max_history = max_history
        self.confirm_threshold = confirm_threshold
        self.expiration_seconds = expiration_seconds
        
        # track_id -> List of recent match states (person_id, state, score, timestamp)
        self._history: Dict[int, deque] = {}
        
    def add_observation(self, track_id: int, person_id: Optional[str], state: str, score: Optional[float]) -> Dict:
        """
        Add a frame's observation for a given track_id and return the fused conclusion.
        
        state from index: MATCH, UNKNOWN, LOW_CONFIDENCE, ERROR
        """
        now = time.time()
        
        if track_id not in self._history:
            self._history[track_id] = deque(maxlen=self.max_history)
            
        self._history[track_id].append({
            "person_id": person_id,
            "state": state,
            "score": score,
            "timestamp": now
        })
        
        return self._fuse(track_id)
        
    def _fuse(self, track_id: int) -> Dict:
        """
        Fuses the recent history into a single conclusion.
        Possible output states: CANDIDATE, CONFIRMED, UNKNOWN, UNSTABLE
        """
        now = time.time()
        history = self._history.get(track_id, [])
        
        # Filter expired
        valid_history = [h for h in history if (now - h["timestamp"]) <= self.expiration_seconds]
        if len(valid_history) != len(history):
             self._history[track_id] = deque(valid_history, maxlen=self.max_history)
             
        if not valid_history:
            return {"fusion_state": "UNKNOWN", "person_id": None, "confidence": None}
            
        # Tally MATCH states by person_id
        match_tallies: Dict[str, int] = {}
        highest_score_for_person: Dict[str, float] = {}
        
        for h in valid_history:
            if h["state"] == "MATCH" and h["person_id"] is not None:
                pid = h["person_id"]
                match_tallies[pid] = match_tallies.get(pid, 0) + 1
                if h["score"] is not None:
                    highest_score_for_person[pid] = max(highest_score_for_person.get(pid, -1.0), h["score"])
                    
        if not match_tallies:
            return {"fusion_state": "UNKNOWN", "person_id": None, "confidence": None}
            
        # Find the most frequent person
        sorted_tallies = sorted(match_tallies.items(), key=lambda x: x[1], reverse=True)
        top_person_id, top_count = sorted_tallies[0]
        
        # Check for conflict (another person has matches >= confirm_threshold or too close)
        if len(sorted_tallies) > 1:
            runner_up_person_id, runner_up_count = sorted_tallies[1]
            if runner_up_count >= self.confirm_threshold or (runner_up_count > 0 and top_count - runner_up_count <= 1):
                return {"fusion_state": "UNSTABLE", "person_id": None, "confidence": None}
                
        fusion_state = "CONFIRMED" if top_count >= self.confirm_threshold else "CANDIDATE"
        confidence = highest_score_for_person.get(top_person_id)
        
        return {
            "fusion_state": fusion_state,
            "person_id": top_person_id,
            "confidence": confidence
        }
        
    def cleanup_expired(self):
        """Removes expired tracks completely."""
        now = time.time()
        expired = []
        for track_id, history in self._history.items():
            if not history or (now - history[-1]["timestamp"]) > self.expiration_seconds:
                expired.append(track_id)
                
        for track_id in expired:
            del self._history[track_id]
