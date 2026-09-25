# PHASE 6: SFACE TEST MATRIX

## Status
PASSED

## Integration Tests
The `tests/test_phase6_sface_integration.py` matrix includes the following verified configurations:

1. **Feature Flag Defaults (test_01)**: `FACE_RECOGNITION_ENGINE` correctly defaults to `lbph`, completely bypassing SFace setup.
2. **Artifact Discovery (test_02)**: Configured SFace path loads the `ONNX` file dynamically.
3. **Missing Model Handling (test_03)**: A missing `.onnx` file blocks `SFaceEmbeddingModel` from starting. With fallback disabled, `WatchlistFaceRecognizer` does not silently swap the engine.
4. **Explicit Fallback (test_04)**: If `FACE_FALLBACK_TO_LBPH=true` and SFace fails to load, the engine securely drops back to `LBPH`.
5. **Preprocessing & Output Dimension (test_05)**: Verified standard input `(112, 112, 3)` outputs `[1, 128]` embedding with mathematically finite L2-norm of `1.0`.
6. **Resource Pressure Omission (test_06)**: If `resource_pressure=True` is triggered (e.g. from the ANPR queue being saturated), SFace returns `NOT_EVALUATED_RESOURCE_PRESSURE` immediately, avoiding identity false-negatives.
7. **LBPH Regression (test_07)**: With LBPH as the target, the API responds correctly via the `cv2.face` cascade, unmodified by the facade addition.

All tests execute cleanly via `pytest`.
