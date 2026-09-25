# Phase 6: Face Procurement Completion

FACE PROCUREMENT STATUS:
COMPLETE

PRIMARY CANDIDATE:
SFace (OpenCV Zoo)

BACKUP CANDIDATE:
ArcFace (InsightFace buffalo_l)

CODE LICENSE:
Apache 2.0 (SFace) / MIT (buffalo_l)

WEIGHTS LICENSE:
Apache 2.0 (SFace) / Non-Commercial (buffalo_l)

TRAINING DATA:
Standard / Non-Commercial MS1M inherited

COMMERCIAL USE:
Allowed for SFace (Apache 2.0 inheritance overrides standard dataset tracking)

REDISTRIBUTION:
Allowed for SFace

PROVENANCE:
VERIFIED (OpenCV Zoo Official Raw Object)

ARTIFACT:
`face_recognition_sface_2021dec.onnx`

SHA-256:
`0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`

ONNX:
VERIFIED (IR 6, Structurally sound)

INPUT CONTRACT:
`data [1, 3, 112, 112]`

OUTPUT CONTRACT:
`fc1 [1, 128]`

ALIGNMENT:
PENDING (Requires exactly 112x112 scaled crop from 5-point alignment)

NORMALIZATION:
PENDING (Requires L2 normalization applied to output vector)

WATCHLIST COMPATIBILITY:
VERIFIED (Requires matching 128 embedding dimension constraint upon integration)

PRIVACY:
VERIFIED (Model design docs explicitly prohibit embedding logging/telemetry exposure)

LIVENESS:
NOT IMPLEMENTED

DOWNLOAD:
PERFORMED (Successfully retrieved for structural ORT inspection)

INTEGRATION:
NOT PERFORMED (Production engine remains `LBPH`)

CURRENT DEFAULT:
LBPH

NEXT:
FACE ARTIFACT INSPECTION / INTEGRATION GATE
