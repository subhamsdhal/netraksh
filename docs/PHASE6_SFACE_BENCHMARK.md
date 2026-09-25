# PHASE 6: SFACE BENCHMARK

## Execution Status
EXECUTED

## Environment
- **Device**: CPU (Intel x86_64, Windows)
- **Framework**: ONNXRuntime (CPUExecutionProvider), single-threaded execution

## Benchmark Results (Averaged over 100 iterations)

| Stage | Latency (ms) | Notes |
| :--- | :--- | :--- |
| **Alignment** | 0.170 | `skimage.transform.SimilarityTransform` |
| **Preprocessing** | 0.042 | `cv2.dnn.blobFromImage` |
| **Inference (CPU)** | 20.445 | `ONNXRuntime` |
| **Normalization** | < 0.001 | `numpy.linalg.norm` |
| **Cosine Similarity** | < 0.001 | `numpy.dot` |
| **Total Pipeline** | **20.657** | Face Recognition per face crop |

## Comparison vs LBPH
The SFace embedding extraction takes ~20.6ms on CPU. This is heavier than LBPH's near-instantaneous `predict()`, but highly acceptable for a real-time RTSP stream. A single core can process roughly 48 faces per second purely for recognition, easily exceeding a standard 10 FPS security camera feed assuming 1-2 faces per frame.

## Scalability
Vector search (Cosine Similarity) is practically instantaneous for watchlists under 10,000 subjects. If the watchlist grows significantly, an external vector database (like Qdrant or Milvus) is required, but the edge implementation limits local embeddings to a smaller subset to avoid memory bloat.
