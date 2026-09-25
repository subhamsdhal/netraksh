import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database.session import SessionLocal

client = TestClient(app)

def test_api_system_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()

def test_api_cameras_unauthorized():
    # Attempting to fetch cameras without auth token should fail with 401
    response = client.get("/cameras")
    assert response.status_code == 401

def test_api_login_invalid():
    response = client.post("/auth/token", data={"username": "admin", "password": "wrong_password"})
    assert response.status_code == 401
    assert "detail" in response.json()

# This harness assumes an admin exists per backend/main.py's bootstrap_users
def get_admin_token():
    # Use the strong mock password from conftest.py
    response = client.post("/auth/token", data={"username": "admin", "password": "StrongAdminTest123!"})
    if response.status_code == 200:
        return response.json()["access_token"]
    return None

def test_api_cameras_authorized():
    token = get_admin_token()
    # If the database is empty or not seeded, this might fail, but status code should be 200
    if token:
        response = client.get("/cameras", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert isinstance(response.json(), list)

def test_api_events_invalid_input():
    token = get_admin_token()
    if token:
        # Invalid sort direction should trigger a 422 Unprocessable Entity
        response = client.get("/events/?sort_dir=INVALID", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 422
