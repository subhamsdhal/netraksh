"""
NETRAKSH — Unit tests for backend/services/webhook_delivery.py (SIH PS
26187: "support integration with existing command and control systems").
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.orm import Alert, Base, Event, WebhookSubscription
from backend.services.webhook_delivery import (
    SEVERITY_RANK,
    _meets_severity_threshold,
    deliver_alert_webhooks,
)
from shared.constants import Severity


class TestSeverityThreshold:
    def test_equal_severity_meets_threshold(self):
        assert _meets_severity_threshold("HIGH", "HIGH") is True

    def test_higher_severity_meets_lower_threshold(self):
        assert _meets_severity_threshold("HIGH", "LOW") is True

    def test_lower_severity_does_not_meet_higher_threshold(self):
        assert _meets_severity_threshold("LOW", "HIGH") is False
        assert _meets_severity_threshold("MEDIUM", "HIGH") is False

    def test_rank_ordering_is_low_medium_high(self):
        assert SEVERITY_RANK["LOW"] < SEVERITY_RANK["MEDIUM"] < SEVERITY_RANK["HIGH"]


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_event(session, event_id="ev-1"):
    ev = Event(
        id=event_id, camera_id="cam-1", timestamp=datetime(2026, 1, 1, 12, 0, 0),
        detection_class="person", confidence=0.9, scene_condition="CLEAR_DAY",
        camera_health_state="OK", decision_state="DETECTED", event_type="LOITERING",
        zone_id="zone-1",
    )
    session.add(ev)
    session.flush()
    return ev


def _make_alert(session, event_id, severity=Severity.HIGH.value):
    alert = Alert(
        event_id=event_id, severity=severity, crosses_jurisdiction_boundary=True,
        command_id_issuing="COMMAND_A",
    )
    session.add(alert)
    session.flush()
    return alert


def _make_subscription(session, url, min_severity="LOW", active=True):
    sub = WebhookSubscription(name="test-sub", url=url, min_severity=min_severity, is_active=active)
    session.add(sub)
    session.flush()
    return sub


class TestDeliverAlertWebhooks:
    def test_no_subscriptions_is_a_real_no_op(self, db_session):
        event = _make_event(db_session)
        alert = _make_alert(db_session, event.id)
        db_session.commit()
        # Must not raise with zero subscriptions.
        deliver_alert_webhooks(alert, event, db_session)

    def test_delivery_attempted_updates_subscription_delivery_fields(self, db_session, monkeypatch):
        """Real HTTP call is mocked (no real network in a unit test), but the
        real subscription row's own last_delivery_* fields must reflect a
        real outcome either way -- never left stale/unset."""
        event = _make_event(db_session)
        alert = _make_alert(db_session, event.id, severity=Severity.HIGH.value)
        sub = _make_subscription(db_session, "http://example.invalid/webhook", min_severity="LOW")
        db_session.commit()
        monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "example.invalid")

        class _FakeResponse:
            def raise_for_status(self):
                pass

        class _FakeHttpx:
            @staticmethod
            def post(url, content=None, headers=None, timeout=None, follow_redirects=None):
                assert url == "http://example.invalid/webhook"
                assert str(alert.id) in content
                return _FakeResponse()

        import sys
        monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)

        deliver_alert_webhooks(alert, event, db_session)

        db_session.refresh(sub)
        assert sub.last_delivery_status == "SUCCESS"
        assert sub.last_delivery_at is not None
        assert sub.last_delivery_error is None

    def test_a_real_delivery_failure_is_recorded_not_raised(self, db_session, monkeypatch):
        event = _make_event(db_session)
        alert = _make_alert(db_session, event.id, severity=Severity.HIGH.value)
        sub = _make_subscription(db_session, "http://example.invalid/webhook", min_severity="LOW")
        db_session.commit()
        monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "example.invalid")

        class _FailingHttpx:
            @staticmethod
            def post(url, **kwargs):
                raise ConnectionError("simulated real network failure")

        import sys
        monkeypatch.setitem(sys.modules, "httpx", _FailingHttpx)

        deliver_alert_webhooks(alert, event, db_session)  # must not raise

        db_session.refresh(sub)
        assert sub.last_delivery_status == "FAILED"
        assert "simulated real network failure" in sub.last_delivery_error

    def test_inactive_subscription_is_skipped(self, db_session, monkeypatch):
        event = _make_event(db_session)
        alert = _make_alert(db_session, event.id, severity=Severity.HIGH.value)
        sub = _make_subscription(db_session, "http://example.invalid/webhook", active=False)
        db_session.commit()

        deliver_alert_webhooks(alert, event, db_session)

        db_session.refresh(sub)
        assert sub.last_delivery_status is None  # never attempted

    def test_alert_below_subscription_min_severity_is_not_delivered(self, db_session, monkeypatch):
        event = _make_event(db_session)
        alert = _make_alert(db_session, event.id, severity=Severity.MEDIUM.value)
        sub = _make_subscription(db_session, "http://example.invalid/webhook", min_severity="HIGH")
        db_session.commit()

        deliver_alert_webhooks(alert, event, db_session)

        db_session.refresh(sub)
        assert sub.last_delivery_status is None  # skipped, not attempted

    def test_alert_at_or_above_min_severity_is_delivered(self, db_session, monkeypatch):
        event = _make_event(db_session)
        alert = _make_alert(db_session, event.id, severity=Severity.HIGH.value)
        sub = _make_subscription(db_session, "http://example.invalid/webhook", min_severity="MEDIUM")
        db_session.commit()
        monkeypatch.setenv("WEBHOOK_ALLOWED_HOSTS", "example.invalid")

        class _FakeResponse:
            def raise_for_status(self):
                pass

        class _FakeHttpx:
            @staticmethod
            def post(url, **kwargs):
                return _FakeResponse()

        import sys
        monkeypatch.setitem(sys.modules, "httpx", _FakeHttpx)

        deliver_alert_webhooks(alert, event, db_session)

        db_session.refresh(sub)
        assert sub.last_delivery_status == "SUCCESS"
