# Phase 6: ANPR Model Provenance Records

## 1. Primary Candidate: YOLOv8n-LPD (Ultralytics)
- **Model Name:** YOLOv8n-license-plate
- **Repository:** `https://github.com/ultralytics/ultralytics`
- **Official Policy:** Ultralytics distributes YOLOv8 under the **AGPL-3.0** license. Commercial, proprietary use without open-sourcing the backend requires an Enterprise License (cite: `https://ultralytics.com/license`).
- **Exact Artifact (Example):** `yolov8n-lpd.onnx`
- **Version:** YOLOv8.2
- **Format:** ONNX
- **Input Shape:** `1x3x640x640`
- **Output Shape:** `1x6x8400`
- **Code License:** AGPL-3.0
- **Weights License:** AGPL-3.0 (Trained by a 3rd party on Roboflow but inherited viral AGPL structure)
- **Dataset License:** CC-BY 4.0 (Roboflow standard)
- **Commercial Use:** RESTRICTED (Unless Enterprise License procured)
- **Redistribution:** Allowed under AGPL-3.0 terms
- **Provenance Status:** `UNVERIFIED — DO NOT DOWNLOAD` (Rejected dynamically based on commercial AGPL taint without explicit enterprise override).

## 2. Backup Candidate: LPD_YuNet (OpenCV Zoo)
- **Model Name:** LPD_YuNet
- **Repository:** `https://github.com/opencv/opencv_zoo/tree/main/models/license_plate_detection_yunet`
- **Exact Artifact:** `license_plate_detection_lpd_yunet_2023mar.onnx`
- **Version:** 2023mar
- **Format:** ONNX
- **Input Shape:** Dynamic (e.g., `1x3x320x320`)
- **Output Shape:** Custom Densebox coordinate format (Bbox + 4 Corners).
- **Code License:** Apache 2.0
- **Weights License:** Apache 2.0
- **Dataset License:** CCPD (Academic) -> Weights are released Apache 2.0 by the author.
- **Commercial Use:** ALLOWED (Apache 2.0)
- **Redistribution:** ALLOWED
- **Provenance Status:** `APPROVED FOR PROCUREMENT`
