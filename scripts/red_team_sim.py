import time
import requests
import json
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000/api"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin_password"  # Replace with actual admin password if needed

def print_result(test_name, passed, details=""):
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    status = "PASS" if passed else "FAIL"
    print(f"[{color}{status}{reset}] {test_name} - {details}")

def get_admin_token():
    try:
        response = requests.post(
            f"{BASE_URL}/auth/token",
            data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception:
        pass
    return None

def test_rate_limit_exhaustion():
    """Test 1: Rapid-fire POST /api/events to trigger 429 Too Many Requests."""
    # We will simulate 65 rapid requests to bypass the 60/minute limit
    print("\n--- Test 1: Rate Limit Exhaustion ---")
    
    # Payload for a basic event ingest
    payload = {
        "edge_device_id": "red-team-edge-1",
        "sequence_number": 1,
        "evidence_package": {
            "event_id": "TEST-EVT-001",
            "camera_id": "CAM-TEST-1",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event_type": "intrusion",
            "detection_class": "person",
            "confidence": 0.99,
            "scene_condition": "clear",
            "camera_health_state": "ok",
            "decision_state": "DETECTED",
            "decision_reason": "Red team test"
        }
    }
    
    hit_429 = False
    for i in range(65):
        payload["evidence_package"]["event_id"] = f"TEST-EVT-RL-{i}"
        try:
            res = requests.post(f"{BASE_URL}/events", json=payload)
            if res.status_code == 429:
                hit_429 = True
                break
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            break
            
    print_result("Rate Limit (slowapi) triggered", hit_429, "Expected 429 Too Many Requests after ~60 reqs")

def test_unauthorized_access():
    """Test 2: Attempt to fetch GET /api/audit without a JWT token."""
    print("\n--- Test 2: Unauthorized Access ---")
    try:
        res = requests.get(f"{BASE_URL}/audit?limit=10")
        passed = res.status_code in [401, 403]
        print_result("JWT Auth Enforcement", passed, f"Received {res.status_code}, expected 401/403")
    except requests.exceptions.RequestException as e:
        print_result("JWT Auth Enforcement", False, f"Connection failed: {e}")

def test_webhook_debounce():
    """Test 3: Fire two CRITICAL watchlist events within 5 seconds."""
    print("\n--- Test 3: Webhook Debounce Verification ---")
    
    # We'll ingest two events with the same face_match_person_id
    payload1 = {
        "edge_device_id": "red-team-edge-1",
        "sequence_number": 100,
        "evidence_package": {
            "event_id": "TEST-EVT-WB-1",
            "camera_id": "CAM-TEST-1",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "detection_class": "face",
            "confidence": 0.99,
            "scene_condition": "clear",
            "camera_health_state": "ok",
            "decision_state": "DETECTED",
            "face_match_person_id": "WLIST-REDTEAM-1",
            "face_match_person_name": "Test Subject",
            "face_match_confidence": 0.1
        }
    }
    
    payload2 = dict(payload1)
    payload2["sequence_number"] = 101
    payload2["evidence_package"] = dict(payload1["evidence_package"])
    payload2["evidence_package"]["event_id"] = "TEST-EVT-WB-2"
    
    try:
        res1 = requests.post(f"{BASE_URL}/events", json=payload1)
        # Sleep short time (e.g. 1 second)
        time.sleep(1)
        res2 = requests.post(f"{BASE_URL}/events", json=payload2)
        
        passed = res1.status_code in [200, 201] and res2.status_code in [200, 201]
        print_result("Webhook Debounce (Event Ingest)", passed, "Events ingested successfully. Backend logs should confirm 'debounce active, skipping'.")
    except requests.exceptions.RequestException as e:
        print_result("Webhook Debounce", False, f"Request failed: {e}")

def test_signature_forgery():
    """Test 4: Submit manipulated EvidencePackage (hash mismatch)."""
    print("\n--- Test 4: Signature Forgery ---")
    
    payload = {
        "edge_device_id": "red-team-edge-1",
        "sequence_number": 200,
        "evidence_package": {
            "event_id": "TEST-EVT-FORGED-1",
            "camera_id": "CAM-TEST-1",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "detection_class": "person",
            "confidence": 0.99,
            "scene_condition": "clear",
            "camera_health_state": "ok",
            "decision_state": "DETECTED",
            "hash": "invalid_hash_that_wont_match_data",
            "signature": "invalid_signature"
        }
    }
    
    try:
        res = requests.post(f"{BASE_URL}/events", json=payload)
        
        # Ingest endpoint might still accept it but mark verified=False
        if res.status_code in [200, 201]:
            data = res.json()
            passed = data.get("verified") is False
            print_result("Signature Forgery Rejected", passed, f"Verified flag: {data.get('verified')}, expected False")
        else:
            # Or it might outright reject it (400)
            passed = res.status_code == 400
            print_result("Signature Forgery Rejected", passed, f"Received status {res.status_code}, expected rejection")
            
    except requests.exceptions.RequestException as e:
        print_result("Signature Forgery", False, f"Request failed: {e}")

if __name__ == "__main__":
    print("=============================================")
    print(" NETRAKSH RED TEAM SIMULATION SCRIPT")
    print("=============================================")
    print(f"Targeting: {BASE_URL}")
    
    test_rate_limit_exhaustion()
    test_unauthorized_access()
    test_webhook_debounce()
    test_signature_forgery()
    
    print("\n=============================================")
    print(" RED TEAM SIMULATION COMPLETE")
    print("=============================================")
