import cv2
import json
import os
import sys
from ultralytics import YOLO

def main():
    video_path = "demo/videos/vtest.mp4"
    out_path = "demo/videos/vtest_telemetry.json"
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Failed to open {video_path}")
        return
        
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0
        
    model = YOLO("yolov8n.pt")
    
    telemetry_cache = []
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        video_time = frame_idx / fps
        frame_h, frame_w = frame.shape[:2]
        
        # We only want bounding boxes and track IDs.
        results = model.track(frame, persist=True, tracker="bytetrack.yaml", conf=0.25, verbose=False)
        
        frame_tracks = []
        if len(results) > 0:
            res = results[0]
            if res.boxes is not None and res.boxes.id is not None:
                boxes = res.boxes.xyxy.cpu().numpy()
                ids = res.boxes.id.cpu().numpy()
                confs = res.boxes.conf.cpu().numpy()
                classes = res.boxes.cls.cpu().numpy()
                
                for i in range(len(ids)):
                    cls_id = int(classes[i])
                    # Person or vehicle classes (0: person, 2: car, 3: motorcycle, 5: bus, 7: truck)
                    if cls_id not in [0, 2, 3, 5, 7]:
                        continue
                    
                    det_class = "person" if cls_id == 0 else "vehicle"
                    x1, y1, x2, y2 = boxes[i]
                    frame_tracks.append({
                        "track_id": int(ids[i]),
                        "detection_class": det_class,
                        "confidence": float(confs[i]),
                        "bbox_x": float(x1) / frame_w if frame_w > 0 else 0.0,
                        "bbox_y": float(y1) / frame_h if frame_h > 0 else 0.0,
                        "bbox_w": float(x2 - x1) / frame_w if frame_w > 0 else 0.0,
                        "bbox_h": float(y2 - y1) / frame_h if frame_h > 0 else 0.0,
                    })
            
        telemetry_cache.append({
            "video_time": video_time,
            "frame_idx": frame_idx,
            "tracks": frame_tracks
        })
        
        frame_idx += 1
        if frame_idx % 10 == 0:
            print(f"Processed {frame_idx} frames...")
            sys.stdout.flush()
            
    with open(out_path, "w") as f:
        json.dump(telemetry_cache, f)
        
    print(f"Saved {len(telemetry_cache)} frames to {out_path}")

if __name__ == "__main__":
    print("Starting cache generation...")
    sys.stdout.flush()
    main()
