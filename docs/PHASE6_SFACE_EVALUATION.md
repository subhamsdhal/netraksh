# PHASE 6: SFACE EVALUATION

## Status
NOT MEASURABLE — NO VALID GROUND TRUTH

## Ground Truth Availability
The NETRAKSH repository does not currently contain a border-specific CCTV face dataset annotated with ground truth identities. 

## Benchmark Accuracy
While the official OpenCV SFace model reports `99.60%` on LFW (Labeled Faces in the Wild), we **do not claim** this as the expected production accuracy. LFW consists of clean, largely frontal web photos. Border CCTV data involves:
- Off-axis poses (pitch/yaw)
- Extreme low light and IR illumination (night vision)
- Severe motion blur
- Low resolution (small faces)
- Partial occlusion (sunglasses, masks, hats, vehicle glare)

## Threshold Calibration
- **Initial Status**: NOT CALIBRATED.
- **Current Value**: `0.363` (OpenCV reference default for Cosine Similarity).

## Condition Slices
No local data exists to evaluate:
- Day / Night
- Frontal / Profile
- Small face / Long range

A dedicated evaluation dataset must be constructed from real border footage to calibrate `FACE_MATCH_THRESHOLD` before promoting SFace to production default.
