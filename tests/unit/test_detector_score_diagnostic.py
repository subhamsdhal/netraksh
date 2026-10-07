"""Confidence diagnostics must retain pre-filter person scores."""

import numpy as np

from edge.detection.runtime import ONNXRuntimeCPU


def test_person_score_survives_confidence_rejection():
    runtime = ONNXRuntimeCPU("unused.onnx")
    predictions = np.zeros((1, 84, 2), dtype=np.float32)
    predictions[0, :4, :] = np.array([[100, 200], [100, 200], [40, 40], [80, 80]])
    predictions[0, 4, :] = [0.42, 0.11]

    detections = runtime._postprocess(predictions, 1.0, 0.0, 0.0, 0.45)

    assert detections == []
    assert runtime.last_threshold_count == 0
    assert abs(runtime.last_max_person_confidence - 0.42) < 0.0001
