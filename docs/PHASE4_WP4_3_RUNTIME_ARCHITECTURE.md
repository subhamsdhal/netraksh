# Phase 4 WP-4.3: Runtime Architecture

## Abstraction
NETRAKSH Edge implements a strict Strategy Pattern for the detector runtime. 
The core orchestrator (`DetectionTracker`) no longer calls PyTorch or ONNX directly. Instead, it relies on a `DetectorRuntime` factory (`edge/detection/runtime.py`).

```text
DetectorRuntime (Abstract)
    ├── PyTorchRuntime (Default)
    ├── ONNXRuntimeCPU
    ├── ONNXRuntimeCUDA
    └── TensorRTRuntime (Optional)
```

## Normalization Boundary
Every runtime must produce a normalized `List[DetectionResult]` that strips framework-specific tensor representations. 
The format is tightly typed: `BoundingBox(x1, y1, x2, y2)`, `confidence`, and `class_id`.

## Tracker Independence
Because trackers (ByteTrack / BoT-SORT) require numpy arrays or standard torch tensors in a specific layout, the normalized `DetectionResult` list is converted back into a `(N, 6)` array structure and fed to the runtime-agnostic tracker wrapper. This ensures tracking behavior is identical regardless of which execution provider performed the detection.

## Strict Selection and Fallback
If the `DETECTOR_RUNTIME` environment variable requests a specific accelerator (e.g. `onnx_cuda`), the startup process verifies:
1. `onnxruntime` is installed.
2. `CUDAExecutionProvider` is available.
3. The specified model artifact exists.

If any requirement is unmet, the system fails to start. There is NO silent fallback to PyTorch or CPU execution. Operators must explicitly deploy compatible hardware or intentionally reconfigure the system to `pytorch` to restore operation.
