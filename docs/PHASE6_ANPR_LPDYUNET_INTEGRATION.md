# LPD_YuNet Integration

## Pipeline Structure
- `PlateLocalizer` interface extended with `LPD_YuNetPlateLocalizer`.
- Inference occurs entirely within `edge/detection/anpr.py` behind the `EnhancedANPRModule`.

## Quadrilateral -> OCR Geometry
Instead of axis-aligned bounds that include background padding when the plate is angled, `LPD_YuNetPlateLocalizer` returns `PlateCrop` containing a full `quadrilateral: List[Tuple[float, float]]` parameter.

### OCR Preprocessor Update
When `quadrilateral` is passed, `OCRPreprocessor.process` leverages OpenCV `getPerspectiveTransform` and `warpPerspective` to flatten and tightly crop the plate geometry before feeding the thresholded image to EasyOCR.

## Failure Isolation
Errors within ONNX session initialization or malformed frame topologies yield graceful fallback, rejecting the frame locally and allowing the tracker to persist without pipeline crashes.
