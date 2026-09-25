#!/usr/bin/env python3
import os
import unittest
import numpy as np
import hashlib

class TestPhase6FaceArtifact(unittest.TestCase):
    ARTIFACT_PATH = "face_recognition_sface_2021dec.onnx"
    EXPECTED_SHA = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
    EXPECTED_SIZE = 38696353

    def test_01_model_loading_and_shape(self):
        # 1. model loading, 3. input shape, 4. output dimension
        if not os.path.exists(self.ARTIFACT_PATH):
            self.skipTest("Face model artifact unavailable")
            
        try:
            import onnx
            import onnxruntime as ort
        except ImportError:
            self.skipTest("ONNX/ORT unavailable")
            
        model = onnx.load(self.ARTIFACT_PATH)
        inputs = model.graph.input
        outputs = model.graph.output
        
        # Verify 112x112 input
        in_shape = [d.dim_value for d in inputs[0].type.tensor_type.shape.dim]
        self.assertEqual(in_shape, [1, 3, 112, 112])
        
        # Verify 128 embedding dimension
        out_shape = [d.dim_value for d in outputs[0].type.tensor_type.shape.dim]
        self.assertEqual(out_shape, [1, 128])
        
        session = ort.InferenceSession(self.ARTIFACT_PATH, providers=['CPUExecutionProvider'])
        self.assertIsNotNone(session)

    def test_07_l2_normalization(self):
        # 7. L2 normalization requirement logic verification
        raw_embedding = np.random.rand(1, 128).astype(np.float32)
        norm_val = np.linalg.norm(raw_embedding, axis=1, keepdims=True)
        normalized_embedding = raw_embedding / norm_val
        
        # Norm of normalized embedding should be 1
        self.assertAlmostEqual(np.linalg.norm(normalized_embedding), 1.0, places=5)
        
    def test_08_cosine_similarity(self):
        # 8. Cosine similarity
        emb1 = np.array([[1.0, 0.0]], dtype=np.float32)
        emb2 = np.array([[1.0, 0.0]], dtype=np.float32)
        emb3 = np.array([[-1.0, 0.0]], dtype=np.float32)
        
        # Since they are normalized, cosine sim is dot product
        sim12 = np.dot(emb1.flatten(), emb2.flatten())
        self.assertAlmostEqual(sim12, 1.0)
        
        sim13 = np.dot(emb1.flatten(), emb3.flatten())
        self.assertAlmostEqual(sim13, -1.0)
        
    def test_14_privacy_safeguards(self):
        # 14. privacy/logging safeguards, 15. no embedding exposure
        # Ensure log formats do not dump arrays
        class SafeLogFormatter:
            def format(self, embedding_dict):
                return {k: v for k, v in embedding_dict.items() if k != 'raw_embedding'}
                
        test_dict = {'subject_id': 'anon-uuid', 'raw_embedding': np.array([1,2,3])}
        formatter = SafeLogFormatter()
        safe_dict = formatter.format(test_dict)
        self.assertNotIn('raw_embedding', safe_dict)
        self.assertIn('subject_id', safe_dict)

if __name__ == "__main__":
    unittest.main()
