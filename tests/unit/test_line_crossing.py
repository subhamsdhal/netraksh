"""
NETRAKSH — Unit tests for edge/rules/modules.py::LineCrossingModule
(architecture v4 §5 — near-free addition reusing the fence module's
geometric style, without an "inside" concept).
"""
from edge.rules.modules import LineCrossingModule
from shared.constants import DetectionClass, EventType, LineCrossingDirection
from shared.schemas import BoundingBox, Point, Polygon, TrackData, ZoneSchema


def _line_zone(zone_id="line-1", a=(0.0, 0.0), b=(10.0, 0.0), restricted_direction=None) -> ZoneSchema:
    return ZoneSchema(
        zone_id=zone_id,
        camera_id="cam-1",
        name="Trip line",
        zone_type="boundary",
        polygon=Polygon(points=[Point(x=a[0], y=a[1]), Point(x=b[0], y=b[1])]),
        owning_command_id="COMMAND_A",
        restricted_direction=restricted_direction,
    )


def _track(track_id: int, x: float, y: float, confidence=0.9) -> TrackData:
    # A tiny bbox whose centroid is exactly (x, y)
    return TrackData(
        track_id=track_id,
        detection_class=DetectionClass.PERSON,
        bbox=BoundingBox(x1=x - 1, y1=y - 1, x2=x + 1, y2=y + 1),
        confidence=confidence,
    )


class TestNoZonesConfigured:
    def test_returns_none_when_no_boundary_zones_exist(self):
        module = LineCrossingModule(zones=[])
        result = module.check(_track(1, 5.0, 5.0))
        assert result is None

    def test_ignores_non_boundary_zone_types(self):
        fence_zone = ZoneSchema(
            zone_id="z1", camera_id="cam-1", name="Fence", zone_type="fence",
            polygon=Polygon(points=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1)]),
            owning_command_id="COMMAND_A",
        )
        module = LineCrossingModule(zones=[fence_zone])
        result = module.check(_track(1, 0.5, 0.5))
        assert result is None

    def test_ignores_boundary_zone_with_wrong_point_count(self):
        """A 'boundary' zone must have exactly 2 points to be treated as a line."""
        three_point = ZoneSchema(
            zone_id="z1", camera_id="cam-1", name="Not a line", zone_type="boundary",
            polygon=Polygon(points=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1)]),
            owning_command_id="COMMAND_A",
        )
        module = LineCrossingModule(zones=[three_point])
        result = module.check(_track(1, 0.5, 0.5))
        assert result is None


class TestNoHistoryNoCrossing:
    def test_first_observation_never_fires(self):
        """No prior side recorded yet — can't detect a crossing on frame one."""
        module = LineCrossingModule(zones=[_line_zone()])
        result = module.check(_track(1, 5.0, 5.0))
        assert result is None

    def test_staying_on_the_same_side_never_fires(self):
        module = LineCrossingModule(zones=[_line_zone()])
        module.check(_track(1, 5.0, 5.0))    # side +1 (above the line, y>0... check sign)
        result = module.check(_track(1, 6.0, 5.0))  # still same side
        assert result is None


class TestCrossingDetection:
    def test_crossing_from_one_side_to_the_other_fires(self):
        module = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module.check(_track(1, 5.0, 5.0))   # above the line
        result = module.check(_track(1, 5.0, -5.0))  # now below the line
        assert result is not None
        assert result["event_type"] == EventType.LINE_CROSSING
        assert result["track_id"] == 1
        assert result["direction"] in (LineCrossingDirection.A_TO_B, LineCrossingDirection.B_TO_A)

    def test_opposite_crossings_report_opposite_directions(self):
        module1 = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module1.check(_track(1, 5.0, 5.0))
        result_down = module1.check(_track(1, 5.0, -5.0))

        module2 = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module2.check(_track(1, 5.0, -5.0))
        result_up = module2.check(_track(1, 5.0, 5.0))

        assert result_down["direction"] != result_up["direction"]

    def test_on_the_line_exactly_is_skipped_not_treated_as_a_side(self):
        module = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module.check(_track(1, 5.0, 5.0))     # side +1
        result_on_line = module.check(_track(1, 5.0, 0.0))  # exactly on the line
        assert result_on_line is None
        # A point exactly on the line must not have overwritten the recorded
        # side — crossing to the other side afterward must still fire.
        result_after = module.check(_track(1, 5.0, -5.0))
        assert result_after is not None

    def test_different_tracks_do_not_share_side_state(self):
        module = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module.check(_track(1, 5.0, 5.0))
        # Track 2 has no history yet — must not fire even though track 1 has a recorded side.
        result = module.check(_track(2, 5.0, -5.0))
        assert result is None

    def test_get_track_side_reflects_last_observed_side(self):
        module = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module.check(_track(1, 5.0, 5.0))
        assert module.get_track_side(1, "line-1") == 1
        module.check(_track(1, 5.0, -5.0))
        assert module.get_track_side(1, "line-1") == -1

    def test_get_track_side_unknown_track_returns_none(self):
        module = LineCrossingModule(zones=[_line_zone()])
        assert module.get_track_side(999, "line-1") is None


