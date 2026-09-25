# Phase 4 Model Provenance Matrix

*Forensic Check: DO NOT integrate any model marked UNVERIFIED.*

## 1. Plate Localization (ANPR)

| ATTRIBUTE | VALUE |
| :--- | :--- |
| **MODEL** | YOLOv8-license-plate (Candidate) |
| **SOURCE URL** | Unknown / Community (e.g., HuggingFace/Ultralytics Hub) |
| **EXACT REPOSITORY** | Unverified |
| **EXACT WEIGHTS FILE** | Unverified |
| **FRAMEWORK** | PyTorch / Ultralytics |
| **INFERENCE FORMAT** | ONNX |
| **LICENSE OF CODE** | AGPL-3.0 (Ultralytics YOLOv8) |
| **LICENSE OF WEIGHTS** | Unknown |
| **TRAINING DATA LICENSE** | Unknown |
| **COMMERCIAL-USE STATUS** | Unverified (AGPL requires open-source of whole app if linked, unless Enterprise licensed) |
| **REDISTRIBUTION STATUS** | Unverified |
| **MODIFICATION STATUS** | Unverified |
| **MODEL SIZE** | ~6MB (nano) |
| **INPUT SHAPE** | 1x3x640x640 |
| **OUTPUT CONTRACT** | Bounding box (x,y,w,h,conf,class) |
| **HARDWARE REQUIREMENT** | CPU / Edge GPU |
| **VERIFICATION STATUS** | **UNVERIFIED — DO NOT INTEGRATE** |

## 2. Face Detection

| ATTRIBUTE | VALUE |
| :--- | :--- |
| **MODEL** | RetinaFace (Candidate) |
| **SOURCE URL** | `https://github.com/serengil/retinaface` |
| **EXACT REPOSITORY** | `serengil/retinaface` |
| **EXACT WEIGHTS FILE** | `Resnet50` / `MobileNet` |
| **FRAMEWORK** | TensorFlow / PyTorch |
| **INFERENCE FORMAT** | ONNX |
| **LICENSE OF CODE** | MIT |
| **LICENSE OF WEIGHTS** | Unverified (Often restricted to Academic/Non-commercial) |
| **TRAINING DATA LICENSE** | WIDER FACE (Non-commercial research only) |
| **COMMERCIAL-USE STATUS** | Unverified / Highly Risky |
| **REDISTRIBUTION STATUS** | Unverified |
| **MODIFICATION STATUS** | Unverified |
| **MODEL SIZE** | ~30MB (MobileNet) |
| **INPUT SHAPE** | 1x3xHxW |
| **OUTPUT CONTRACT** | Bounding box + 5 Facial Landmarks |
| **HARDWARE REQUIREMENT** | Edge GPU Recommended |
| **VERIFICATION STATUS** | **UNVERIFIED — DO NOT INTEGRATE** |

## 3. Face Embedding

| ATTRIBUTE | VALUE |
| :--- | :--- |
| **MODEL** | ArcFace (Candidate) |
| **SOURCE URL** | `https://github.com/deepinsight/insightface` |
| **EXACT REPOSITORY** | `deepinsight/insightface` |
| **EXACT WEIGHTS FILE** | e.g., `w600k_r50.onnx` or `glintr100` |
| **FRAMEWORK** | MXNet / PyTorch |
| **INFERENCE FORMAT** | ONNX |
| **LICENSE OF CODE** | MIT |
| **LICENSE OF WEIGHTS** | Unverified (Many InsightFace models are strictly Non-Commercial) |
| **TRAINING DATA LICENSE** | MS-Celeb-1M / Glint360K (Non-commercial research only) |
| **COMMERCIAL-USE STATUS** | Unverified / Highly Risky |
| **REDISTRIBUTION STATUS** | Unverified |
| **MODIFICATION STATUS** | Unverified |
| **MODEL SIZE** | ~100MB |
| **INPUT SHAPE** | 1x3x112x112 (Aligned Face Crop) |
| **OUTPUT CONTRACT** | 512-D L2-Normalized Float Vector |
| **HARDWARE REQUIREMENT** | GPU Recommended |
| **VERIFICATION STATUS** | **UNVERIFIED — DO NOT INTEGRATE** |

*Note: Proceeding with Phase 4 WP-1 or WP-2 requires explicitly verifying and acquiring commercial/open licenses for the chosen models before any code is written.*
