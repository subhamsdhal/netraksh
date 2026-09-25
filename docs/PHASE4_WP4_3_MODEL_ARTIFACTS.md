# Phase 4 WP-4.3: Model Artifacts

## Verified Base Model
- **Filename:** `yolov8n.pt`
- **Source:** Ultralytics (Pretrained COCO)
- **Status:** EXECUTABLE
- **SHA-256:** NOT MEASURED — ENVIRONMENT BLOCKED

## Accelerated Artifacts (ONNX)
- **Filename:** `yolov8n.onnx`
- **Source Artifact:** `yolov8n.pt`
- **Export Tool:** `ultralytics.YOLO.export(format="onnx")`
- **Export Configuration:** `opset=12, simplify=True, dynamic=False, imgsz=640`
- **Runtime Compatibility:** ONNX CPU, ONNX CUDA, TensorRT
- **Status:** NOT AVAILABLE — EXPORT BLOCKED BY ENVIRONMENT
- **SHA-256:** NOT MEASURED — ENVIRONMENT BLOCKED

## Accelerated Artifacts (TensorRT)
- **Filename:** `yolov8n.engine`
- **Status:** DEFERRED — TARGET HARDWARE UNAVAILABLE
- **SHA-256:** NOT MEASURED — ENVIRONMENT BLOCKED

*No generated artifacts have been approved for production deployment until benchmarking finishes.*
