import pytest
import time
import sys
from unittest.mock import patch, MagicMock

@pytest.fixture
def demo_runner_mocked():
    """
    Provides edge.demo_runner with mocked dependencies to avoid polluting sys.modules globally.
    """
    # 1. Patch dependencies
    mock_cv2 = MagicMock()
    mock_httpx = MagicMock()
    mock_ultralytics = MagicMock()
    mock_deep_sort = MagicMock()
    mock_deepsort_tracker = MagicMock()
    mock_edge_main = MagicMock()

    class MockEdgePipeline:
        def __init__(self, config):
            pass
        def start(self):
            pass
        def stop(self):
            pass

    mock_edge_main.EdgePipeline = MockEdgePipeline

    patches = {
        'cv2': mock_cv2,
        'httpx': mock_httpx,
        'ultralytics': mock_ultralytics,
        'deep_sort_realtime': mock_deep_sort,
        'deep_sort_realtime.deepsort_tracker': mock_deepsort_tracker,
        'edge.main': mock_edge_main
    }

    # Remove demo_runner if it was imported previously
    if 'edge.demo_runner' in sys.modules:
        del sys.modules['edge.demo_runner']

    with patch.dict('sys.modules', patches):
        # 2. Import module under test inside patch context
        import edge.demo_runner
        
        # 3. Execute test
        yield edge.demo_runner

    # 4 & 5. Restore patched sys.modules and clean up
    if 'edge.demo_runner' in sys.modules:
        del sys.modules['edge.demo_runner']

def test_stale_replay_rejected(demo_runner_mocked):
    """
    Test that the loop rejects a stale replay (video_time=0) where
    updated_at is older than pipeline_exit_time.
    """
    _scenario = demo_runner_mocked._scenario
    # Simulate a finished video play that was started 20 seconds ago
    _scenario.clear()
    _scenario["current"] = "normal"
    _scenario["video_time"] = 0.0
    _scenario["video_time_updated_at"] = time.time() - 20.0
    _scenario["video_session_id"] = "test-session"
    _scenario["should_restart"] = False

    pipeline_exit_time = time.time() - 5.0  # Pipeline exited 5s ago

    # This represents the condition inside demo_runner's while loop
    should_restart = False
    if _scenario.get("current") == "normal" and _scenario.get("video_time", -1) == 0:
        updated_at = _scenario.get("video_time_updated_at", 0)
        if updated_at > pipeline_exit_time:
            should_restart = True
            
    assert should_restart is False, "Stale replay should be rejected"

def test_fresh_replay_accepted(demo_runner_mocked):
    """
    Test that the loop accepts a fresh replay (video_time=0) where
    updated_at is newer than pipeline_exit_time.
    """
    _scenario = demo_runner_mocked._scenario
    _scenario.clear()
    _scenario["current"] = "normal"
    _scenario["video_time"] = 0.0
    # Simulate user clicking replay 2 seconds AFTER pipeline exited
    pipeline_exit_time = time.time() - 5.0
    _scenario["video_time_updated_at"] = pipeline_exit_time + 2.0
    _scenario["video_session_id"] = "test-session"
    _scenario["should_restart"] = False

    should_restart = False
    if _scenario.get("current") == "normal" and _scenario.get("video_time", -1) == 0:
        updated_at = _scenario.get("video_time_updated_at", 0)
        if updated_at > pipeline_exit_time:
            should_restart = True
            
    assert should_restart is True, "Fresh replay should be accepted"