class TestMultipleLines:
    def test_only_the_crossed_line_fires(self):
        line_a = _line_zone(zone_id="line-a", a=(0, 0), b=(10, 0))
        line_b = _line_zone(zone_id="line-b", a=(0, 100), b=(10, 100))
        module = LineCrossingModule(zones=[line_a, line_b])
        module.check(_track(1, 5.0, 5.0))     # side_a=+1, side_b=-1
        module.check(_track(1, 5.0, 95.0))    # side_a=+1 (unchanged), side_b=-1 (unchanged) — no fire
        result = module.check(_track(1, 5.0, 105.0))  # side_a=+1 (unchanged), side_b=+1 (crossed!)
        assert result is not None
        assert result["zone_id"] == "line-b"


class TestWrongDirection:
    """
    SIH PS 26187's "suspicious activity detection": ZoneSchema.restricted_direction
    (new) lets a boundary-line zone flag one specific crossing direction as
    wrong-way, real vehicle/person movement instead of an ordinary crossing.
    EventType.WRONG_DIRECTION previously existed only as a defined-but-unused
    enum value with zero real producer anywhere in the codebase.

    Geometry established by the existing tests above: for a=(0,0), b=(10,0),
    crossing from y>0 (side +1) to y<0 (side -1) reports A_TO_B; the reverse
    reports B_TO_A.
    """

    def test_no_restricted_direction_configured_always_reports_line_crossing(self):
        """Regression: every zone without this new field configured (i.e.
        every zone that existed before this feature) must behave exactly as
        before — restricted_direction defaults to None."""
        module = LineCrossingModule(zones=[_line_zone(a=(0, 0), b=(10, 0))])
        module.check(_track(1, 5.0, 5.0))
        result = module.check(_track(1, 5.0, -5.0))
        assert result["event_type"] == EventType.LINE_CROSSING

    def test_crossing_in_the_restricted_direction_fires_wrong_direction(self):
        zone = _line_zone(a=(0, 0), b=(10, 0), restricted_direction=LineCrossingDirection.A_TO_B)
        module = LineCrossingModule(zones=[zone])
        module.check(_track(1, 5.0, 5.0))     # above
        result = module.check(_track(1, 5.0, -5.0))  # crosses to below -> A_TO_B
        assert result["direction"] == LineCrossingDirection.A_TO_B
        assert result["event_type"] == EventType.WRONG_DIRECTION

    def test_crossing_the_other_direction_still_reports_ordinary_line_crossing(self):
        """Only the configured direction is flagged -- the reverse crossing on
        the SAME zone is still an ordinary, non-wrong-way LINE_CROSSING."""
        zone = _line_zone(a=(0, 0), b=(10, 0), restricted_direction=LineCrossingDirection.A_TO_B)
        module = LineCrossingModule(zones=[zone])
        module.check(_track(1, 5.0, -5.0))    # below
        result = module.check(_track(1, 5.0, 5.0))   # crosses to above -> B_TO_A
        assert result["direction"] == LineCrossingDirection.B_TO_A
        assert result["event_type"] == EventType.LINE_CROSSING

    def test_restricted_direction_set_to_the_other_value_flags_the_reverse_crossing(self):
        zone = _line_zone(a=(0, 0), b=(10, 0), restricted_direction=LineCrossingDirection.B_TO_A)
        module = LineCrossingModule(zones=[zone])
        module.check(_track(1, 5.0, -5.0))
        result = module.check(_track(1, 5.0, 5.0))   # -> B_TO_A, matches restriction
        assert result["event_type"] == EventType.WRONG_DIRECTION

    def test_wrong_direction_event_still_carries_the_real_track_and_zone_fields(self):
        """The event dict shape is unchanged -- only event_type differs from
        an ordinary LINE_CROSSING."""
        zone = _line_zone(zone_id="checkpoint-road", a=(0, 0), b=(10, 0), restricted_direction=LineCrossingDirection.A_TO_B)
        module = LineCrossingModule(zones=[zone])
        module.check(_track(1, 5.0, 5.0))
        result = module.check(_track(1, 5.0, -5.0))
        assert result["zone_id"] == "checkpoint-road"
        assert result["track_id"] == 1
        assert result["detection_class"] == DetectionClass.PERSON
        assert "confidence" in result
