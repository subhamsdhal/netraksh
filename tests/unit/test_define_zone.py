"""
NETRAKSH — Unit tests for scripts/define_zone.py's pure logic.
The interactive cv2 click-loop (run_click_loop) needs a real display and is
not covered here — everything around it (pixel-to-normalized conversion,
zone-record construction, config upsert, point-count validation) is pure
and fully tested.
"""
import pytest

from scripts.define_zone import (
    _validate_point_count,
    build_zone,
    points_to_normalized,
    upsert_zone,
)


class TestPointsToNormalized:
    def test_converts_pixels_to_0_1_range(self):
        result = points_to_normalized([(640, 360)], frame_width=1280, frame_height=720)
        assert result == [{"x": 0.5, "y": 0.5}]

    def test_preserves_point_order(self):
        result = points_to_normalized([(0, 0), (100, 0), (100, 100)], frame_width=100, frame_height=100)
        assert result == [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]

    def test_rounds_to_four_decimal_places(self):
        result = points_to_normalized([(1, 3)], frame_width=3, frame_height=7)
        assert result[0]["x"] == round(1 / 3, 4)
        assert result[0]["y"] == round(3 / 7, 4)


class TestBuildZone:
    def test_produces_a_valid_zone_shape(self):
        zone = build_zone(
            zone_id="z1", camera_id="edge-001", name="Test Zone", zone_type="fence",
            points_px=[(0, 0), (100, 0), (100, 100)], frame_width=100, frame_height=100,
        )
        assert zone["zone_id"] == "z1"
        assert zone["camera_id"] == "edge-001"
        assert zone["zone_type"] == "fence"
        assert zone["owning_command_id"] == "COMMAND_A"
        assert len(zone["polygon"]["points"]) == 3

    def test_output_is_accepted_by_the_real_zoneschema(self, tmp_path):
        """The whole point of this tool: its output must actually load
        through edge/rules/modules.py::load_zones, not just look plausible."""
        import json
        from edge.rules.modules import load_zones

        zone = build_zone("z1", "edge-001", "Test Zone", "boundary", [(0, 0), (100, 100)], 100, 100)
        config_path = tmp_path / "zones.json"
        config_path.write_text(json.dumps({"zones": [zone]}))

        loaded = load_zones(str(config_path))
        assert len(loaded) == 1
        assert loaded[0].zone_id == "z1"
        assert loaded[0].zone_type == "boundary"


class TestUpsertZone:
    def test_appends_when_zone_id_is_new(self):
        config = {"zones": [{"zone_id": "existing"}]}
        result = upsert_zone(config, {"zone_id": "new"})
        ids = {z["zone_id"] for z in result["zones"]}
        assert ids == {"existing", "new"}

    def test_replaces_existing_zone_with_the_same_id(self):
        config = {"zones": [{"zone_id": "z1", "name": "old"}]}
        result = upsert_zone(config, {"zone_id": "z1", "name": "new"})
        assert len(result["zones"]) == 1
        assert result["zones"][0]["name"] == "new"

    def test_leaves_other_zones_untouched(self):
        config = {"zones": [{"zone_id": "keep-me", "name": "unchanged"}, {"zone_id": "z1", "name": "old"}]}
        result = upsert_zone(config, {"zone_id": "z1", "name": "new"})
        kept = next(z for z in result["zones"] if z["zone_id"] == "keep-me")
        assert kept["name"] == "unchanged"

    def test_does_not_mutate_the_input_config(self):
        config = {"zones": [{"zone_id": "z1", "name": "old"}]}
        upsert_zone(config, {"zone_id": "z1", "name": "new"})
        assert config["zones"][0]["name"] == "old"

    def test_missing_zones_key_is_handled(self):
        result = upsert_zone({}, {"zone_id": "z1"})
        assert result["zones"] == [{"zone_id": "z1"}]


class TestValidatePointCount:
    def test_boundary_requires_exactly_two(self):
        assert _validate_point_count("boundary", 2) is None
        assert _validate_point_count("boundary", 1) is not None
        assert _validate_point_count("boundary", 3) is not None

    def test_fence_requires_at_least_three(self):
        assert _validate_point_count("fence", 3) is None
        assert _validate_point_count("fence", 5) is None
        assert _validate_point_count("fence", 2) is not None

    def test_checkpoint_and_verification_also_require_at_least_three(self):
        assert _validate_point_count("checkpoint", 3) is None
        assert _validate_point_count("verification", 3) is None
        assert _validate_point_count("checkpoint", 2) is not None
