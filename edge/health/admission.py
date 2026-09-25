import logging
import os
from enum import Enum
from typing import Dict, Any

from edge.health.resource import EdgeResourceGovernor, ResourceState

logger = logging.getLogger(__name__)

class StreamPriority(Enum):
    CRITICAL = 4
    HIGH = 3
    NORMAL = 2
    LOW = 1

class AdmissionDecision(Enum):
    ACCEPT = "ACCEPT"
    ACCEPT_DEGRADED = "ACCEPT_DEGRADED"
    REJECT = "REJECT"

class StreamAdmissionController:
    """
    Acts as the gatekeeper for new camera streams based on governor state and max configuration bounds.
    """
    def __init__(self, governor: EdgeResourceGovernor):
        self.governor = governor
        
        # Must be bounded, not unbounded. 
        self.max_streams = int(os.environ.get("MAX_ACTIVE_STREAMS", "4"))
        
    def request_admission(self, stream_id: str, priority: StreamPriority, current_active_streams: int) -> AdmissionDecision:
        if current_active_streams >= self.max_streams:
            logger.warning(f"Admission REJECTED for {stream_id}: Hard limit of {self.max_streams} streams reached.")
            return AdmissionDecision.REJECT
            
        current_state = self.governor._current_state
        
        if current_state == ResourceState.CRITICAL:
            if priority == StreamPriority.CRITICAL:
                logger.warning(f"Admission ACCEPT_DEGRADED for CRITICAL {stream_id} despite CRITICAL resource state.")
                return AdmissionDecision.ACCEPT_DEGRADED
            logger.warning(f"Admission REJECTED for {stream_id}: System is in CRITICAL state.")
            return AdmissionDecision.REJECT
            
        if current_state == ResourceState.DEGRADED:
            if priority.value <= StreamPriority.NORMAL.value:
                logger.warning(f"Admission REJECTED for {priority.name} {stream_id}: System is in DEGRADED state.")
                return AdmissionDecision.REJECT
            return AdmissionDecision.ACCEPT_DEGRADED
            
        if current_state == ResourceState.WARNING:
            if priority == StreamPriority.LOW:
                logger.warning(f"Admission REJECTED for LOW priority {stream_id}: System is in WARNING state.")
                return AdmissionDecision.REJECT
                
        return AdmissionDecision.ACCEPT

class DegradationPolicy:
    """
    Governs how modules behave under varying resource states.
    Emits skip decisions to avoid false negatives.
    """
    def __init__(self):
        # Configuration mapping
        self.anpr_critical = os.environ.get("ANPR_CRITICAL", "false").lower() == "true"
        self.face_critical = os.environ.get("FACE_CRITICAL", "false").lower() == "true"
        self.behavior_critical = os.environ.get("BEHAVIOR_CRITICAL", "false").lower() == "true"
        
    def should_evaluate(self, module: str, state: ResourceState, frame_index: int) -> bool:
        """Returns True if the module should execute this frame, False to skip and emit NOT_EVALUATED."""
        is_critical = getattr(self, f"{module.lower()}_critical", False)
        
        if state == ResourceState.NORMAL:
            return True
            
        if state == ResourceState.WARNING:
            # Evaluate every 2nd frame
            return (frame_index % 2) == 0
            
        if state == ResourceState.DEGRADED:
            if is_critical:
                # Maintain minimum cadence
                return (frame_index % 5) == 0
            return False
            
        if state == ResourceState.CRITICAL:
            if is_critical:
                return (frame_index % 10) == 0
            return False
            
        return True
