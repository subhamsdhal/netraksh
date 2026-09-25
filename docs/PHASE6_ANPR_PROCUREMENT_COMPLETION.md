# Phase 6: ANPR Procurement Completion (Inspection)

ARTIFACT:
`license_plate_detection_lpd_yunet_2023mar.onnx`

SOURCE:
`https://github.com/opencv/opencv_zoo/raw/main/models/license_plate_detection_yunet/license_plate_detection_lpd_yunet_2023mar.onnx`

LICENSE:
Apache 2.0 (Verified via OpenCV Zoo Repository)

WEIGHTS LICENSE:
Apache 2.0 (Verified via Official Maintainers)

DATASET:
CCPD (Academic original)

COMMERCIAL USE:
VERIFIED (Allowed via Apache 2.0)

REDISTRIBUTION:
VERIFIED (Allowed via Apache 2.0)

SHA-256:
`6d4978a7b6d25514d5e24811b82bfb511d166bdd8ca3b03aa63c1623d4d039c7`

ONNX:
PASSED (IR Version 6, Valid Structure)

INPUT:
`input [1, 3, 240, 320]` (Float32)

OUTPUT:
`loc [4385, 14]`, `conf [4385, 2]`, `iou [4385, 1]`

COORDINATES:
PASSED (Decodes into 4-corner bounding boxes, requires mapping to standard [x,y,w,h])

SECURITY:
PASSED (No unsafe hooks or external calls)

BENCHMARK:
NOT EXECUTED (Environment Blocked)

INTEGRATION:
NOT PERFORMED

CURRENT DEFAULT:
`HeuristicPlateLocalizer`

NEXT:
ANPR BENCHMARK + CONTROLLED INTEGRATION GATE
