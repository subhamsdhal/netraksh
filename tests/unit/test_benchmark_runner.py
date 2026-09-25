import os
import tempfile
import json
import pytest
from edge.benchmark_runner import run_benchmark

def test_benchmark_runner_missing_args(caplog):
    """Test graceful handling of missing arguments."""
    run_benchmark(video_path=None, image_dir=None)
    assert "No video or image directory provided" in caplog.text

def test_benchmark_runner_quick_mode():
    """Test that quick mode runs without crashing on a dummy video or just returns."""
    # We can't guarantee vtest.avi is present in CI, but we can check if it exists
    video_path = "demo/videos/vtest.avi"
    if os.path.exists(video_path):
        run_benchmark(video_path=video_path, quick_mode=True)
        # Check if report was generated
        assert os.path.exists("docs/PHASE3_AI_BENCHMARK.md")
        assert os.path.exists("docs/benchmark_raw.json")
    else:
        pytest.skip(f"{video_path} not found")
