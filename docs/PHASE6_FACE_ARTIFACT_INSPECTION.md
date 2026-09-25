# Phase 6: Face Artifact Inspection

## Security Inspection
- **Valid ONNX File:** YES (Passes ORT structural checks).
- **Unexpected Payload:** None (Pure ONNX ProtoBuf).
- **Embedded Credentials:** None.
- **External Network Dependency:** None internally.
- **Unsafe Serialization:** None (Not a Python Pickle file).

## ONNX Structural Inspection
- **IR Version:** 6
- **Producer:** PyTorch
- **Input Node:**
  - `name`: `data`
  - `shape`: `[1, 3, 112, 112]`
  - `dtype`: Float32
- **Output Node:**
  - `name`: `fc1`
  - `shape`: `[1, 128]`
  - `dtype`: Float32
- **Embedding Dimension:** 128

## Input / Output Contract
- **PREPROCESSING:** 
  - Image is aligned via 5-point facial landmarks (right eye, left eye, nose, mouth right, mouth left).
  - OpenCV SFace uses `cv.dnn.blobFromImage` to resize to 112x112. 
  - Mean subtraction and standard deviation scaling are internally applied or expected by the model.
- **OUTPUT NORMALIZATION:** 
  - Raw embedding `[1, 128]` must be L2 normalized before cosine similarity operations.
- **ALIGNMENT:** 
  - Requires tightly cropped and rotated face aligned to expected standard facial landmarks matching the MS1M training standard (which SFace relies on).
