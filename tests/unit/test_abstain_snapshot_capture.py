"""
NETRAKSH — Unit tests for edge/main.py's tiered evidence capture during a
FAILED-camera-health ABSTAIN heartbeat (should_capture_abstain_snapshot).

Real bug this fixes: a FAILED-health frame emitted an ABSTAIN heartbeat
every single frame but NEVER saved a snapshot at all (frame=None,
unconditional) -- so if the camera health monitor's own frozen/blur/
exposure detection had a false trigger, there was nothing to review. Now
captures a real encrypted snapshot periodically (see
shared/constants.py's ABSTAIN_SNAPSHOT_INTERVAL_SECONDS) instead of never,
without flooding local disk with one encrypted JPEG per frame during a
sustained outage.
"""
from edge.main import should_capture_abstain_snapshot
from shared.constants import ABSTAIN_SNAPSHOT_INTERVAL_SECONDS


class TestShouldCaptureAbstainSnapshot:
    def test_captures_immediately_on_first_call(self):
        # last_snapshot_time=0.0 (EdgePipeline's real initial value) and any
        # real now (time.time() is always >> 0) must always capture on the
        # very first FAILED-health frame of a run.
        assert should_capture_abstain_snapshot(last_snapshot_time=0.0, now=1_700_000_000.0) is True

    def test_does_not_capture_again_immediately_after(self):
        now = 1_700_000_000.0
        assert should_capture_abstain_snapshot(last_snapshot_time=now, now=now) is False
        assert should_capture_abstain_snapshot(last_snapshot_time=now, now=now + 1.0) is False

    def test_does_not_capture_just_before_the_interval_elapses(self):
        now = 1_700_000_000.0
        just_before = now + ABSTAIN_SNAPSHOT_INTERVAL_SECONDS - 0.01
        assert should_capture_abstain_snapshot(last_snapshot_time=now, now=just_before) is False

    def test_captures_exactly_at_the_interval_boundary(self):
        now = 1_700_000_000.0
        at_boundary = now + ABSTAIN_SNAPSHOT_INTERVAL_SECONDS
        assert should_capture_abstain_snapshot(last_snapshot_time=now, now=at_boundary) is True

    def test_captures_well_after_the_interval_elapses(self):
        now = 1_700_000_000.0
        long_after = now + ABSTAIN_SNAPSHOT_INTERVAL_SECONDS * 10
        assert should_capture_abstain_snapshot(last_snapshot_time=now, now=long_after) is True


class TestAbstainSnapshotIntervalConstant:
    def test_interval_is_a_positive_real_number(self):
        # Guards against a future edit accidentally setting this to 0 (which
        # would silently revert to "capture every frame" -- the exact disk-
        # flooding problem this throttle exists to prevent) or negative.
        assert ABSTAIN_SNAPSHOT_INTERVAL_SECONDS > 0
