# PHASE 6: SFACE ALIGNMENT

## Status
VERIFIED

## Verification Summary
We evaluated the existing `FaceAligner` implementation (using ArcFace 112x112 standard landmarks via `skimage.transform.SimilarityTransform`) against the reference OpenCV `cv2.FaceRecognizerSF.alignCrop()` method.

## Key Findings
- **Landmark Coordinates**: SFace uses the standard ArcFace 112x112 layout:
  ```python
  [[38.2946, 51.6963],  # Right eye (image-left)
   [73.5318, 51.5014],  # Left eye (image-right)
   [56.0252, 71.7366],  # Nose tip
   [41.5493, 92.3655],  # Right mouth corner
   [70.7299, 92.2041]]  # Left mouth corner
  ```
- **Interpolation Differences**: `cv2.warpAffine` using LMEDS (what OpenCV uses natively) vs `skimage`'s SimilarityTransform produces a maximum pixel difference of `7` on an 8-bit image scale.
- **Output Target Size**: `112 x 112` pixels.
- **Geometrical Impact on Embedding**: The embedding generated from our existing `FaceAligner` vs OpenCV's reference `alignCrop` yielded a cosine similarity of `0.999981`.

## Conclusion
The current `FaceAligner` is fully compatible with SFace. There is no need to embed alignment logic directly inside `SFaceEmbeddingModel`.
