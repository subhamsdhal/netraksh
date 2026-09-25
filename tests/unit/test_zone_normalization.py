"""
NETRAKSH — Unit tests for edge/rules/modules.py::normalize_point and its
wiring into the zone-matching modules.

Closes a real bug: zone-matching used to compare a raw-pixel centroid
directly against polygon coordinates with no defined unit — a config
written for one camera resolution would silently misbehave on another.
"""
from edge.rules.modules import (
    LineCrossingModule,
    VirtualFenceModule,
    normalize_point,
)
from shared.constants import DetectionClass
from shared.schemas import BoundingBox, Point, Polygon, TrackData, ZoneSchema


def _track(track_id: int, x: float, y: float) -> TrackData:
    return TrackData(
        track_id=track_id,
        detection_class=DetectionClass.PERSON,
        bbox=BoundingBox(x1=x - 1, y1=y - 1, x2=x + 1, y2=y + 1),
        confidence=0.9,
    )


class TestNormalizePoint:
    def test_center_of_frame_normalizes_to_half(self):
        p = normalize_point(Point(x=640, y=360), frame_width=1280, frame_height=720)
        assert abs(p.x - 0.5) < 1e-9
        assert abs(p.y - 0.5) < 1e-9

    def test_default_frame_size_is_a_no_op(self):
        """Callers that don't pass real dimensions (existing unit tests, or
        a config already authored in 0-1 coordinates) get an unchanged point."""
        p = normalize_point(Point(x=0.3, y=0.7), frame_width=1.0, frame_height=1.0)
        assert p.x == 0.3
        assert p.y == 0.7

    def test_zero_dimensions_return_point_unchanged_rather_than_dividing_by_zero(self):
        original = Point(x=100, y=200)
        result = normalize_point(original, frame_width=0, frame_height=0)
        assert result.x == 100
        assert result.y == 200

    def test_same_pixel_position_normalizes_differently_at_different_resolutions(self):
        """The whole point of this fix: (640, 360) is dead-center at 720p but
        NOT dead-center at 1080p — the same raw pixel value must not be
        treated identically at two different resolutions."""
        p_at_720p = normalize_point(Point(x=640, y=360), 1280, 720)
        p_at_1080p = normalize_point(Point(x=640, y=360), 1920, 1080)
        assert p_at_720p.x != p_at_1080p.x
        assert abs(p_at_720p.x - 0.5) < 1e-9  # centered at 720p
        assert p_at_1080p.x < 0.4              # NOT centered at 1080p


class TestZoneMatchingIsResolutionCorrect:
    """A normalized-coordinate zone must fire correctly regardless of the
    camera's actual resolution — this is the end-to-end payoff of the fix."""

    def test_fence_zone_fires_the_same_way_at_two_different_resolutions(self):
        # A zone covering the right half of frame, authored in normalized coords.
        zone = ZoneSchema(
            zone_id="z1", camera_id="cam-1", name="Right half", zone_type="fence",
            polygon=Polygon(points=[
                Point(x=0.5, y=0.0), Point(x=1.0, y=0.0),
                Point(x=1.0, y=1.0), Point(x=0.5, y=1.0),
            ]),
            owning_command_id="COMMAND_A",
        )

        # At 1280x720: x=960 is in the right half (960/1280 = 0.75).
        module_720p = VirtualFenceModule(zones=[zone])
        module_720p.check(_track(1, x=100, y=360), frame_width=1280, frame_height=720)   # left half, outside
        result_720p = module_720p.check(_track(1, x=960, y=360), frame_width=1280, frame_height=720)  # crosses in
        assert result_720p is not None

        # At 1920x1080: the SAME relative position (75% across) is x=1440, not x=960.
        module_1080p = VirtualFenceModule(zones=[zone])
        module_1080p.check(_track(1, x=100, y=540), frame_width=1920, frame_height=1080)
        result_1080p = module_1080p.check(_track(1, x=1440, y=540), frame_width=1920, frame_height=1080)
        assert result_1080p is not None

        # And critically: x=900 at 1080p is only ~47% across (still outside the >50% zone) —
        # proving the SAME raw pixel region that fired at 720p does NOT fire at 1080p.
        module_1080p_wrong = VirtualFenceModule(zones=[zone])
        module_1080p_wrong.check(_track(1, x=100, y=540), frame_width=1920, frame_height=1080)
        result_should_not_fire = module_1080p_wrong.check(_track(1, x=900, y=540), frame_width=1920, frame_height=1080)
        assert result_should_not_fire is None

    def test_line_crossing_fires_the_same_way_at_two_different_resolutions(self):
        # A vertical trip-line at the horizontal midpoint, normalized coords.
        zone = ZoneSchema(
            zone_id="line-1", camera_id="cam-1", name="Midline", zone_type="boundary",
            polygon=Polygon(points=[Point(x=0.5, y=0.0), Point(x=0.5, y=1.0)]),
            owning_command_id="COMMAND_A",
        )

        module_720p = LineCrossingModule(zones=[zone])
        module_720p.check(_track(1, x=200, y=360), 1280, 720)   # left of midline (200/1280)
        result_720p = module_720p.check(_track(1, x=1000, y=360), 1280, 720)  # right of midline
        assert result_720p is not None

        module_1080p = LineCrossingModule(zones=[zone])
        module_1080p.check(_track(1, x=200, y=540), 1920, 1080)   # still left of midline (200/1920)
        result_1080p = module_1080p.check(_track(1, x=1000, y=540), 1920, 1080)  # 1000/1920 ≈ 0.52, right of midline
        assert result_1080p is not None
