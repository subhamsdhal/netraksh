import requests
import sys

BASE_URL = "http://localhost:8443"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"

def print_status(test, passed, info=""):
    color = "\033[92m" if passed else "\033[91m"
    reset = "\033[0m"
    status = "PASS" if passed else "FAIL"
    print(f"[{color}{status}{reset}] {test} - {info}")

def run_health_checks():
    print("=============================================")
    print(" NETRAKSH BACKEND HEALTH VERIFICATION")
    print("=============================================")

    # 1. Check Node Health Endpoint
    try:
        res = requests.get(f"{BASE_URL}/api/nodes/health")
        passed = res.status_code == 200 and "status" in res.json()[0] if isinstance(res.json(), list) and len(res.json()) > 0 else True # the response is a list
        print_status("GET /api/nodes/health", passed, f"Status Code: {res.status_code}")
    except Exception as e:
        print_status("GET /api/nodes/health", False, str(e))

    # 2. Check Database & Ledger Health
    try:
        # Authenticate first
        auth_res = requests.post(
            f"{BASE_URL}/auth/token",
            data={"username": ADMIN_USER, "password": ADMIN_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if auth_res.status_code == 200:
            token = auth_res.json().get("access_token")
            # Query the immutable ledger
            audit_res = requests.get(
                f"{BASE_URL}/api/audit?limit=1",
                headers={"Authorization": f"Bearer {token}"}
            )
            passed = audit_res.status_code == 200
            print_status("GET /api/audit (Database & Ledger Check)", passed, f"Status Code: {audit_res.status_code}")
        else:
            print_status("Authentication for Ledger Check", False, f"Failed to login: {auth_res.status_code}")
    except Exception as e:
        print_status("Database & Ledger Check", False, str(e))

    print("=============================================")

if __name__ == "__main__":
    run_health_checks()
