import cv2
import numpy as np
import onnxruntime as ort
import os
import itertools

def test_preprocessing():
    model_path = "face_recognition_sface_2021dec.onnx"
    
    # Generate random face image
    image = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    
    face_box = np.array([
        50, 50, 200, 200,
        100, 100, 200, 100, 150, 150, 120, 200, 180, 200, 0.99
    ], dtype=np.float32)
    
    recognizer = cv2.FaceRecognizerSF.create(model_path, "")
    aligned_ref = recognizer.alignCrop(image, face_box)
    feature_ref = recognizer.feature(aligned_ref)
    feature_ref_normalized = feature_ref / np.linalg.norm(feature_ref)
    
    session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
    
    scales = [1.0, 1.0/255.0, 1.0/128.0]
    means = [(0,0,0), (127.5, 127.5, 127.5), (104.0, 117.0, 123.0)]
    swapRBs = [False, True]
    
    for scale, mean, swapRB in itertools.product(scales, means, swapRBs):
        input_blob = cv2.dnn.blobFromImage(aligned_ref, scale, (112, 112), mean, swapRB=swapRB, crop=False)
        feature_dir = session.run(["fc1"], {"data": input_blob})[0]
        
        feature_dir_normalized = feature_dir / np.linalg.norm(feature_dir)
        
        diff = np.max(np.abs(feature_ref_normalized.flatten() - feature_dir_normalized.flatten()))
        
        if diff < 1e-4:
            print(f"MATCH FOUND: scale={scale}, mean={mean}, swapRB={swapRB}")
            return
            
    print("NO EXACT MATCH FOUND")

if __name__ == "__main__":
    test_preprocessing()
