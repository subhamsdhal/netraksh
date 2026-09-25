# Phase 6: Planning Gate Report

PHASE 6:
PLANNED

ANPR DATA REQUIREMENTS:
DEFINED (Requires COCO-style bounding box + transcript mapping with condition slices)

FACE DATA REQUIREMENTS:
DEFINED (Requires bounding box + pseudonymous identity + impostor pairs with condition slices)

MODEL PROVENANCE:
DESIGNED (Strict schema for license, weights hash, and runtime bounds)

ANPR METRICS:
DEFINED (IoU, CER, Latency)

FACE METRICS:
DEFINED (ROC, TAR@FAR, Latency)

TEMPORAL EVALUATION:
DEFINED (Frame-level vs. Track-level consensus evaluation)

CONDITION SLICING:
DEFINED (Day/Night, Blur, Occlusion, Pose, Distance)

PRIVACY:
ENFORCED (No logging of raw tensors, face images, or credentials. Internal pseudonymization only)

EVALUATION HARNESS:
IMPLEMENTED (`scripts/phase6_evaluate_anpr.py` and `scripts/phase6_evaluate_face.py`)

DATASET DOWNLOAD:
NOT PERFORMED

MODEL DOWNLOAD:
NOT PERFORMED

INTEGRATION:
NOT PERFORMED

NEXT IMPLEMENTATION PACKAGE:
ANPR MODEL PROCUREMENT
