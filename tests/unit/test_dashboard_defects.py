import pytest
import time
from edge.demo_runner import _scenario, _poll_scenario
from unittest.mock import patch, MagicMock

def test_source_session_switching(tmp_path):
    # The edge deliberately rejects a control-plane path it cannot resolve.
    # Use a local fixture path so this tests session switching, not that guard.
    source_path = tmp_path / "source.avi"
    source_path.write_bytes(b"source fixture")
    source = str(source_path)
    # Reset state
    _scenario["current"] = "normal"
    _scenario["video_source"] = None
    _scenario["video_session_id"] = None
    _scenario["should_restart"] = False

    # Mock httpx response
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        # First poll with initial values
        mock_resp.json.return_value = {
            "scenario": "normal",
            "video_source": source,
            "video_session_id": "session-123"
        }
        
        def fake_sleep(sec):
            raise KeyboardInterrupt()

        with patch("time.sleep", side_effect=fake_sleep):
            try:
                _poll_scenario("http://localhost:8000", "cam-test")
            except KeyboardInterrupt:
                pass
        
        # On first poll (when video_source was None), should_restart should NOT be True
        assert _scenario["video_source"] == source
        assert _scenario["video_session_id"] == "session-123"
        assert not _scenario["should_restart"]

        # Now simulate a second poll with a new session ID
        mock_resp.json.return_value = {
            "scenario": "normal",
            "video_source": source,
            "video_session_id": "session-456"
        }

        with patch("time.sleep", side_effect=fake_sleep):
            try:
                _poll_scenario("http://localhost:8000", "cam-test")
            except KeyboardInterrupt:
                pass

        # Because video_source was not None, should_restart should now be True
        assert _scenario["video_source"] == source
        assert _scenario["video_session_id"] == "session-456"
        assert _scenario["should_restart"]

        _scenario["should_restart"] = False

        # Third poll, same session, no restart
        with patch("time.sleep", side_effect=fake_sleep):
            try:
                _poll_scenario("http://localhost:8000", "cam-test")
            except KeyboardInterrupt:
                pass

        assert not _scenario["should_restart"]
