"""
Tests for WP-4.4 Edge Resource Management and Admission Control.
"""
import os
import pytest
import time
from unittest.mock import patch, MagicMock

from edge.health.resource import EdgeResourceGovernor, ResourceState
from edge.health.admission import StreamAdmissionController, StreamPriority, AdmissionDecision, DegradationPolicy

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {}, clear=True):
        yield

def test_governor_initial_state(mock_env):
    gov = EdgeResourceGovernor()
    assert gov._current_state == ResourceState.NORMAL

@patch("psutil.cpu_percent")
@patch("psutil.virtual_memory")
def test_governor_warning_transition(mock_vmem, mock_cpu, mock_env):
    os.environ["MAX_CPU_PERCENT"] = "80.0"
    os.environ["RESOURCE_HYSTERESIS_SECONDS"] = "0.0"
    gov = EdgeResourceGovernor()
    
    mock_cpu.return_value = 60.0 # > 80 * 0.7 (56) -> WARNING
    mock_mem = MagicMock()
    mock_mem.total = 8000 * 1024 * 1024
    mock_mem.available = 6000 * 1024 * 1024
    mock_vmem.return_value = mock_mem
    
    state = gov.evaluate(active_streams=1, avg_queue_depth=5, avg_latency_ms=20.0)
    assert state == ResourceState.WARNING

@patch("psutil.cpu_percent")
@patch("psutil.virtual_memory")
def test_governor_critical_transition(mock_vmem, mock_cpu, mock_env):
    os.environ["MAX_QUEUE_DEPTH"] = "60"
    os.environ["RESOURCE_HYSTERESIS_SECONDS"] = "0.0"
    gov = EdgeResourceGovernor()
    
    mock_cpu.return_value = 10.0
    mock_mem = MagicMock()
    mock_mem.total = 8000 * 1024 * 1024
    mock_mem.available = 7000 * 1024 * 1024
    mock_vmem.return_value = mock_mem
    
    # Exceed queue depth -> CRITICAL
    state = gov.evaluate(active_streams=2, avg_queue_depth=65, avg_latency_ms=20.0)
    assert state == ResourceState.CRITICAL

def test_hysteresis_prevents_rapid_recovery(mock_env):
    os.environ["MAX_CPU_PERCENT"] = "80.0"
    os.environ["RESOURCE_HYSTERESIS_SECONDS"] = "5.0"
    gov = EdgeResourceGovernor()
    
    # Force state to CRITICAL internally
    gov._current_state = ResourceState.CRITICAL
    gov._state_start_time = time.time()
    
    with patch("psutil.cpu_percent", return_value=10.0), \
         patch("psutil.virtual_memory") as mock_vmem:
         
        mock_mem = MagicMock()
        mock_mem.total = 8000 * 1024 * 1024
        mock_mem.available = 7000 * 1024 * 1024
        mock_vmem.return_value = mock_mem
        
        # Even though metrics are fine, we haven't passed 5 seconds
        state = gov.evaluate(1, 1, 10.0)
        assert state == ResourceState.CRITICAL

def test_admission_hard_limit(mock_env):
    os.environ["MAX_ACTIVE_STREAMS"] = "2"
    gov = EdgeResourceGovernor()
    adm = StreamAdmissionController(gov)
    
    # 2 streams active, hard limit is 2 -> REJECT
    decision = adm.request_admission("cam3", StreamPriority.NORMAL, 2)
    assert decision == AdmissionDecision.REJECT

def test_admission_reject_low_in_warning(mock_env):
    gov = EdgeResourceGovernor()
    gov._current_state = ResourceState.WARNING
    adm = StreamAdmissionController(gov)
    
    decision = adm.request_admission("cam1", StreamPriority.LOW, 1)
    assert decision == AdmissionDecision.REJECT

def test_admission_accept_degraded_in_degraded(mock_env):
    gov = EdgeResourceGovernor()
    gov._current_state = ResourceState.DEGRADED
    adm = StreamAdmissionController(gov)
    
    decision = adm.request_admission("cam1", StreamPriority.HIGH, 1)
    assert decision == AdmissionDecision.ACCEPT_DEGRADED

def test_degradation_policy_normal(mock_env):
    policy = DegradationPolicy()
    assert policy.should_evaluate("ANPR", ResourceState.NORMAL, frame_index=1) is True

def test_degradation_policy_warning_cadence(mock_env):
    policy = DegradationPolicy()
    assert policy.should_evaluate("ANPR", ResourceState.WARNING, frame_index=1) is False
    assert policy.should_evaluate("ANPR", ResourceState.WARNING, frame_index=2) is True

def test_degradation_policy_critical_skips_optional(mock_env):
    os.environ["ANPR_CRITICAL"] = "false"
    policy = DegradationPolicy()
    
    assert policy.should_evaluate("ANPR", ResourceState.CRITICAL, frame_index=10) is False

def test_degradation_policy_critical_preserves_critical_modules(mock_env):
    os.environ["ANPR_CRITICAL"] = "true"
    policy = DegradationPolicy()
    
    assert policy.should_evaluate("ANPR", ResourceState.CRITICAL, frame_index=10) is True
    assert policy.should_evaluate("ANPR", ResourceState.CRITICAL, frame_index=11) is False
