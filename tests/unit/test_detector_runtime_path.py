"""Regression tests for selecting the artifact used by each detector runtime."""

from edge.main import resolve_detector_model_path


def test_onnx_cpu_validates_its_onnx_artifact(monkeypatch):
    monkeypatch.setenv("DETECTOR_RUNTIME", "onnx_cpu")
    monkeypatch.setenv("DETECTOR_MODEL_ONNX", "models/yolov8n.onnx")
    monkeypatch.setenv("YOLO_MODEL_PATH", "models/yolov8n.pt")

    assert resolve_detector_model_path({}) == "models/yolov8n.onnx"


def test_pytorch_keeps_configured_pt_artifact(monkeypatch):
    monkeypatch.setenv("DETECTOR_RUNTIME", "pytorch")
    monkeypatch.setenv("DETECTOR_MODEL_ONNX", "models/yolov8n.onnx")

    assert resolve_detector_model_path({"model_size": "models/yolov8n.pt"}) == "models/yolov8n.pt"
