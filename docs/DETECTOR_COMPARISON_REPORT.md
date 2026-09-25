# DETECTOR COMPARISON REPORT (Phase 3 Step 4)

## 1. Executive Summary
This report documents the detector comparison between YOLOv8n and YOLOv8s.

## 2. Task-1163 Status
**PARTIALLY COMPLETE / BLOCKED**
YOLOv8n was successfully benchmarked. YOLOv8s was not benchmarked because the weight file is missing.

## 3. Current Detector Architecture
- YOLOv8n (default)
- ByteTrack Tracker
- Track Continuity Guard enabled

## 4. YOLOv8n Baseline
YOLOv8n: **BENCHMARKED**

## 5. YOLOv8s Candidate Verification
YOLOv8s: **NOT BENCHMARKED**
Reason: Candidate weight yolov8s.pt was not available locally and automatic download was intentionally disabled for reproducibility and security.

## 6. Benchmark Availability
YOLOv8n data available: YES
YOLOv8s data available: NO

## 7. YOLOv8n Measurements

### Video: vtest
- **model**: yolov8n.pt
- **weight path**: yolov8n.pt
- **hardware**: NOT MEASURED
- **resolution**: NOT MEASURED
- **source FPS**: NOT MEASURED
- **confidence threshold**: 0.3
- **tracker**: ByteTrack
- **mean latency**: 50.15 ms
- **median latency**: 49.41 ms
- **p95 latency**: 59.44 ms
- **effective FPS**: 19.9
- **peak RSS**: 1434.5859375 MB
- **total detections**: 6107
- **tracks created**: 749
- **tracks terminated**: 787

## 8. Pixel-Area Distribution
- **SMALL** (<32x32): 195
- **MEDIUM**: 5857
- **LARGE** (>96x96): 55

## 9. Tracker Interaction
- **ContinuityGuard interventions**: 710 (TRACK FRAGMENTATION / REASSOCIATION PROXY, NOT ID SWITCH COUNT)

### Video: demo
- **model**: yolov8n.pt
- **weight path**: yolov8n.pt
- **hardware**: NOT MEASURED
- **resolution**: NOT MEASURED
- **source FPS**: NOT MEASURED
- **confidence threshold**: 0.3
- **tracker**: ByteTrack
- **mean latency**: 52.85 ms
- **median latency**: 52.18 ms
- **p95 latency**: 61.73 ms
- **effective FPS**: 18.9
- **peak RSS**: 1051.02734375 MB
- **total detections**: 693
- **tracks created**: 4
- **tracks terminated**: 1

## 8. Pixel-Area Distribution
- **SMALL** (<32x32): 0
- **MEDIUM**: 163
- **LARGE** (>96x96): 530

## 9. Tracker Interaction
- **ContinuityGuard interventions**: 0 (TRACK FRAGMENTATION / REASSOCIATION PROXY, NOT ID SWITCH COUNT)

## 10. Ground-Truth Availability
No ground truth available for current benchmarks.

## 11. Metrics Not Measurable
- **Precision**: NOT MEASURABLE
- **Recall**: NOT MEASURABLE
- **F1**: NOT MEASURABLE
- **mAP**: NOT MEASURABLE

## 12. License / Provenance
- **Model Provenance**: Ultralytics
- **License**: AGPL-3.0

## 13. Current Limitations
Pixel-area categories are merely size bins, NOT real-world distance categories, because actual calibration is missing.

## 14. Exact Blocker for YOLOv8s
Missing verified yolov8s.pt file on the local filesystem. Auto-downloads are restricted.

## 15. Final Recommendation
YOLOv8n remains the current default. This is NOT a result proving YOLOv8n is superior to YOLOv8s. The comparison remains pending until a verified yolov8s.pt is supplied.

## 16. Requirements to Complete Detector Comparison
- Provisioning of a verified `yolov8s.pt` file.
- Re-running the benchmark suite against both models.