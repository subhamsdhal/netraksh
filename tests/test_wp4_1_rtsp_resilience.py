import logging
import queue
import time
from unittest import mock
import pytest
import numpy as np

from edge.ingestion.camera_adapter import CameraAdapter, sanitize_url, classify_source
from shared.constants import StreamState


def test_sanitize_url():
    assert sanitize_url("rtsp://admin:password123@192.168.1.10:554/stream") == "rtsp://***:***@192.168.1.10:554/stream"
    assert sanitize_url("rtsp://admin:pass%20word@192.168.1.10/stream") == "rtsp://***:***@192.168.1.10/stream"
    assert sanitize_url("http://user:pass@localhost") == "http://***:***@localhost"
    assert sanitize_url("rtsp://192.168.1.10/stream") == "rtsp://192.168.1.10/stream"
    assert sanitize_url("0") == "0"


def test_source_classification_keeps_network_sources_out_of_demo_looping():
    assert classify_source("demo/videos/vtest.mp4") == "LOCAL_FINITE_FILE"
    assert classify_source("rtsp://camera/stream") == "RTSP"
    assert classify_source("https://camera/stream") == "HTTP_STREAM"
    assert classify_source("0") == "USB_CAMERA"


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_local_demo_eof_rewinds_and_marks_replay_boundary(mock_vc):
    cap = mock.MagicMock()
    cap.isOpened.return_value = True
    cap.get.side_effect = lambda prop: 10.0 if prop == 5 else (64 if prop == 3 else (48 if prop == 4 else 0.0))
    reads = [(True, np.zeros((48, 64, 3), dtype=np.uint8)), (False, None), (True, np.ones((48, 64, 3), dtype=np.uint8))]
    cap.read.side_effect = lambda: reads.pop(0) if reads else (True, np.zeros((48, 64, 3), dtype=np.uint8))
    cap.set.return_value = True
    mock_vc.return_value = cap
    adapter = CameraAdapter(source="demo/videos/replay.mp4", loop_video=True, min_reconnect_delay=0.01)
    adapter.start()
    boundary = None
    deadline = time.time() + 1.0
    while time.time() < deadline and boundary is None:
        _, meta = adapter.get_frame(timeout=0.05)
        if meta and meta.replay_boundary:
            boundary = meta
    adapter.stop(); adapter.join()
    assert boundary is not None
    assert boundary.replay_cycle == 1
    assert adapter.demo_replay is True


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_finite_demo_without_loop_terminates_at_eof(mock_vc):
    cap = mock.MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = 10.0
    cap.read.side_effect = [(True, np.zeros((8, 8, 3), dtype=np.uint8)), (False, None)]
    mock_vc.return_value = cap
    adapter = CameraAdapter(source="demo/videos/one-shot.avi", loop_video=False, min_reconnect_delay=0.01)
    adapter.start(); time.sleep(0.12)
    assert adapter.eof_reached is True
    adapter.stop(); adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_rtsp_eof_reconnects_instead_of_using_demo_rewind(mock_vc):
    cap = mock.MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = 10.0
    cap.read.return_value = (False, None)
    mock_vc.return_value = cap
    adapter = CameraAdapter(source="rtsp://camera/stream", min_reconnect_delay=0.01, max_reconnect_delay=0.02)
    adapter.start(); time.sleep(0.08)
    assert adapter.demo_replay is False
    assert adapter.replay_cycle == 0
    adapter.stop(); adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_demo_rewind_failure_is_bounded(mock_vc):
    cap = mock.MagicMock()
    cap.isOpened.return_value = True
    cap.get.return_value = 10.0
    cap.read.return_value = (False, None)
    cap.set.return_value = False
    mock_vc.return_value = cap
    adapter = CameraAdapter(source="demo/videos/broken.mp4", loop_video=True, min_reconnect_delay=0.001, max_reconnect_delay=0.005)
    adapter.start(); time.sleep(0.1)
    assert adapter.eof_reached is True
    assert adapter.state == StreamState.FAILED
    adapter.stop(); adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_initial_connection_success(mock_vc):
    # Test 1: initial connection success
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, mock.MagicMock())
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.1)
    assert adapter.state == StreamState.CONNECTED
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_initial_connection_failure(mock_vc):
    # Test 2: initial connection failure
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = False
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.05)
    assert adapter.state == StreamState.RECONNECTING
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_queue_boundedness_and_drop_oldest(mock_vc):
    # Test 11, 12: queue boundedness, DROP_OLDEST behavior
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    
    # Generate distinct frames
    def side_effect():
        return True, mock.MagicMock()
    
    mock_cap.read.side_effect = side_effect
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", max_queue_depth=5)
    adapter.start()
    
    time.sleep(0.2)
    adapter.stop()
    adapter.join()
    
    assert adapter.frames_received > 5
    assert adapter.frames_dropped > 0
    assert adapter._queue.qsize() <= 5


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_stall_detection(mock_vc):
    # Test 5, 9: stall detection after first frame
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    
    call_count = [0]
    def read_side_effect():
        call_count[0] += 1
        if call_count[0] <= 1:
            return True, mock.MagicMock()
        # Simulate stall by returning True but doing nothing or sleeping
        time.sleep(0.2)
        return True, mock.MagicMock()
    
    mock_cap.read.side_effect = read_side_effect
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", frame_stall_timeout_seconds=0.1)
    adapter.start()
    
    # Wait for the first frame and then the stall
    time.sleep(0.3)
    assert adapter.state in (StreamState.STALLING, StreamState.RECONNECTING)
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_reconnect_success_after_failure(mock_vc):
    # Test 3: reconnect success
    mock_cap_fail = mock.MagicMock()
    mock_cap_fail.isOpened.return_value = False
    
    mock_cap_success = mock.MagicMock()
    mock_cap_success.isOpened.return_value = True
    mock_cap_success.read.return_value = (True, mock.MagicMock())
    
    mock_vc.side_effect = [mock_cap_fail, mock_cap_success]

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.1)
    assert adapter.state == StreamState.CONNECTED
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_decoder_exception(mock_vc):
    # Test 14: decoder exception
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.side_effect = Exception("Decoder failure")
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.1)
    # The exception should be caught, read fails, transitions to stalling/reconnecting
    assert adapter.state in (StreamState.STALLING, StreamState.RECONNECTING)
    
    adapter.stop()
    adapter.join()


def test_queue_timeout_behavior():
    # Test 13: queue timeout behavior
    adapter = CameraAdapter(source="rtsp://test")
    # Don't start the thread
    frame, meta = adapter.get_frame(timeout=0.01)
    assert frame is None
    assert meta is None
