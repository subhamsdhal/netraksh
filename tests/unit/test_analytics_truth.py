import asyncio
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from backend.api.analytics import (
    analytics_by_camera,
    analytics_by_severity,
    analytics_by_type,
    analytics_summary,
    analytics_timeseries,
)
from backend.models.orm import Alert, Base, Camera, Event, EvidencePackage


WINDOW_START = datetime(2026, 10, 2, 3, 31)
WINDOW_END = datetime(2026, 10, 3, 3, 31)


def _call(endpoint, db, since=WINDOW_START, until=WINDOW_END, **kwargs):
    parameters = {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "stream_id": None,
        "camera_id": None,
        "event_type": None,
        "db": db,
        "_user": None,
        **kwargs,
    }
    return asyncio.run(endpoint(**parameters))


def _event(event_id, timestamp, *, event_type, decision_state="DETECTED", score_r=0.8):
    return Event(
        id=event_id,
        camera_id="cam-border-01",
        timestamp=timestamp,
        event_type=event_type,
        detection_class="person" if decision_state == "DETECTED" else "unknown",
        confidence=0.9 if decision_state == "DETECTED" else 0.0,
        scene_condition="DAY",
        camera_health_state="OK",
        decision_state=decision_state,
        severity="MEDIUM" if decision_state == "DETECTED" else None,
        stream_id="stream-current",
        score_r=score_r,
    )


@pytest.fixture()
def analytics_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Camera(
        id="cam-border-01",
        name="Border 01",
        location="Test border",
        owning_command_id="COMMAND_A",
    ))

    detected = [
        _event(f"detected-{index}", WINDOW_START + timedelta(hours=index + 1),
               event_type="LOITERING" if index < 6 else "VIRTUAL_FENCE_CROSSING")
        for index in range(7)
    ]
    abstain = [
        _event(f"abstain-{index}", WINDOW_START + timedelta(hours=index + 10),
               event_type=None, decision_state="ABSTAIN", score_r=None)
        for index in range(2)
    ]
    legacy = _event(
        "legacy-lowercase",
        WINDOW_START - timedelta(days=2),
        event_type="loitering",
    )
    session.add_all([*detected, *abstain, legacy])

    for event in [*detected, *abstain]:
        session.add(EvidencePackage(
            id=f"package-{event.id}",
            event_id=event.id,
            sha256="a" * 64,
            digital_signature="signature",
            current_hash="b" * 64,
            verified_ok=True,
        ))

    session.add(Alert(
        id="historical-alert",
        event_id=detected[0].id,
        severity="HIGH",
        command_id_issuing="COMMAND_A",
        created_at=WINDOW_START - timedelta(days=1),
    ))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_summary_uses_raw_event_scope_and_detected_metric_scope(analytics_db):
    result = _call(analytics_summary, analytics_db)

    assert result["events"]["raw_total"] == 9
    assert result["events"]["analytic_total"] == 7
    assert result["events"]["detected"] == 7
    assert result["events"]["abstain"] == 2
    assert result["events"]["detection_rate_pct"] == 77.78
    assert result["events"]["intrusion"] == 6
    assert result["events"]["person"] == 7
    assert result["events"]["vehicle"] == 0
    assert result["events"]["verified_packages"] == 9
    assert result["events"]["reliability"]["average"] == pytest.approx(0.8)
    assert result["events"]["confidence"]["average"] == pytest.approx(0.9)
    assert result["cameras"]["with_events"] == 1
    assert result["alerts"] == {"total": 0, "acknowledged": 0, "unresolved": 0, "closed": 0}


def test_intrusion_matching_accepts_uppercase_and_legacy_lowercase(analytics_db):
    current = _call(analytics_summary, analytics_db)
    assert current["events"]["intrusion"] == 6

    legacy_time = WINDOW_START - timedelta(days=2)
    legacy = _call(
        analytics_summary,
        analytics_db,
        since=legacy_time - timedelta(minutes=1),
        until=legacy_time + timedelta(minutes=1),
    )
    assert legacy["events"]["intrusion"] == 1


def test_detected_charts_preserve_real_type_severity_and_intrusion_counts(analytics_db):
    by_type = _call(analytics_by_type, analytics_db)
    assert {row["event_type"]: row["count"] for row in by_type["by_type"]} == {
        "LOITERING": 6,
        "VIRTUAL_FENCE_CROSSING": 1,
    }

    by_severity = _call(analytics_by_severity, analytics_db)
    assert by_severity["by_severity"] == [{"severity": "MEDIUM", "count": 7}]

    timeseries = _call(analytics_timeseries, analytics_db, bucket="hour")
    assert sum(row["intrusion"] for row in timeseries["series"]) == 6
    assert sum(row["total"] for row in timeseries["series"]) == 7


def test_filters_and_camera_with_events_remain_authoritative(analytics_db):
    filtered = _call(
        analytics_summary,
        analytics_db,
        camera_id="cam-border-01",
        event_type="LOITERING",
        stream_id="stream-current",
    )
    assert filtered["events"]["raw_total"] == 6
    assert filtered["events"]["intrusion"] == 6
    assert filtered["cameras"]["with_events"] == 1

    by_camera = _call(analytics_by_camera, analytics_db)
    assert by_camera["by_camera"] == [{
        "camera_id": "cam-border-01",
        "camera_name": "Border 01",
        "count": 7,
    }]
