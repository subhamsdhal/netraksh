# Phase 6: ANPR Artifact Inspection

## Security Inspection
- **Valid ONNX File:** YES (Passes `onnx.checker.check_model`)
- **Unexpected Payload:** None (Pure ONNX ProtoBuf)
- **Embedded Credentials:** None
- **External Network Dependency:** None internally.
- **Unsafe Serialization:** None (Not a Python Pickle file).

## ONNX Structural Inspection
- **IR Version:** 6
- **Producer:** pytorch
- **Input Node:** 
  - `name`: `input`
  - `shape`: `[1, 3, 240, 320]` (Though dynamic heights/widths are typically supported via prior generation)
  - `dtype`: Float32
- **Output Nodes:** 
  - `loc` `[4385, 14]` (Contains BBox and 5 landmarks/corners)
  - `conf` `[4385, 2]` (Classification confidence)
  - `iou` `[4385, 1]` (IoU confidence adjustment)

## Input / Output Contract
- **PREPROCESS:** `cv.dnn.blobFromImage(image)`. Normalization is built into OpenCV's `blobFromImage` defaults (no mean subtraction, scale=1.0) or handled internally.
- **INFERENCE:** Forward pass generates `loc`, `conf`, `iou`.
- **POSTPROCESS:** 
  - Generates grid priors based on min sizes `[[10, 16, 24], [32, 48], [64, 96], [128, 192, 256]]` and feature map steps.
  - Decodes confidences: `scores = np.sqrt(cls_scores * iou_scores)`.
  - Decodes `loc` into a 4-corner bounding box (8 coordinates).
- **COORDINATE MAPPING:** `dets = np.hstack((bboxes, scores))` yielding a `(N, 9)` matrix.
- **NMS BEHAVIOR:** 
  - Uses `cv.dnn.NMSBoxes(bboxes=dets[:, 0:4], scores=dets[:, -1])`.
  - Important Note: OpenCV Zoo explicitly maps the first 4 coordinates of the 8-corner array into the NMS. Since it represents a quadrilateral, we must carefully wrap this into the standard `[x, y, w, h]` required by our downstream `EasyOCR` normalizer.

## Edge Compatibility
- **Python / OpenCV:** COMPATIBLE
- **ONNX Runtime:** COMPATIBLE (CPU Execution Provider verified)
- **Future GPU:** COMPATIBLE (CUDA/TensorRT Execution Providers supported natively by ORT)
