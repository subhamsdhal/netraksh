"""
NETRAKSH — Unit tests for backend/services/cross_camera.py, the real, first
implementation of the poster's cross-camera corroboration (§12B) and
temporal-consistency formula (§13, Tc = e^(-|Δt-t_expected|/σ)).

See that module's docstring for the honest scope: real haversine distance
from real admin-entered camera coordinates, a disclosed walking-speed
heuristic for the expected travel-time range, and explicitly NOT person
re-identification.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.orm import Base, Camera, Event
from backend.services.cross_camera import (
    ASSUMED_MAX_SPEED_MPS,
    ASSUMED_MIN_SPEED_MPS,
    MAX_CORROBORATION_DISTANCE_M,
    MIN_SIGMA_SECONDS,
    apply_corroboration,
    expected_travel_time_range,
    find_corroboration,
    haversine_distance_m,
    temporal_consistency,
)


# ---------------------------------------------------------------------------
# Pure formula tests — no DB needed
# ---------------------------------------------------------------------------

class TestHaversineDistance:
    def test_same_point_is_zero_distance(self):
        assert haversine_distance_m(28.6139, 77.2090, 28.6139, 77.2090) == pytest.approx(0.0, abs=1e-6)

    def test_known_real_distance_delhi_to_agra(self):
        # New Delhi (28.6139, 77.2090) to Agra (27.1767, 78.0081) — real,
        # well-known great-circle distance is ~180km. Not this project's own
        # measurement (no GPS-surveyed camera pair exists to measure), but a
        # correctness check against an independently known real value, which
        # is what a haversine implementation should be checked against.
        d = haversine_distance_m(28.6139, 77.2090, 27.1767, 78.0081)
        assert 170_000 < d < 190_000

    def test_symmetric(self):
        d1 = haversine_distance_m(28.6139, 77.2090, 27.1767, 78.0081)
        d2 = haversine_distance_m(27.1767, 78.0081, 28.6139, 77.2090)
        assert d1 == pytest.approx(d2, rel=1e-9)


class TestExpectedTravelTimeRange:
    def test_zero_distance_gives_zero_zero(self):
        assert expected_travel_time_range(0.0) == (0.0, 0.0)

    def test_real_distance_gives_real_bounds(self):
        # 100m: fastest assumed speed gives the shortest time, slowest gives
        # the longest — real division, not fabricated numbers.
        t_min, t_max = expected_travel_time_range(100.0)
        assert t_min == pytest.approx(100.0 / ASSUMED_MAX_SPEED_MPS)
        assert t_max == pytest.approx(100.0 / ASSUMED_MIN_SPEED_MPS)
        assert t_min < t_max

    def test_larger_distance_gives_wider_and_later_range(self):
        t_min_near, t_max_near = expected_travel_time_range(50.0)
        t_min_far, t_max_far = expected_travel_time_range(500.0)
        assert t_min_far > t_min_near
        assert t_max_far > t_max_near
        assert (t_max_far - t_min_far) > (t_max_near - t_min_near)


class TestTemporalConsistency:
    def test_delta_t_exactly_at_expected_midpoint_is_tc_one(self):
        t_min, t_max = 10.0, 30.0
        t_expected = (t_min + t_max) / 2.0
        tc, _ = temporal_consistency(t_expected, t_min, t_max)
        assert tc == pytest.approx(1.0, abs=1e-9)

    def test_tc_decreases_as_delta_t_moves_away_from_expected(self):
        t_min, t_max = 10.0, 30.0
        t_expected = (t_min + t_max) / 2.0
        tc_near, _ = temporal_consistency(t_expected + 2, t_min, t_max)
        tc_far, _ = temporal_consistency(t_expected + 20, t_min, t_max)
        assert 0.0 <= tc_far < tc_near <= 1.0

    def test_tc_bounded_in_zero_one_for_extreme_delta_t(self):
        tc, _ = temporal_consistency(1_000_000.0, 10.0, 30.0)
        assert 0.0 <= tc <= 1.0

    def test_zero_width_range_does_not_divide_by_zero(self):
        # Co-located cameras: t_min == t_max == 0. Without the MIN_SIGMA_SECONDS
        # floor this would be a division by zero; the floor keeps it a real,
        # finite, sensible value instead of raising or garbage.
        tc, _ = temporal_consistency(3.0, 0.0, 0.0)
        assert 0.0 <= tc <= 1.0
        # sigma is floored at MIN_SIGMA_SECONDS, so this should match the
        # formula computed with that floor directly.
        import math
        expected = math.exp(-abs(3.0 - 0.0) / MIN_SIGMA_SECONDS)
        assert tc == pytest.approx(expected)


# ---------------------------------------------------------------------------
# DB-backed matching tests — real Camera/Event rows in an in-memory DB
# ---------------------------------------------------------------------------

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_camera(session, camera_id, lat=None, lon=None, active=True):
    cam = Camera(
        id=camera_id, name=camera_id, location="Test Sector",
        owning_command_id="COMMAND_A", is_active=active,
        latitude=lat, longitude=lon,
    )
    session.add(cam)
    session.flush()
    return cam


def _make_event(session, event_id, camera_id, ts, detection_class="person", event_type=None, stream_id=None, analysis_session_id=None):
    ev = Event(
        id=event_id, camera_id=camera_id, timestamp=ts,
        detection_class=detection_class, confidence=0.9,
        scene_condition="CLEAR_DAY", camera_health_state="OK",
        decision_state="DETECTED",
        event_type=event_type,
        stream_id=stream_id,
        analysis_session_id=analysis_session_id,
    )
    session.add(ev)
    session.flush()
    return ev


class TestFindCorroborationHonestlySkips:
    def test_current_run_scope_rejects_an_old_replay_on_the_same_stream(self, db_session):
        _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        _make_camera(db_session, "cam-b", lat=28.6001, lon=77.2000)
        current = _make_event(
            db_session, "current-a", "cam-a", datetime(2026, 1, 1, 12, 0, 10),
            stream_id="stream-a", analysis_session_id="run-a-2",
        )
        _make_event(
            db_session, "old-b", "cam-b", datetime(2026, 1, 1, 12, 0, 9),
            stream_id="stream-b", analysis_session_id="run-b-1",
        )
        status, result = find_corroboration(current, db_session, run_scope={
            "cam-a": ("stream-a", "run-a-2"),
            "cam-b": ("stream-b", "run-b-2"),
        })
        assert result is None
        assert status != "CORROBORATED"

    def test_no_corroboration_when_camera_has_no_coordinates(self, db_session):
        _make_camera(db_session, "cam-a", lat=None, lon=None)
        _make_camera(db_session, "cam-b", lat=28.60, lon=77.20)
        ev = _make_event(db_session, "ev-1", "cam-a", datetime(2026, 1, 1, 12, 0, 0))
        _make_event(db_session, "ev-2", "cam-b", datetime(2026, 1, 1, 12, 0, 5))

        assert find_corroboration(ev, db_session)[1] is None

    def test_no_corroboration_when_only_one_camera_exists(self, db_session):
        _make_camera(db_session, "cam-a", lat=28.60, lon=77.20)
        ev = _make_event(db_session, "ev-1", "cam-a", datetime(2026, 1, 1, 12, 0, 0))

        assert find_corroboration(ev, db_session)[1] is None

    def test_no_corroboration_across_an_implausible_distance(self, db_session):
        # Real, far-apart real-world coordinates (New Delhi <-> Mumbai,
        # ~1150km) — genuinely beyond MAX_CORROBORATION_DISTANCE_M, so no
        # honest corroboration should ever be claimed between them no matter
        # how close in time the two events are.
        _make_camera(db_session, "cam-delhi", lat=28.6139, lon=77.2090)
        _make_camera(db_session, "cam-mumbai", lat=19.0760, lon=72.8777)
        ev = _make_event(db_session, "ev-1", "cam-delhi", datetime(2026, 1, 1, 12, 0, 0))
        _make_event(db_session, "ev-2", "cam-mumbai", datetime(2026, 1, 1, 12, 0, 1))

        assert find_corroboration(ev, db_session)[1] is None

    def test_no_corroboration_when_detection_class_differs(self, db_session):
        _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        _make_camera(db_session, "cam-b", lat=28.6010, lon=77.2000)  # ~111m away
        ev = _make_event(db_session, "ev-1", "cam-a", datetime(2026, 1, 1, 12, 0, 0), detection_class="person")
        _make_event(db_session, "ev-2", "cam-b", datetime(2026, 1, 1, 12, 0, 30), detection_class="vehicle")

        assert find_corroboration(ev, db_session)[1] is None

    def test_no_corroboration_when_timing_is_implausible(self, db_session):
        # ~111m apart -> expected travel time is on the order of tens of
        # seconds, not two hours. A two-hour gap should not be corroborated.
        _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        _make_camera(db_session, "cam-b", lat=28.6010, lon=77.2000)
        ev = _make_event(db_session, "ev-1", "cam-a", datetime(2026, 1, 1, 12, 0, 0))
        _make_event(db_session, "ev-2", "cam-b", datetime(2026, 1, 1, 14, 0, 0))

        assert find_corroboration(ev, db_session)[1] is None


class TestFindCorroborationRealMatch:
    def test_sih_demo_topology_correlates_without_gps_or_shared_track_id(self, db_session):
        _make_camera(db_session, "cam-border-01", lat=None, lon=None)
        _make_camera(db_session, "cam-checkpoint-01", lat=None, lon=None)
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        ev = _make_event(db_session, "ev-demo-a", "cam-border-01", t0, event_type="LINE_CROSSING", stream_id="session-a")
        _make_event(db_session, "ev-demo-b", "cam-checkpoint-01", t0 + timedelta(seconds=7), event_type="VIRTUAL_FENCE_CROSSING", stream_id="session-b")
        status, result = find_corroboration(ev, db_session)
        assert status == "CORROBORATED"
        assert result is not None
        assert result.other_camera_id == "cam-checkpoint-01"
        assert result.delta_t_s == pytest.approx(7.0)

    def test_finds_plausible_corroboration_at_real_expected_delay(self, db_session):
        cam_a = _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        cam_b = _make_camera(db_session, "cam-b", lat=28.6010, lon=77.2000)
        distance = haversine_distance_m(cam_a.latitude, cam_a.longitude, cam_b.latitude, cam_b.longitude)
        t_min, t_max = expected_travel_time_range(distance)
        t_expected = (t_min + t_max) / 2.0

        t0 = datetime(2026, 1, 1, 12, 0, 0)
        ev = _make_event(db_session, "ev-1", "cam-a", t0)
        _make_event(db_session, "ev-2", "cam-b", t0 + timedelta(seconds=t_expected))

        _, result = find_corroboration(ev, db_session)
        assert result is not None
        assert result.other_event_id == "ev-2"
        assert result.other_camera_id == "cam-b"
        assert result.tc == pytest.approx(1.0, abs=1e-6)
        assert result.distance_m == pytest.approx(distance)

    def test_picks_the_best_of_multiple_candidates(self, db_session):
        cam_a = _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        cam_b = _make_camera(db_session, "cam-b", lat=28.6010, lon=77.2000)
        distance = haversine_distance_m(cam_a.latitude, cam_a.longitude, cam_b.latitude, cam_b.longitude)
        t_min, t_max = expected_travel_time_range(distance)
        t_expected = (t_min + t_max) / 2.0

        t0 = datetime(2026, 1, 1, 12, 0, 0)
        ev = _make_event(db_session, "ev-1", "cam-a", t0)
        # A poor-fit candidate (far from expected delay) and a good-fit one —
        # the good-fit one must win, not just "the first one found".
        _make_event(db_session, "ev-poor", "cam-b", t0 + timedelta(seconds=t_expected + 500))
        _make_event(db_session, "ev-good", "cam-b", t0 + timedelta(seconds=t_expected))

        _, result = find_corroboration(ev, db_session)
        assert result is not None
        assert result.other_event_id == "ev-good"

    def test_apply_corroboration_stores_real_fields_on_both_events(self, db_session):
        cam_a = _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        cam_b = _make_camera(db_session, "cam-b", lat=28.6010, lon=77.2000)
        distance = haversine_distance_m(cam_a.latitude, cam_a.longitude, cam_b.latitude, cam_b.longitude)
        t_min, t_max = expected_travel_time_range(distance)
        t_expected = (t_min + t_max) / 2.0

        t0 = datetime(2026, 1, 1, 12, 0, 0)
        ev_a = _make_event(db_session, "ev-1", "cam-a", t0)
        ev_b = _make_event(db_session, "ev-2", "cam-b", t0 + timedelta(seconds=t_expected))
        db_session.commit()

        result = apply_corroboration(ev_a, db_session)
        assert result is not None

        db_session.refresh(ev_a)
        db_session.refresh(ev_b)
        # Symmetric: both events carry the corroboration, each pointing at
        # the other — not just the one that triggered the search.
        assert ev_a.corroborated_by_event_id == "ev-2"
        assert ev_b.corroborated_by_event_id == "ev-1"
        assert ev_a.corroboration_score == pytest.approx(1.0, abs=1e-6)
        assert ev_b.corroboration_score == pytest.approx(1.0, abs=1e-6)
        assert ev_a.corroboration_distance_m == pytest.approx(distance)
        assert ev_a.corroboration_delta_t_s == pytest.approx(t_expected, abs=1e-3)

    def test_apply_corroboration_returns_none_and_writes_nothing_when_no_match(self, db_session):
        _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        ev_a = _make_event(db_session, "ev-1", "cam-a", datetime(2026, 1, 1, 12, 0, 0))
        db_session.commit()

        result = apply_corroboration(ev_a, db_session)
        assert result is None
        db_session.refresh(ev_a)
        assert ev_a.corroboration_score is None
        assert ev_a.corroborated_by_event_id is None

    def test_ignores_inactive_cameras(self, db_session):
        _make_camera(db_session, "cam-a", lat=28.6000, lon=77.2000)
        _make_camera(db_session, "cam-b", lat=28.6010, lon=77.2000, active=False)
        ev = _make_event(db_session, "ev-1", "cam-a", datetime(2026, 1, 1, 12, 0, 0))
        _make_event(db_session, "ev-2", "cam-b", datetime(2026, 1, 1, 12, 0, 15))

        assert find_corroboration(ev, db_session)[1] is None
