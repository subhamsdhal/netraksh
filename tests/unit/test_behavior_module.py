"""
NETRAKSH — Unit tests for edge/rules/modules.py's BehaviorModule
(loitering + abandoned object). This module had ZERO dedicated unit tests
anywhere in this project before this file (confirmed by inspection --
every other task module has its own test_*.py; VirtualFenceModule and
LineCrossingModule are covered via test_line_crossing.py/
test_zone_normalization.py, FaceDetectionModule via
test_face_detection_recognition_wiring.py, but BehaviorModule had none).

TestAbandonedObjectGracePeriod below is the direct regression coverage for
a real, previously-undiscovered gap this same audit found: `self.
_disappeared_tracks` and `ABANDONED_DISAPPEAR_FRAMES` both already existed
(the constant in shared/constants.py, the dict in __init__) for exactly
the purpose of tolerating a brief detection/tracking miss before treating
a stationary object as genuinely abandoned -- but neither was ever wired
into the actual detection logic, which fired the instant a stationary
track disappeared for even a single frame.
"""
from __future__ import annotations

import edge.rules.modules as modules_mod
from edge.rules.modules import BehaviorModule
from shared.constants import DetectionClass, EventType
from shared.schemas import BoundingBox, Point, Polygon, TrackData, ZoneSchema


def _track(track_id, x1, y1, x2, y2, detection_class=DetectionClass.PERSON, confidence=0.9):
    return TrackData(
        track_id=track_id, detection_class=detection_class,
        bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2), confidence=confidence, trajectory=[],
    )


def _zone(zone_id="zone-1", zone_type="fence", points=None):
    points = points or [Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1), Point(x=0, y=1)]
    return ZoneSchema(zone_id=zone_id, camera_id="cam-1", name="Test zone", zone_type=zone_type,
                       polygon=Polygon(points=points), owning_command_id="COMMAND_A")


class TestLoitering:
    def test_no_event_before_dwell_threshold(self):
        module = BehaviorModule(zones=[_zone()], dwell_threshold_seconds=1000.0)
        events = []
        for _ in range(5):
            events += module.update([_track(1, 10, 10, 20, 20)], 100, 100)
        assert events == []

    def test_fires_once_dwell_threshold_exceeded(self, monkeypatch):
        module = BehaviorModule(zones=[_zone()], dwell_threshold_seconds=0.0)
        events = module.update([_track(1, 10, 10, 20, 20)], 100, 100)
        assert len(events) == 1
        assert events[0]["event_type"] == EventType.LOITERING
        assert events[0]["track_id"] == 1

    def test_does_not_refire_every_frame_while_still_dwelling(self):
        module = BehaviorModule(zones=[_zone()], dwell_threshold_seconds=0.0)
        first = module.update([_track(1, 10, 10, 20, 20)], 100, 100)
        second = module.update([_track(1, 10, 10, 20, 20)], 100, 100)
        assert len(first) == 1
        assert second == []

    def test_leaving_zone_resets_loitering_state(self):
        # bbox (10,10,20,20) in a 100x100 frame -> centroid (15,15) ->
        # normalized (0.15, 0.15) -- the zone must actually contain that.
        zone = _zone(points=[Point(x=0, y=0), Point(x=0.2, y=0), Point(x=0.2, y=0.2), Point(x=0, y=0.2)])
        module = BehaviorModule(zones=[zone], dwell_threshold_seconds=0.0)
        first = module.update([_track(1, 10, 10, 20, 20)], 100, 100)  # inside the zone
        assert len(first) == 1
        # bbox (890,890,910,910) in a 1000x1000 frame -> centroid (900,900)
        # -> normalized (0.9, 0.9) -- clearly outside the zone above.
        module.update([_track(1, 890, 890, 910, 910)], 1000, 1000)
        third = module.update([_track(1, 10, 10, 20, 20)], 100, 100)  # back inside -- can refire
        assert len(third) == 1


