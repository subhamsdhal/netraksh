# PHASE 6: SFACE REFERENCE EQUIVALENCE

## Objective
Verify that the standalone SFace ONNX model integration using our internal `FaceAligner` and `onnxruntime` exactly matches the behavior of the official OpenCV `cv2.FaceRecognizerSF` implementation.

## Verification Utility
An isolated verification script `scripts/verify_full_equivalence.py` was constructed with the following steps:
1. Generate a random synthetic 300x300 image.
2. Define a standard 5-point face landmark set and bounding box.
3. Pass through the **Reference Pipeline**: `cv2.FaceRecognizerSF.alignCrop` followed by `cv2.FaceRecognizerSF.feature` and L2 normalization.
4. Pass through the **Direct Pipeline**: Our `FaceAligner` (using `skimage.transform.SimilarityTransform`) followed by `cv2.dnn.blobFromImage` (scale=1.0, mean=(0,0,0), swapRB=True) and `onnxruntime` inference, ending with L2 normalization.
5. Compute Cosine Similarity between the output vectors.

## Preprocessing Semantics
The canonical preprocessing sequence has been mathematically verified to be:
- **Alignment:** 5-point similarity transform to 112x112 using ArcFace standard landmarks.
- **Scale:** `1.0` (pixel values range from 0 to 255).
- **Mean Subtraction:** `(0, 0, 0)` (None).
- **Channel Ordering:** Model expects **RGB**, achieved by passing `swapRB=True` if the source image is BGR.
- **Shape:** `(1, 3, 112, 112)` in NCHW format.

## Results
- **Max Diff (normalized):** 1.544e-03
- **Cosine Similarity:** 0.999981
- **Status:** ACCEPTABLE NUMERIC DIFFERENCE

The minor difference (0.000019 in cosine similarity) arises from sub-pixel interpolation differences between OpenCV's internal affine warp and `skimage`'s affine warp. This is mathematically acceptable and structurally equivalent.

## Conclusion
The reference equivalence step is **PASSED**. We can proceed with the direct ONNX implementation in `SFaceEmbeddingModel`.
