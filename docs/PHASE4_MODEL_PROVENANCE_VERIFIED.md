# Phase 4 Model Provenance Matrix: Verified Status

*Date: 2026-09-14 | Forensic Status: WP-1 Provenance Audit*

## TRACK A: ANPR Plate Localizer

| ATTRIBUTE | VALUE |
| :--- | :--- |
| **CANDIDATE MODEL** | `keremberke/yolov8n-license-plate` |
| **SOURCE URL** | HuggingFace Model Hub |
| **EXACT REPOSITORY** | `keremberke/yolov8n-license-plate` |
| **EXACT WEIGHTS FILE** | Not downloaded |
| **CODE LICENSE** | AGPL-3.0 (Ultralytics) |
| **WEIGHTS LICENSE** | Claimed CC-BY 4.0 (Roboflow dataset) but exact checkpoint license file is unavailable without download |
| **COMMERCIAL-USE STATUS** | Unclear (Requires confirming no proprietary datasets were mixed) |
| **REDISTRIBUTION STATUS** | Unverified |
| **INTENDED-USE RESTRICTIONS** | Unverified |
| **VERIFICATION STATUS** | **UNVERIFIED — DO NOT INTEGRATE** |
| **JUSTIFICATION** | Cannot securely verify the exact artifact-level license restrictions without pulling arbitrary checkpoints from HuggingFace. Assumption of SIH or CC-BY applicability is prohibited. |

## TRACK B: Face Embedding (InsightFace)

| ATTRIBUTE | VALUE |
| :--- | :--- |
| **CANDIDATE MODEL** | ArcFace (`glintr100.onnx` / `w600k_r50.onnx`) |
| **SOURCE URL** | `https://github.com/deepinsight/insightface` |
| **EXACT REPOSITORY** | `deepinsight/insightface` |
| **EXACT WEIGHTS FILE** | Not downloaded |
| **CODE LICENSE** | MIT |
| **WEIGHTS LICENSE** | Non-commercial research only |
| **COMMERCIAL-USE STATUS** | STRICTLY PROHIBITED (Requires separate enterprise contact) |
| **REDISTRIBUTION STATUS** | STRICTLY PROHIBITED for commercial |
| **INTENDED-USE RESTRICTIONS** | Academic/Research only |
| **VERIFICATION STATUS** | **UNVERIFIED — DO NOT INTEGRATE** |
| **JUSTIFICATION** | Pretrained weights explicitly restrict commercial use. Extrapolating permission from the "SIH context" is prohibited by the execution mandate. We do not have a commercially cleared artifact. |

---

## DECISION

- **TRACK A**: BLOCKED on provenance.
- **TRACK B**: BLOCKED on provenance.

No models will be downloaded. No integration code will be written.
