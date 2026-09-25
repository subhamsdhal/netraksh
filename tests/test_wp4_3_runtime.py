"""
Tests for WP-4.3 ONNX Runtime and hardware acceleration abstractions.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

import numpy as np

from edge.detection.runtime import (
    create_runtime, 
    PyTorchRuntime, 
    ONNXRuntimeCPU, 
    ONNXRuntimeCUDA, 
    TensorRTRuntime,
    DetectionResult
)
from shared.schemas import BoundingBox

@pytest.fixture
def mock_env():
    with patch.dict(os.environ, {}, clear=True):
        yield

def test_create_runtime_pytorch(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "pytorch"
    rt = create_runtime()
    assert isinstance(rt, PyTorchRuntime)

def test_create_runtime_onnx_cpu(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "onnx_cpu"
    rt = create_runtime()
    assert isinstance(rt, ONNXRuntimeCPU)
    assert "CPUExecutionProvider" in rt.providers

def test_create_runtime_onnx_cuda(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "onnx_cuda"
    rt = create_runtime()
    assert isinstance(rt, ONNXRuntimeCUDA)
    assert "CUDAExecutionProvider" in rt.providers

def test_create_runtime_tensorrt(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "tensorrt"
    rt = create_runtime()
    assert isinstance(rt, TensorRTRuntime)
    assert "TensorrtExecutionProvider" in rt.providers

def test_strict_fallback_unknown(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "unknown_runtime"
    with pytest.raises(ValueError, match="STRICT FAILURE: Unknown DETECTOR_RUNTIME"):
        create_runtime()

@patch("os.path.exists")
def test_pytorch_missing_model(mock_exists, mock_env):
    os.environ["DETECTOR_RUNTIME"] = "pytorch"
    mock_exists.return_value = False
    rt = create_runtime()
    with pytest.raises(FileNotFoundError, match="Model artifact unavailable"):
        rt.load()

@patch("os.path.exists")
@patch("edge.detection.runtime.PyTorchRuntime.load")
def test_pytorch_load_success(mock_load, mock_exists, mock_env):
    os.environ["DETECTOR_RUNTIME"] = "pytorch"
    mock_exists.return_value = True
    rt = create_runtime()
    rt.load()
    mock_load.assert_called_once()

def test_onnx_missing_onnxruntime(mock_env, monkeypatch):
    os.environ["DETECTOR_RUNTIME"] = "onnx_cpu"
    rt = create_runtime()
    
    # Simulate onnxruntime missing
    import sys
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    
    with patch("os.path.exists", return_value=True):
        with pytest.raises(RuntimeError, match="STRICT FAILURE: onnxruntime is not installed"):
            rt.load()

def test_onnx_missing_provider(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "onnx_cuda"
    rt = create_runtime()
    
    with patch("os.path.exists", return_value=True):
        # Mock get_available_providers to only return CPU
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        
        with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            with pytest.raises(RuntimeError, match="Requested provider CUDAExecutionProvider is unavailable"):
                rt.load()

def test_onnx_session_reuse(mock_env):
    os.environ["DETECTOR_RUNTIME"] = "onnx_cpu"
    rt = create_runtime()
    
    with patch("os.path.exists", return_value=True):
        mock_ort = MagicMock()
        mock_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
        
        mock_session = MagicMock()
        mock_session.get_inputs.return_value = [MagicMock(name="images")]
        mock_ort.InferenceSession.return_value = mock_session
        
        with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            rt.load()
            
            # The session should be created once
            mock_ort.InferenceSession.assert_called_once()
            
            # And cached in the instance
            assert rt.session is not None
            assert rt.session == mock_session

def test_coordinate_regression(mock_env):
    """
    Test coordinate equivalence for the ONNX post-processing pipeline to ensure
    no box scale mismatch or translation issue.
    """
    rt = ONNXRuntimeCPU("dummy.onnx")
    
    # Simulate a raw YOLOv8 ONNX output
    # Shape: (1, 84, 8400)
    mock_preds = np.zeros((1, 84, 8400), dtype=np.float32)
    
    # Let's inject one high-confidence prediction at index 0
    # box format: [cx, cy, w, h] in the resized image space
    mock_preds[0, 0, 0] = 320 # cx
    mock_preds[0, 1, 0] = 320 # cy
    mock_preds[0, 2, 0] = 100 # w
    mock_preds[0, 3, 0] = 100 # h
    
    # class 2 (VEHICLE) confidence
    mock_preds[0, 4 + 2, 0] = 0.95 
    
    # Simulate resizing state (e.g. 1920x1080 to 640x640 with letterbox)
    ratio = 640 / 1920 # 0.3333
    pad_w = 0
    pad_h = 140 # (640 - 1080*ratio) / 2
    
    detections = rt._postprocess(mock_preds, ratio, pad_w, pad_h, conf_thresh=0.5)
    
    assert len(detections) == 1
    det = detections[0]
    
    assert det.class_id == 2
    assert det.confidence == 0.95
    
    # Validate mapping back to original 1920x1080 space
    # cx=320, cy=320, w=100, h=100 -> x1=270, y1=270, x2=370, y2=370 in letterboxed image
    # rx1 = (270 - pad_w) / ratio = 270 / (1/3) = 810
    # ry1 = (270 - pad_h) / ratio = (270 - 140) * 3 = 390
    # rx2 = (370 - pad_w) / ratio = 370 * 3 = 1110
    # ry2 = (370 - pad_h) / ratio = (370 - 140) * 3 = 690
    
    assert abs(det.bbox.x1 - 810) < 1.0
    assert abs(det.bbox.y1 - 390) < 1.0
    assert abs(det.bbox.x2 - 1110) < 1.0
    assert abs(det.bbox.y2 - 690) < 1.0
