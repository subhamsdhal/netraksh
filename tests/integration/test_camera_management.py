"""Isolated HTTP tests for Camera Management registration and location mutations."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import cameras
from backend.database.session import get_db
from backend.models.orm import AuditLog, Base, Camera, CameraHealth, CameraKey, EdgeIdentity, User
from backend.security.auth import create_access_token


@pytest.fixture
def camera_api(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'camera-management.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    users = {
        role: User(
            id=str(uuid.uuid4()),
            username=f"{role.lower()}-camera-test",
            hashed_password="unused",
            role=role,
            command_id="COMMAND_A",
            is_active=True,
        )
        for role in ("ADMIN", "OPERATOR", "AUDITOR")
    }
    session.add_all(users.values())
    session.commit()

    app = FastAPI()
    app.include_router(cameras.router)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, session, users
    session.close()
    engine.dispose()


def _headers(user: User) -> dict[str, str]:
    token = create_access_token({"sub": user.username, "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def _register(client, user, **overrides):
    payload = {"name": "Gate Camera", "location": "Sector 9", **overrides}
    return client.post("/cameras", json=payload, headers=_headers(user))


def test_registration_requires_admin(camera_api):
    client, session, users = camera_api
    response = _register(client, users["OPERATOR"])
    assert response.status_code == 403
    assert session.query(Camera).count() == 0


def test_location_update_requires_admin(camera_api):
    client, session, users = camera_api
    camera = Camera(id="location-rbac", name="RBAC", location="Test", owning_command_id="COMMAND_A")
    session.add(camera)
    session.commit()

    response = client.put(
        "/cameras/location-rbac/location",
        json={"latitude": 1.0, "longitude": 2.0},
        headers=_headers(users["AUDITOR"]),
    )
    assert response.status_code == 403
    session.refresh(camera)
    assert camera.latitude is None and camera.longitude is None


def test_valid_registration_without_coordinates_uses_generated_id(camera_api):
    client, session, users = camera_api
    response = _register(client, users["ADMIN"], name="  Border Gamma  ", location="  Sector 9  ")
    assert response.status_code == 201
    camera_id = response.json()["camera_id"]
    uuid.UUID(camera_id)
    assert camera_id != "Border Gamma"
    camera = session.get(Camera, camera_id)
    assert (camera.name, camera.location) == ("Border Gamma", "Sector 9")
    assert camera.latitude is None and camera.longitude is None


def test_valid_registration_with_both_coordinates_including_zero(camera_api):
    client, session, users = camera_api
    response = _register(client, users["ADMIN"], latitude=0, longitude=0.0)
    assert response.status_code == 201
    camera = session.get(Camera, response.json()["camera_id"])
    assert camera.latitude == 0.0
    assert camera.longitude == 0.0


@pytest.mark.parametrize(
    "coordinates",
    [
        {"latitude": 10.0},
        {"longitude": 20.0},
        {"latitude": -90.01, "longitude": 0.0},
        {"latitude": 90.01, "longitude": 0.0},
        {"latitude": 0.0, "longitude": -180.01},
        {"latitude": 0.0, "longitude": 180.01},
    ],
)
def test_invalid_or_partial_coordinates_are_rejected(camera_api, coordinates):
    client, session, users = camera_api
    response = _register(client, users["ADMIN"], **coordinates)
    assert response.status_code == 422
    assert session.query(Camera).count() == 0


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_coordinates_are_rejected(camera_api, literal):
    client, session, users = camera_api
    response = client.post(
        "/cameras",
        json={
            "name": "Gate Camera",
            "location": "Sector 9",
            "latitude": literal,
            "longitude": 0,
        },
        headers=_headers(users["ADMIN"]),
    )
    assert response.status_code == 422
    assert session.query(Camera).count() == 0


@pytest.mark.parametrize("name", ["", "   "])
def test_empty_display_name_is_rejected(camera_api, name):
    client, session, users = camera_api
    response = _register(client, users["ADMIN"], name=name)
    assert response.status_code == 422
    assert session.query(Camera).count() == 0


def test_registration_creates_safe_admin_audit_and_no_edge_resources(camera_api):
    client, session, users = camera_api
    response = _register(client, users["ADMIN"], latitude=12.5, longitude=77.5)
    assert response.status_code == 201
    camera_id = response.json()["camera_id"]

    entry = session.query(AuditLog).filter(AuditLog.action == "CAMERA_REGISTERED").one()
    assert entry.user_id == users["ADMIN"].id
    assert entry.resource_type == "Camera"
    assert entry.resource_id == camera_id
    assert entry.success is True
    assert json.loads(entry.detail) == {
        "display_name": "Gate Camera",
        "physical_location": "Sector 9",
        "coordinates_supplied": True,
    }
    assert session.query(CameraHealth).count() == 0
    assert session.query(CameraKey).count() == 0
    assert session.query(EdgeIdentity).count() == 0


def test_location_update_creates_admin_audit_for_camera(camera_api):
    client, session, users = camera_api
    camera = Camera(id="location-audit", name="Audit", location="Test", owning_command_id="COMMAND_A")
    session.add(camera)
    session.commit()

    response = client.put(
        "/cameras/location-audit/location",
        json={"latitude": -12.25, "longitude": 130.5},
        headers=_headers(users["ADMIN"]),
    )
    assert response.status_code == 200
    entry = session.query(AuditLog).filter(AuditLog.action == "CAMERA_LOCATION_UPDATED").one()
    assert entry.user_id == users["ADMIN"].id
    assert entry.resource_type == "Camera"
    assert entry.resource_id == "location-audit"
    assert entry.success is True
    assert json.loads(entry.detail) == {"latitude": -12.25, "longitude": 130.5}


@pytest.mark.parametrize("role", ["ADMIN", "OPERATOR", "AUDITOR"])
def test_camera_list_remains_readable_by_authorized_roles(camera_api, role):
    client, session, users = camera_api
    session.add(Camera(id="readable-camera", name="Readable", location="Test", owning_command_id="COMMAND_A"))
    session.commit()
    response = client.get("/cameras", headers=_headers(users[role]))
    assert response.status_code == 200
    assert response.json()[0]["camera_id"] == "readable-camera"

