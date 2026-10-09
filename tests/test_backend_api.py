import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from backend.main import app
from backend.database.session import get_db
from backend.models.orm import Base, User
from backend.security.auth import hash_password

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_api_database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as session:
        session.add(User(
            username="admin", hashed_password=hash_password("StrongAdminTest123!"),
            role="ADMIN", command_id="COMMAND_A", is_active=True,
        ))
        session.commit()

    def test_db():
        with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()

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

def get_admin_token():
    response = client.post("/auth/token", data={"username": "admin", "password": "StrongAdminTest123!"})
    assert response.status_code == 200
    return response.json()["access_token"]

def test_api_cameras_authorized():
    token = get_admin_token()
    response = client.get("/cameras", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_api_events_invalid_input():
    token = get_admin_token()
    # The supported limit parameter is bounded to 500.
    response = client.get("/events/?limit=501", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 422
