from datetime import datetime
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.api.audit import get_audit_logs
from backend.models.orm import AuditLog, Base, User


@pytest.fixture()
def audit_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    admin = User(
        id="11111111-1111-1111-1111-111111111111",
        username="admin",
        hashed_password="not-used",
        role="ADMIN",
        is_active=True,
    )
    auditor = User(
        id="22222222-2222-2222-2222-222222222222",
        username="auditor",
        hashed_password="not-used",
        role="AUDITOR",
        is_active=True,
    )
    timestamp = datetime(2026, 10, 3, 3, 56, 43)
    session.add_all([
        admin,
        auditor,
        AuditLog(
            id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            user_id=admin.id,
            action="LOGIN_SUCCESS",
            timestamp=timestamp,
            ip_address="10.0.0.1",
            success=True,
        ),
        AuditLog(
            id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            action="EDGE_KEY_BOOTSTRAPPED",
            resource_type="Camera",
            resource_id="cam-border-01",
            timestamp=timestamp,
            ip_address="10.0.0.2",
            success=True,
        ),
        AuditLog(
            id="cccccccc-cccc-cccc-cccc-cccccccccccc",
            action="LOGIN_FAILED",
            timestamp=timestamp,
            ip_address="10.0.0.3",
            detail="username=admin",
            success=False,
        ),
        AuditLog(
            id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            user_id=auditor.id,
            action="EVIDENCE_URL_GENERATED",
            resource_type="Event",
            resource_id="event-1",
            timestamp=datetime(2026, 10, 2, 12, 0, 0),
            success=True,
        ),
    ])
    session.commit()
    try:
        yield session, admin, auditor
    finally:
        session.close()
        engine.dispose()


def _fetch(db, user, **overrides):
    parameters = {
        "request": None,
        "skip": 0,
        "limit": 50,
        "action": None,
        "user_id": None,
        "current_user": user,
        "db": db,
        **overrides,
    }
    return get_audit_logs(**parameters)


def test_timestamps_and_actor_types_are_authoritative(audit_db):
    db, admin, _auditor = audit_db
    result = _fetch(db, admin)

    assert result["logs"][0]["id"].startswith("cccccccc")
    assert result["logs"][0]["timestamp"] == "2026-10-03T03:56:43Z"
    assert result["logs"][0]["actor_type"] == "UNAUTHENTICATED"
    assert result["logs"][0]["attempted_username"] == "admin"
    assert result["logs"][1]["actor_type"] == "SYSTEM"
    assert result["logs"][2]["actor_type"] == "USER"
    assert result["logs"][2]["username"] == "admin"


def test_pagination_is_deterministic_for_equal_timestamps(audit_db):
    db, admin, _auditor = audit_db
    first = _fetch(db, admin, limit=2)
    second = _fetch(db, admin, skip=2, limit=2)

    assert [row["id"][0] for row in first["logs"]] == ["c", "b"]
    assert [row["id"][0] for row in second["logs"]] == ["a", "d"]
    assert first["total"] == 4
    assert first["has_newer"] is False
    assert first["has_older"] is True
    assert second["has_newer"] is True
    assert second["has_older"] is False


def test_existing_action_and_user_filters_are_preserved(audit_db):
    db, admin, auditor = audit_db
    action = _fetch(db, admin, action="LOGIN_FAILED")
    attributed = _fetch(db, admin, user_id=auditor.id)

    assert action["total"] == 1
    assert action["logs"][0]["actor_type"] == "UNAUTHENTICATED"
    assert attributed["total"] == 1
    assert attributed["logs"][0]["username"] == "auditor"


@pytest.mark.parametrize("role", ["ADMIN", "AUDITOR"])
def test_admin_and_auditor_remain_authorized(audit_db, role):
    db, _admin, _auditor = audit_db
    assert _fetch(db, SimpleNamespace(role=role))["total"] == 4


def test_operator_remains_unauthorized(audit_db):
    db, _admin, _auditor = audit_db
    with pytest.raises(HTTPException) as exc:
        _fetch(db, SimpleNamespace(role="OPERATOR"))
    assert exc.value.status_code == 403


def test_audit_router_introduces_no_mutating_endpoint():
    from backend.api.audit import router

    audit_methods = set().union(*(route.methods or set() for route in router.routes))
    assert audit_methods <= {"GET"}
