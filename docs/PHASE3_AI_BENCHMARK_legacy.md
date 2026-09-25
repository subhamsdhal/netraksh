# NETRAKSH Phase 3 AI Benchmark

*Generated on: Mon Sep 14 11:04:07 2026*

## 1. Environment
- **OS**: win32
- **Python**: 3.12.10
- **Hardware**: NOT MEASURED

## 2. Input Data
- **Resolution**: 1280x720
- **Source FPS**: 24.0
- **Frames Processed**: 90 (excl. 10 warmup)

## 3. Current Baseline Configuration
- **Detector**: yolov8n.pt
- **Tracker**: default

## 4. Detection Metrics
- **Mean Latency**: 33.00 ms (p95: 35.85 ms)
- **Effective FPS**: 30.3
- **Total Objects Detected**: 303
- **Precision/Recall**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 5. Tracking Metrics
- *(Integrated into Detection latency for YOLO+ByteTrack)*
- **Peak Active Tracks**: 4
- **IDF1/MOTA/ID Switches**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 6. Face Metrics
- **Face Processing Latency**: Included in Orchestrator
- **Matches/Unknowns**: 0
- **ROC/Accuracy**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 7. ANPR Metrics
- **OCR Latency**: Included in Orchestrator
- **OCR Attempts**: 0
- **Exact-Match Rate**: NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 8. Reliability Metrics
- **Mean Processing Latency**: 0.02 ms
- **R (Final Score) Mean**: 0.00

## 9. Scene-Condition Metrics
- **Mean Latency**: 9.67 ms

## 10. End-to-End Metrics
- **Mean Latency**: 42.72 ms (p95: 45.78 ms)
- **Mean Effective Throughput**: 23.4 FPS

## 11. Memory Metrics
- **RSS Before**: 54.97 MB
- **RSS Peak During**: 682.02 MB
- **RSS After**: 681.59 MB

## 12. Ground-Truth Availability
NOT MEASURABLE — NO GROUND TRUTH AVAILABLE

## 13. Metrics that are NOT MEASURABLE
- Precision, Recall, mAP, IDF1, MOTA, ID Switches, True OCR Accuracy, Face Recognition ROC are all **NOT MEASURABLE** at this time due to lack of ground truth labels for the evaluated videos.

## 14. Known Benchmark Limitations
- Face and ANPR latencies are grouped under Orchestrator latency due to current architecture coupling.
- No ground truth datasets currently exist in the repository to measure True Positives vs False Positives.

## 15. Reproduction Command
```bash
python -m edge.benchmark_runner --video <path_to_video>
```
