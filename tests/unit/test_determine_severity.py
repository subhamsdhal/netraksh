"""
NETRAKSH — Unit tests for edge/main.py::determine_severity. No existing
coverage for this function before now; added alongside the new
WRONG_DIRECTION case (SIH PS 26187's "suspicious activity detection").
"""
from edge.main import determine_severity
from shared.constants import Severity


class TestWrongDirectionSeverity:
    def test_wrong_direction_is_high(self):
        event = {"event_type": "WRONG_DIRECTION", "direction": "A_TO_B"}
        assert determine_severity(event, reliability=None) == Severity.HIGH

    def test_wrong_direction_checked_before_the_generic_line_crossing_case(self):
        """WRONG_DIRECTION must not fall into the generic LINE_CROSSING
        MEDIUM branch just because it's also a line-crossing-shaped event."""
        event = {"event_type": "WRONG_DIRECTION"}
        assert determine_severity(event, reliability=None) != Severity.MEDIUM


class TestOrdinaryLineCrossingUnaffected:
    def test_ordinary_line_crossing_is_still_medium(self):
        """Regression: adding the WRONG_DIRECTION case above must not change
        real, existing LINE_CROSSING severity behavior."""
        event = {"event_type": "LINE_CROSSING", "direction": "A_TO_B"}
        assert determine_severity(event, reliability=None) == Severity.MEDIUM


class TestOtherEventTypesUnaffected:
    def test_fence_crossing_outside_to_restricted_is_still_high(self):
        event = {"event_type": "VIRTUAL_FENCE_CROSSING", "direction": "OUTSIDE_TO_RESTRICTED"}
        assert determine_severity(event, reliability=None) == Severity.HIGH

    def test_abandoned_object_is_still_high(self):
        event = {"event_type": "ABANDONED_OBJECT"}
        assert determine_severity(event, reliability=None) == Severity.HIGH

    def test_unrecognized_event_type_defaults_to_low(self):
        event = {"event_type": "SOMETHING_NEW"}
        assert determine_severity(event, reliability=None) == Severity.LOW
