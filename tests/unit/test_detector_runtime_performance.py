import sys
from types import SimpleNamespace

import numpy as np

from edge.detection.runtime import ONNXRuntimeCPU


def test_onnx_session_is_created_once_and_reused_across_frames(monkeypatch, tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"test-model-placeholder")
    created = []

    class _Options:
        def add_session_config_entry(self, *_args):
            pass

    class _Session:
        def __init__(self):
            self.runs = 0

        def get_inputs(self):
            return [SimpleNamespace(name="images")]

        def run(self, *_args):
            self.runs += 1
            return [np.zeros((1, 84, 2100), dtype=np.float32)]

    def _create_session(*_args, **_kwargs):
        session = _Session()
        created.append(session)
        return session

    fake_ort = SimpleNamespace(
        SessionOptions=_Options,
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        get_available_providers=lambda: ["CPUExecutionProvider"],
        InferenceSession=_create_session,
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setenv("DETECTOR_INPUT_SIZE", "320")

    runtime = ONNXRuntimeCPU(str(model))
    runtime.load()
    frame = np.zeros((180, 320, 3), dtype=np.uint8)
    runtime.detect(frame, 0.25)
    runtime.detect(frame, 0.25)

    assert len(created) == 1
    assert created[0].runs == 3  # one warmup plus two real frames
    assert runtime.session is created[0]
