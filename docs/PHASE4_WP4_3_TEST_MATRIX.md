# Phase 4 WP-4.3: Test Matrix

## Test Suite: `tests/test_wp4_3_runtime.py`

| Test Case | Description | Status |
|---|---|---|
| `test_create_runtime_pytorch` | Validates `pytorch` selects `PyTorchRuntime`. | EXECUTABLE |
| `test_create_runtime_onnx_cpu` | Validates `onnx_cpu` selects `ONNXRuntimeCPU` + providers. | EXECUTABLE |
| `test_create_runtime_onnx_cuda` | Validates `onnx_cuda` selects `ONNXRuntimeCUDA` + providers. | EXECUTABLE |
| `test_create_runtime_tensorrt` | Validates `tensorrt` selects `TensorRTRuntime` + providers. | EXECUTABLE |
| `test_strict_fallback_unknown` | Validates invalid runtime crashes startup. | EXECUTABLE |
| `test_pytorch_missing_model` | Validates missing `.pt` file crashes startup. | EXECUTABLE |
| `test_pytorch_load_success` | Validates `YOLO` init on valid model. | EXECUTABLE |
| `test_onnx_missing_onnxruntime`| Validates missing `onnxruntime` import crashes startup. | EXECUTABLE |
| `test_onnx_missing_provider` | Validates missing provider (e.g. CUDA) crashes startup. | EXECUTABLE |
| `test_onnx_session_reuse` | Validates ONNX inference session is created exactly once. | EXECUTABLE |
| `test_coordinate_regression` | Validates BBOX post-processing scale/padding conversion. | EXECUTABLE |

## Regression Execution
**STATUS:** NOT EXECUTED — ENVIRONMENT BLOCKED
*Test file implemented, but actual pytest execution over native modules requires a working Python environment.*
