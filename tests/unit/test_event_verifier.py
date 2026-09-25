"""
NETRAKSH — Unit tests for the Event Verification state machine
(architecture v4 §9, edge/temporal/event_verifier.py).

Covers the exact lifecycle NETRAKSH's pitch depends on:
OBSERVED -> CANDIDATE -> [held while UNCERTAIN] -> VERIFIED -> ALERTED,
plus cooldown and stale-candidate expiry.
"""
from edge.temporal.event_verifier import DEFAULT_REQUIRED_CONFIRMATIONS, EventVerifier


def _payload(track_id=1, zone_id="zone-1", event_type="LOITERING", **extra):
    d = {"track_id": track_id, "zone_id": zone_id, "event_type": event_type}
    d.update(extra)
    return d


class TestSingleConfirmationEvents:
    """Rules with their own temporal persistence may verify immediately."""

    def test_loitering_verifies_on_first_detected_observation(self):
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 5, "LOITERING", "zone-1")
        state, verified = v.observe(key, "LOITERING", _payload(track_id=5), frame_count=1, reliability_is_detected=True)
        assert state == "ALERTED"
        assert verified is not None
        assert verified["track_id"] == 5

    def test_loitering_does_not_verify_while_uncertain(self):
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 5, "LOITERING", "zone-1")
        state, verified = v.observe(key, "LOITERING", _payload(track_id=5), frame_count=1, reliability_is_detected=False)
        assert state == "CANDIDATE"
        assert verified is None
        # Held, not discarded — a later DETECTED frame still verifies it.
        state, verified = v.observe(key, "LOITERING", _payload(track_id=5), frame_count=2, reliability_is_detected=True)
        assert state == "ALERTED"
        assert verified is not None

    def test_fence_crossing_requires_a_second_observation(self):
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 7, "VIRTUAL_FENCE_CROSSING", "zone-1")
        payload = _payload(track_id=7, event_type="VIRTUAL_FENCE_CROSSING", direction="OUTSIDE_TO_RESTRICTED")

        state, verified = v.observe(key, "VIRTUAL_FENCE_CROSSING", payload, 1, True)
        assert state == "CANDIDATE" and verified is None
        state, verified = v.observe(key, "VIRTUAL_FENCE_CROSSING", payload, 2, True)
        assert state == "ALERTED" and verified is not None

    def test_line_crossing_requires_a_second_observation(self):
        assert DEFAULT_REQUIRED_CONFIRMATIONS["LINE_CROSSING"] == 2
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 8, "LINE_CROSSING", "line-1")
        payload = _payload(track_id=8, zone_id="line-1", event_type="LINE_CROSSING", direction="A_TO_B")

        state, verified = v.observe(key, "LINE_CROSSING", payload, 1, True)
        assert state == "CANDIDATE" and verified is None
        state, verified = v.observe(key, "LINE_CROSSING", payload, 2, True)
        assert state == "ALERTED" and verified is not None

    def test_uncertain_frame_holds_progress_without_resetting_it(self):
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 7, "VIRTUAL_FENCE_CROSSING", "zone-1")
        payload = _payload(track_id=7, event_type="VIRTUAL_FENCE_CROSSING", direction="OUTSIDE_TO_RESTRICTED")

        state, verified = v.observe(key, "VIRTUAL_FENCE_CROSSING", payload, 1, False)  # held, not counted, not reset
        assert state == "CANDIDATE" and verified is None
        state, verified = v.observe(key, "VIRTUAL_FENCE_CROSSING", payload, 2, True)  # confirm 1/2
        assert state == "CANDIDATE" and verified is None
        state, verified = v.observe(key, "VIRTUAL_FENCE_CROSSING", payload, 3, True)  # confirm 2/2
        assert state == "ALERTED" and verified is not None


