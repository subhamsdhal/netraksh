#!/usr/bin/env python3
"""
NETRAKSH Phase 6: ANPR Artifact Inspection Test Suite

Target: LPD_YuNet (OpenCV Zoo)
Validates the structural properties, contract, and runtime footprint of the artifact.
"""
import os
import hashlib
import unittest

class TestANPRArtifact(unittest.TestCase):
    ARTIFACT_PATH = "lpd_yunet.onnx"
    EXPECTED_SHA256 = "6d4978a7b6d25514d5e24811b82bfb511d166bdd8ca3b03aa63c1623d4d039c7"
    EXPECTED_SIZE = 4146213

    def test_01_artifact_exists(self):
        """1. Artifact exists"""
        self.assertTrue(os.path.exists(self.ARTIFACT_PATH), "Artifact missing from expected path")

    def test_02_artifact_sha256_and_size(self):
        """2. Artifact SHA-256 and size verification"""
        size = os.path.getsize(self.ARTIFACT_PATH)
        self.assertEqual(size, self.EXPECTED_SIZE, "File size mismatch")
        
        with open(self.ARTIFACT_PATH, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(file_hash, self.EXPECTED_SHA256, "Artifact SHA-256 hash mismatch")

    def test_03_valid_onnx_structure(self):
        """3. Valid ONNX / Structural requirements"""
        try:
            import onnx
        except ImportError:
            self.skipTest("ONNX not installed, skipping structural checks (NOT EXECUTED - ENVIRONMENT BLOCKED)")
            
        model = onnx.load(self.ARTIFACT_PATH)
        onnx.checker.check_model(model)
        
        # Extract inputs/outputs
        inputs = model.graph.input
        outputs = model.graph.output
        
        self.assertTrue(len(inputs) > 0, "No inputs found")
        self.assertTrue(len(outputs) > 0, "No outputs found")
        
        # 4. Expected Input (YuNet typically uses 'input')
        self.assertEqual(inputs[0].name, "input")
        
        # 5. Expected Output (YuNet outputs 'loc' and 'conf')
        out_names = [o.name for o in outputs]
        self.assertIn("loc", out_names)
        self.assertIn("conf", out_names)

    def test_12_runtime_initialization(self):
        """12. Runtime Initializes without crashing"""
        try:
            import onnxruntime as ort
        except ImportError:
            self.skipTest("ONNXRuntime not installed, skipping (NOT EXECUTED - ENVIRONMENT BLOCKED)")
            
        try:
            session = ort.InferenceSession(self.ARTIFACT_PATH, providers=['CPUExecutionProvider'])
            self.assertIsNotNone(session)
        except Exception as e:
            self.fail(f"ONNXRuntime failed to initialize: {e}")

if __name__ == "__main__":
    unittest.main(verbosity=2)
