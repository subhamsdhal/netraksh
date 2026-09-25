# LPD_YuNet Decoding Reference

## Quadrilateral Construction
LPD_YuNet infers bounding boxes not as axis-aligned rectangles `[x,y,w,h]`, but as sets of four distinct corners. 
The anchor generation process follows an FPN-style generation:
```python
feature_maps = [feature_map_3th, feature_map_4th, feature_map_5th, feature_map_6th]
min_sizes = [[10, 16, 24], [32, 48], [64, 96], [128, 192, 256]]
```

### Coordinate Decode
The tensor indices decode offsets to the anchors:
- Corner 1: `loc[:, 4:6]`
- Corner 2: `loc[:, 6:8]`
- Corner 3: `loc[:, 10:12]`
- Corner 4: `loc[:, 12:14]`

### NMS Subtlety
The OpenCV Zoo implementation passes `dets[:, 0:4]` to `cv2.dnn.NMSBoxes`, passing corner 1 and corner 2 components instead of a bounding box. Our integration faithfully executes this exact behavior to retain equivalence with the author's reference logic before calculating final coordinate offsets back to the `vehicle_crop` scaling factor.