class TestAbandonedObjectGracePeriod:
    """Direct regression coverage for the disappear-grace-period fix."""

    def _module(self, monkeypatch, stationary_frames=3, disappear_frames=3):
        monkeypatch.setattr(modules_mod, "ABANDONED_STATIONARY_FRAMES", stationary_frames)
        monkeypatch.setattr(modules_mod, "ABANDONED_DISAPPEAR_FRAMES", disappear_frames)
        return BehaviorModule(zones=[], dwell_threshold_seconds=10_000.0)  # loitering never fires here

    def _make_stationary(self, module, track_id=1, frames=3, cls=DetectionClass.VEHICLE):
        # The first update() at a given position only REGISTERS the track
        # (stationary_frames starts at 0); the counter only increments on
        # each subsequent call at the same position. +1 call is needed to
        # actually reach `stationary_frames == frames`.
        for _ in range(frames + 1):
            module.update([_track(track_id, 10, 10, 20, 20, detection_class=cls)], 100, 100)

    def test_does_not_fire_while_track_still_present(self, monkeypatch):
        module = self._module(monkeypatch)
        events = []
        for _ in range(10):
            events += module.update([_track(1, 10, 10, 20, 20, detection_class=DetectionClass.VEHICLE)], 100, 100)
        assert events == []

    def test_fires_after_disappearing_for_the_full_grace_period(self, monkeypatch):
        module = self._module(monkeypatch, stationary_frames=3, disappear_frames=3)
        self._make_stationary(module, frames=3)
        events = []
        for _ in range(3):
            events += module.update([], 100, 100)  # track gone
        assert len(events) == 1
        assert events[0]["event_type"] == EventType.ABANDONED_OBJECT
        assert events[0]["track_id"] == 1

    def test_does_not_fire_before_grace_period_elapses(self, monkeypatch):
        module = self._module(monkeypatch, stationary_frames=3, disappear_frames=5)
        self._make_stationary(module, frames=3)
        events = []
        for _ in range(4):  # one short of the 5-frame grace period
            events += module.update([], 100, 100)
        assert events == []

    def test_reappearing_within_grace_period_cancels_the_candidate(self, monkeypatch):
        """The core fix: a brief detection/tracking miss must NOT become a
        false abandoned-object alert."""
        module = self._module(monkeypatch, stationary_frames=3, disappear_frames=5)
        self._make_stationary(module, frames=3)
        module.update([], 100, 100)  # missing for 1 frame
        module.update([], 100, 100)  # missing for 2 frames
        # Tracking recovers it before the 5-frame grace period elapses.
        reappear_events = module.update([_track(1, 10, 10, 20, 20, detection_class=DetectionClass.VEHICLE)], 100, 100)
        assert reappear_events == []
        # Even if it now disappears again, waiting the full period from here
        # is required -- the earlier missing frames must not carry over.
        events = []
        for _ in range(4):
            events += module.update([], 100, 100)
        assert events == []  # only 4 of the required 5 frames since reappearing

    def test_not_stationary_long_enough_never_becomes_a_candidate(self, monkeypatch):
        module = self._module(monkeypatch, stationary_frames=10, disappear_frames=1)
        self._make_stationary(module, frames=3)  # short of the 10-frame stationary requirement
        events = []
        for _ in range(5):
            events += module.update([], 100, 100)
        assert events == []

    def test_candidate_fires_only_once_not_repeatedly(self, monkeypatch):
        module = self._module(monkeypatch, stationary_frames=3, disappear_frames=2)
        self._make_stationary(module, frames=3)
        events = []
        for _ in range(6):  # well past the grace period
            events += module.update([], 100, 100)
        assert len(events) == 1

    def test_two_independent_tracks_tracked_separately(self, monkeypatch):
        module = self._module(monkeypatch, stationary_frames=3, disappear_frames=2)
        for _ in range(4):  # +1: see _make_stationary's comment on the registration-frame off-by-one
            module.update([
                _track(1, 10, 10, 20, 20, detection_class=DetectionClass.VEHICLE),
                _track(2, 50, 50, 60, 60, detection_class=DetectionClass.UNKNOWN),
            ], 100, 100)
        # Only track 1 disappears; track 2 stays present.
        events = []
        for _ in range(3):
            events += module.update([_track(2, 50, 50, 60, 60, detection_class=DetectionClass.UNKNOWN)], 100, 100)
        assert len(events) == 1
        assert events[0]["track_id"] == 1
