"""
NETRAKSH — Unit tests for backend/services/escalation.py, including the
cross-camera-corroboration boost wired in alongside
backend/services/cross_camera.py.

Regression coverage (existing behavior, must be unchanged): HIGH severity
escalates on its own; MEDIUM/LOW do not, with or without corroboration
below the boost threshold. New coverage: MEDIUM + strong real corroboration
now escalates, transparently marked escalated_via_corroboration=True; LOW
is never boosted regardless of corroboration strength.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.orm import Alert, Base, Event, Zone
from backend.services.escalation import (
    CORROBORATION_BOOST_MIN_TC,
    CORROBORATION_BOOST_SEVERITY,
    check_and_escalate,
)
from shared.constants import Severity


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_event(session, event_id="ev-1", severity=None, corroboration_score=None, zone_id=None):
    ev = Event(
        id=event_id, camera_id="cam-a", zone_id=zone_id,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        detection_class="person", confidence=0.9,
        scene_condition="CLEAR_DAY", camera_health_state="OK",
        decision_state="DETECTED", severity=severity,
        corroboration_score=corroboration_score,
    )
    session.add(ev)
    session.flush()
    return ev


def _make_boundary_zone(session, zone_id="zone-1", adjacent_command_id="COMMAND_B"):
    zone = Zone(
        id=zone_id, camera_id="cam-a", name="Boundary Zone", zone_type="fence",
        polygon_json="[]", owning_command_id="COMMAND_A",
        adjacent_command_id=adjacent_command_id,
    )
    session.add(zone)
    session.flush()
    return zone


class TestHighSeverityUnchanged:
    """Regression: HIGH severity's own escalation behavior must be exactly
    as before this boost was added."""

    def test_high_severity_with_no_zone_creates_alert_not_boosted(self, db_session):
        ev = _make_event(db_session, severity=Severity.HIGH.value)
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert is not None
        assert alert.escalated_via_corroboration is False
        assert alert.crosses_jurisdiction_boundary is False

    def test_high_severity_crossing_boundary_submits_to_blockchain(self, db_session):
        _make_boundary_zone(db_session)
        ev = _make_event(db_session, severity=Severity.HIGH.value, zone_id="zone-1")
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert is not None
        assert alert.crosses_jurisdiction_boundary is True
        assert alert.blockchain_status != "PENDING"  # MockBlockchainAdapter set it to "MOCK"

    def test_high_severity_corroboration_score_does_not_change_flag(self, db_session):
        # A HIGH event needed no boost — it was already eligible on its own,
        # so escalated_via_corroboration must stay False even if it happens
        # to also carry a strong corroboration score.
        ev = _make_event(db_session, severity=Severity.HIGH.value, corroboration_score=0.95)
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert.escalated_via_corroboration is False


class TestMediumSeverityRegression:
    """Regression: MEDIUM without strong-enough corroboration must still
    not escalate at all, exactly as before this boost existed."""

    def test_medium_with_no_corroboration_does_not_escalate(self, db_session):
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=None)
        check_and_escalate(ev, db_session)

        assert db_session.query(Alert).filter(Alert.event_id == ev.id).first() is None

    def test_medium_with_weak_corroboration_does_not_escalate(self, db_session):
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=0.3)
        check_and_escalate(ev, db_session)

        assert db_session.query(Alert).filter(Alert.event_id == ev.id).first() is None


class TestMediumSeverityCorroborationBoost:
    """New behavior: MEDIUM + strong real corroboration now escalates,
    transparently marked."""

    def test_medium_with_strong_corroboration_escalates(self, db_session):
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=0.8)
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert is not None
        assert alert.escalated_via_corroboration is True
        assert alert.severity == Severity.MEDIUM.value

    def test_boundary_exactly_at_threshold_counts_as_eligible(self, db_session):
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=CORROBORATION_BOOST_MIN_TC)
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert is not None
        assert alert.escalated_via_corroboration is True

    def test_just_below_threshold_does_not_escalate(self, db_session):
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=CORROBORATION_BOOST_MIN_TC - 0.01)
        check_and_escalate(ev, db_session)

        assert db_session.query(Alert).filter(Alert.event_id == ev.id).first() is None

    def test_boosted_alert_can_still_cross_boundary_and_hit_blockchain(self, db_session):
        _make_boundary_zone(db_session)
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=0.9, zone_id="zone-1")
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert is not None
        assert alert.escalated_via_corroboration is True
        assert alert.crosses_jurisdiction_boundary is True
        assert alert.blockchain_status != "PENDING"


class TestLowSeverityNeverBoosted:
    """LOW is explicitly never boosted, regardless of corroboration
    strength — a deliberate, disclosed scope limit, not an accident."""

    def test_low_with_very_strong_corroboration_still_does_not_escalate(self, db_session):
        ev = _make_event(db_session, severity=Severity.LOW.value, corroboration_score=0.99)
        check_and_escalate(ev, db_session)

        assert db_session.query(Alert).filter(Alert.event_id == ev.id).first() is None

    def test_corroboration_boost_severity_constant_is_medium_only(self):
        assert CORROBORATION_BOOST_SEVERITY == Severity.MEDIUM.value


class TestIdempotency:
    def test_calling_twice_does_not_create_a_duplicate_alert(self, db_session):
        ev = _make_event(db_session, severity=Severity.MEDIUM.value, corroboration_score=0.9)
        check_and_escalate(ev, db_session)
        check_and_escalate(ev, db_session)

        alerts = db_session.query(Alert).filter(Alert.event_id == ev.id).all()
        assert len(alerts) == 1


class TestAlertLifecycleState:
    """SIH PS 26187 audit finding: EventState.CLOSED was defined but never
    actually set anywhere. A real Alert now carries a real, queryable
    lifecycle_state (shared.constants.EventState) — ALERTED at creation
    here; ACKNOWLEDGED/CLOSED are set by backend/api/alerts.py's real
    acknowledge/close endpoints, not exercised by this escalation-only
    test file."""

    def test_a_newly_created_alert_has_lifecycle_state_alerted(self, db_session):
        ev = _make_event(db_session, severity=Severity.HIGH.value)
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert.lifecycle_state == "ALERTED"

    def test_a_newly_created_alert_has_no_close_fields_set(self, db_session):
        ev = _make_event(db_session, severity=Severity.HIGH.value)
        check_and_escalate(ev, db_session)

        alert = db_session.query(Alert).filter(Alert.event_id == ev.id).first()
        assert alert.closed_at is None
        assert alert.closed_by is None
        assert alert.resolution_notes is None
