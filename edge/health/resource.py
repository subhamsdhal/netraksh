import logging
import os
import time
from enum import Enum
from typing import Dict, Any

import psutil

logger = logging.getLogger(__name__)

class ResourceState(Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"

class EdgeResourceGovernor:
    """
    Monitors node-level resources (CPU, Mem) and stream metrics (queue depth, latency).
    Emits a normalized state with hysteresis to avoid oscillation.
    """
    def __init__(self):
        self.max_cpu_percent = float(os.environ.get("MAX_CPU_PERCENT", "85.0"))
        self.max_memory_mb = float(os.environ.get("MAX_MEMORY_MB", "4096.0"))
        self.max_queue_depth = int(os.environ.get("MAX_QUEUE_DEPTH", "60"))
        self.max_latency_ms = float(os.environ.get("MAX_INFERENCE_LATENCY_MS", "200.0"))
        
        self.hysteresis_seconds = float(os.environ.get("RESOURCE_HYSTERESIS_SECONDS", "5.0"))
        
        self._current_state = ResourceState.NORMAL
        self._state_start_time = time.time()
        
        # We need psutil to settle CPU measurements
        psutil.cpu_percent(interval=None)

    def evaluate(self, active_streams: int, avg_queue_depth: int, avg_latency_ms: float) -> ResourceState:
        """Evaluate current resource metrics and return the system state using hysteresis."""
        cpu = psutil.cpu_percent(interval=None)
        mem_info = psutil.virtual_memory()
        mem_mb = (mem_info.total - mem_info.available) / (1024 * 1024)
        
        # Determine instantaneous required state
        instant_state = ResourceState.NORMAL
        
        if cpu > self.max_cpu_percent or mem_mb > self.max_memory_mb:
            instant_state = ResourceState.CRITICAL
        elif avg_queue_depth >= self.max_queue_depth or avg_latency_ms >= self.max_latency_ms:
            instant_state = ResourceState.CRITICAL
        elif cpu > self.max_cpu_percent * 0.85 or avg_queue_depth > self.max_queue_depth * 0.8:
            instant_state = ResourceState.DEGRADED
        elif cpu > self.max_cpu_percent * 0.7 or avg_queue_depth > self.max_queue_depth * 0.5:
            instant_state = ResourceState.WARNING
            
        now = time.time()
        time_in_state = now - self._state_start_time
        
        # State transitions
        if instant_state != self._current_state:
            # Escalate immediately to worse states to protect safety
            if self._is_worse(instant_state, self._current_state):
                self._current_state = instant_state
                self._state_start_time = now
            # Recover slowly (hysteresis)
            elif time_in_state >= self.hysteresis_seconds:
                self._current_state = instant_state
                self._state_start_time = now
                
        return self._current_state

    def _is_worse(self, new_state: ResourceState, current_state: ResourceState) -> bool:
        order = {ResourceState.NORMAL: 0, ResourceState.WARNING: 1, ResourceState.DEGRADED: 2, ResourceState.CRITICAL: 3}
        return order[new_state] > order[current_state]

    def get_telemetry(self) -> Dict[str, Any]:
        return {
            "resource_state": self._current_state.value,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_mb": psutil.virtual_memory().used / (1024*1024),
            "time_in_state_s": round(time.time() - self._state_start_time, 2)
        }
