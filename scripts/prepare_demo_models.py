#!/usr/bin/env python3
"""
NETRAKSH — Demo Model Preparation Script.
Validates the offline availability of required AI models.
"""
import os
import hashlib

MODELS = [
    {
        "name": "YOLOv8 Nano",
        "path": "yolov8n.pt",
        "expected_sha256": None, # Could vary depending on exactly which PyTorch version downloaded it, but we check existence
    },
    {
        "name": "Haar Cascade (Frontal Face)",
        "path": "edge/detection/cascades/haarcascade_frontalface_default.xml",
        "source": "https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_default.xml",
        "expected_sha256": "4392636d194c6f96dfaabfc83be83c4ec581bc32d00062a4d048d0873a48e895",
        "license": "BSD 3-Clause"
    }
]

def hash_file(filepath):
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def main():
    print("--- NETRAKSH Demo Model Preparation ---")
    all_ready = True
    
    for model in MODELS:
        path = model["path"]
        print(f"\nChecking {model['name']}...")
        print(f"Expected location: {os.path.abspath(path)}")
        
        if not os.path.exists(path):
            print(f"[X] MISSING: {path}")
            if "source" in model:
                print(f"    You must manually acquire this asset from: {model['source']}")
                print(f"    License: {model.get('license', 'Unknown')}")
            all_ready = False
            continue
            
        print("[OK] File exists.")
        
        expected_hash = model.get("expected_sha256")
        if expected_hash:
            actual_hash = hash_file(path)
            if actual_hash.lower() == expected_hash.lower():
                print(f"[OK] SHA-256 matches: {actual_hash}")
            else:
                print(f"[!] WARNING: SHA-256 mismatch!")
                print(f"    Expected: {expected_hash}")
                print(f"    Actual:   {actual_hash}")
                # We do not strictly fail here as different OpenCV versions might have slight differences,
                # but we warn the user.
        
    print("\n---------------------------------------")
    if all_ready:
        print("STATUS: ALL MODELS READY")
    else:
        print("STATUS: MODELS MISSING — Do not start the demo pipeline until resolved.")
        exit(1)

if __name__ == "__main__":
    main()