class TestMultiFrameConfirmationEvents:
    def test_noisy_single_anpr_read_is_not_alerted(self):
        assert DEFAULT_REQUIRED_CONFIRMATIONS["ANPR_READ"] == 2
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 10, "ANPR_READ", "checkpoint")
        state, verified = v.observe(key, "ANPR_READ", _payload(10, "checkpoint", "ANPR_READ"), 1, True)
        assert state == "CANDIDATE" and verified is None

    def test_face_detection_confirms_on_second_frame(self):
        assert DEFAULT_REQUIRED_CONFIRMATIONS["FACE_DETECTED"] == 2
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 11, "FACE_DETECTED", "verification")
        payload = _payload(11, "verification", "FACE_DETECTED")
        v.observe(key, "FACE_DETECTED", payload, 1, True)
        state, verified = v.observe(key, "FACE_DETECTED", payload, 2, True)
        assert state == "ALERTED" and verified is not None


class TestExpiry:
    def test_candidate_expires_without_reconfirmation(self):
        v = EventVerifier(max_gap_frames=5)
        key = EventVerifier.make_key("cam-1", 9, "VIRTUAL_FENCE_CROSSING", "zone-1")
        v.observe(key, "VIRTUAL_FENCE_CROSSING", _payload(track_id=9, event_type="VIRTUAL_FENCE_CROSSING"), 1, False) # Using False so it stays a CANDIDATE
        assert v.get_pending_count() == 1
        expired = v.expire_stale(current_frame=10)  # 9 frames later, > max_gap_frames
        assert key in expired
        assert v.get_pending_count() == 0

    def test_candidate_not_expired_within_gap_window(self):
        v = EventVerifier(max_gap_frames=5)
        key = EventVerifier.make_key("cam-1", 9, "VIRTUAL_FENCE_CROSSING", "zone-1")
        v.observe(key, "VIRTUAL_FENCE_CROSSING", _payload(track_id=9, event_type="VIRTUAL_FENCE_CROSSING"), 1, False)
        expired = v.expire_stale(current_frame=4)  # only 3 frames later
        assert expired == []
        assert v.get_pending_count() == 1

    def test_verified_alerted_key_is_not_expired(self):
        v = EventVerifier()
        key = EventVerifier.make_key("cam-1", 3, "LOITERING", "zone-1")
        v.observe(key, "LOITERING", _payload(track_id=3), 1, True)  # auto-verifies (required=1)
        assert v.get_state(key) == "ALERTED"
        v.expire_stale(current_frame=1000)
        assert v.get_state(key) == "ALERTED"  # only pending CANDIDATEs expire


class TestCooldown:
    def test_repeat_alert_suppressed_within_cooldown(self):
        v = EventVerifier(cooldown_seconds=9999)
        key = EventVerifier.make_key("cam-1", 3, "LOITERING", "zone-1")
        _, verified1 = v.observe(key, "LOITERING", _payload(track_id=3), 1, True)
        assert verified1 is not None
        _, verified2 = v.observe(key, "LOITERING", _payload(track_id=3), 2, True)
        assert verified2 is None  # still in cooldown, no duplicate alert

    def test_new_episode_after_cooldown_elapses(self):
        v = EventVerifier(cooldown_seconds=0)  # cooldown elapses immediately
        key = EventVerifier.make_key("cam-1", 3, "LOITERING", "zone-1")
        _, verified1 = v.observe(key, "LOITERING", _payload(track_id=3), 1, True)
        assert verified1 is not None
        _, verified2 = v.observe(key, "LOITERING", _payload(track_id=3), 2, True)
        assert verified2 is not None  # cooldown elapsed -> genuinely new episode


class TestKeyIsolation:
    def test_different_tracks_do_not_share_confirmation_progress(self):
        v = EventVerifier(required_confirmations={"TEST_EVENT": 2})
        key_a = EventVerifier.make_key("cam-1", 1, "TEST_EVENT", "zone-1")
        key_b = EventVerifier.make_key("cam-1", 2, "TEST_EVENT", "zone-1")
        payload_a = _payload(track_id=1, event_type="TEST_EVENT")
        payload_b = _payload(track_id=2, event_type="TEST_EVENT")

        v.observe(key_a, "TEST_EVENT", payload_a, 1, True)
        # track 2 has only one confirmation — must not benefit from track 1's progress
        state_b, verified_b = v.observe(key_b, "TEST_EVENT", payload_b, 1, True)
        assert state_b == "CANDIDATE" and verified_b is None
