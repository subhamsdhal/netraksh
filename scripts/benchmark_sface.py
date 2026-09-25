import os
import time
import cv2
import numpy as np
import onnxruntime as ort

from edge.detection.face_align import FaceAligner
from edge.detection.face_embedding import SFaceEmbeddingModel

def benchmark():
    model_path = "face_recognition_sface_2021dec.onnx"
    if not os.path.exists(model_path):
        print("NOT EXECUTED - ENVIRONMENT BLOCKED (Model missing)")
        return
        
    print("=== SFACE BENCHMARK ===")
    print("Warming up...")
    
    # Setup
    aligner = FaceAligner((112, 112))
    model = SFaceEmbeddingModel(model_path)
    
    image = np.random.randint(0, 256, (300, 300, 3), dtype=np.uint8)
    landmarks = np.array([
        [100, 100], [200, 100], [150, 150], [120, 200], [180, 200]
    ], dtype=np.float32)
    
    # Warmup
    for _ in range(5):
        aligned = aligner.align(image, None, landmarks)["aligned_face"]
        emb = model.embed(aligned)
        
    iterations = 100
    
    # 1. Alignment timing
    t0 = time.time()
    for _ in range(iterations):
        aligned = aligner.align(image, None, landmarks)["aligned_face"]
    t1 = time.time()
    align_ms = ((t1 - t0) / iterations) * 1000
    
    # 2. Preprocess timing
    t0 = time.time()
    for _ in range(iterations):
        blob = cv2.dnn.blobFromImage(aligned, 1.0, (112, 112), (0, 0, 0), swapRB=True, crop=False)
    t1 = time.time()
    prep_ms = ((t1 - t0) / iterations) * 1000
    
    # 3. Inference timing
    t0 = time.time()
    for _ in range(iterations):
        net_out = model.session.run([model.output_name], {model.input_name: blob})[0]
    t1 = time.time()
    inf_ms = ((t1 - t0) / iterations) * 1000
    
    # 4. Normalization timing
    t0 = time.time()
    for _ in range(iterations):
        embedding = net_out.flatten()
        norm = np.linalg.norm(embedding)
        normed = embedding / norm
    t1 = time.time()
    norm_ms = ((t1 - t0) / iterations) * 1000
    
    # 5. Similarity timing
    emb1 = np.random.rand(128).astype(np.float32)
    emb2 = np.random.rand(128).astype(np.float32)
    t0 = time.time()
    for _ in range(iterations):
        score = float(np.dot(emb1, emb2))
    t1 = time.time()
    sim_ms = ((t1 - t0) / iterations) * 1000
    
    # Total timing
    total_ms = align_ms + prep_ms + inf_ms + norm_ms + sim_ms
    
    print(f"Alignment:     {align_ms:.3f} ms")
    print(f"Preprocessing: {prep_ms:.3f} ms")
    print(f"Inference:     {inf_ms:.3f} ms")
    print(f"Normalization: {norm_ms:.3f} ms")
    print(f"Similarity:    {sim_ms:.3f} ms")
    print("-" * 25)
    print(f"Total / Face:  {total_ms:.3f} ms")

if __name__ == "__main__":
    benchmark()
