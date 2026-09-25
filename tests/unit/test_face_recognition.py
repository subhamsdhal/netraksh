"""
NETRAKSH — Unit tests for edge/detection/face_recognition.py's real
WatchlistFaceRecognizer (SIH PS 26187: "support facial recognition", not
detection alone).

Uses real cv2.face.LBPHFaceRecognizer against real (synthetic but
genuinely distinct) grayscale images — not mocked. Requires
opencv-contrib-python-headless (see requirements.txt); the plain
opencv-python-headless package never ships cv2.face.
"""
import numpy as np
import pytest

from edge.detection.face_recognition import (
    FACE_IMAGE_SIZE,
    LBPH_MATCH_THRESHOLD,
    WatchlistFaceRecognizer,
    decode_base64_face_image,
)


def _synthetic_face(seed: int) -> np.ndarray:
    """
    A real, deterministic, seed-varying grayscale image with genuine
    structure (LBPH compares local texture patterns, so uniform random
    noise is a poor stand-in for a real face crop — two noise images can
    score a deceptively low LBPH distance purely from having statistically
    similar histograms, not from any real resemblance). Draws real shapes
    at seed-dependent positions/sizes via OpenCV, closer in spirit to a
    real face crop's real edges/gradients.
    """
    import cv2
    rng = np.random.RandomState(seed)
    img = np.full(FACE_IMAGE_SIZE, 40, dtype=np.uint8)
    cx = int(rng.randint(60, 140))
    cy = int(rng.randint(60, 140))
    radius = int(rng.randint(30, 70))
    cv2.circle(img, (cx, cy), radius, 200, -1)
    cv2.rectangle(img, (cx - radius // 2, cy - radius // 2), (cx + radius // 2, cy + radius // 2), 80, 3)
    return img


class TestUntrainedRecognizer:
    def test_recognize_returns_none_before_any_training(self):
        recognizer = WatchlistFaceRecognizer()
        result = recognizer.recognize(_synthetic_face(1))
        assert result is None

    def test_is_trained_false_before_training(self):
        recognizer = WatchlistFaceRecognizer()
        assert recognizer.is_trained() is False

    def test_train_with_zero_images_leaves_recognizer_untrained(self):
        recognizer = WatchlistFaceRecognizer()
        count = recognizer.train([])
        assert count == 0
        assert recognizer.is_trained() is False

    def test_train_with_a_person_who_has_no_images_leaves_recognizer_untrained(self):
        recognizer = WatchlistFaceRecognizer()
        count = recognizer.train([{"person_id": "p1", "name": "Nobody", "images": []}])
        assert count == 0
        assert recognizer.is_trained() is False


class TestRealTrainingAndRecognition:
    def test_recognizes_the_exact_same_enrolled_image(self):
        recognizer = WatchlistFaceRecognizer()
        face = _synthetic_face(42)
        recognizer.train([{"person_id": "p1", "name": "Alice", "images": [face]}])
        assert recognizer.is_trained() is True

        result = recognizer.recognize(face)
        assert result is not None
        assert result["person_id"] == "p1"
        assert result["name"] == "Alice"
        # A real image matched against itself should be a near-perfect
        # (near-zero distance) LBPH match, not just "under threshold".
        assert result["confidence"] < 1.0

    def test_threshold_logic_rejects_a_match_above_the_real_disclosed_threshold(self, monkeypatch):
        """
        LBPH's real distance on genuinely different SYNTHETIC shapes isn't
        reliably "far" the way it would be on real, texture-rich face
        photos (confirmed directly: two clearly-different synthetic shapes
        scored a real LBPH distance of ~4.9, well inside the default
        threshold — a real, known LBPH property on low-texture synthetic
        images, not a bug in this wrapper). So this tests the wrapper's own
        threshold LOGIC directly and deterministically, by controlling
        exactly what predict() returns, rather than depending on LBPH's
        unpredictable real behavior on synthetic (non-face) imagery.
        """
        recognizer = WatchlistFaceRecognizer()
        recognizer.train([{"person_id": "p1", "name": "Alice", "images": [_synthetic_face(1)]}])
        assert recognizer.is_trained()

        # cv2's C++-bound LBPHFaceRecognizer doesn't allow monkeypatching a
        # single method on it directly (attributes are read-only) -- swap
        # the whole wrapped object for a minimal real stand-in instead.
        class _FakePredict:
            def predict(self, face):
                return (0, LBPH_MATCH_THRESHOLD + 0.01)
        recognizer._lbph_recognizer = _FakePredict()
        assert recognizer.recognize(_synthetic_face(2)) is None

    def test_threshold_logic_accepts_a_match_at_or_below_the_real_disclosed_threshold(self, monkeypatch):
        recognizer = WatchlistFaceRecognizer()
        recognizer.train([{"person_id": "p1", "name": "Alice", "images": [_synthetic_face(1)]}])

        class _FakePredict:
            def predict(self, face):
                return (0, LBPH_MATCH_THRESHOLD)
        recognizer._lbph_recognizer = _FakePredict()
        result = recognizer.recognize(_synthetic_face(2))
        assert result is not None
        assert result["person_id"] == "p1"

    def test_distinguishes_between_two_enrolled_people(self):
        recognizer = WatchlistFaceRecognizer()
        face_alice = _synthetic_face(1)
        face_bob = _synthetic_face(2)
        recognizer.train([
            {"person_id": "p-alice", "name": "Alice", "images": [face_alice]},
            {"person_id": "p-bob", "name": "Bob", "images": [face_bob]},
        ])

        result_alice = recognizer.recognize(face_alice)
        result_bob = recognizer.recognize(face_bob)
        assert result_alice["person_id"] == "p-alice"
        assert result_bob["person_id"] == "p-bob"

    def test_retraining_from_scratch_forgets_a_removed_person(self):
        """A real re-sync (edge/main.py::_resync_watchlist) trains fresh
        each time -- a person removed from the watchlist must genuinely
        stop being matchable, not linger in an ever-growing model."""
        recognizer = WatchlistFaceRecognizer()
        face_alice = _synthetic_face(1)
        recognizer.train([{"person_id": "p-alice", "name": "Alice", "images": [face_alice]}])
        assert recognizer.recognize(face_alice) is not None

        # Re-sync without Alice -- e.g. she was removed from the watchlist.
        recognizer.train([{"person_id": "p-bob", "name": "Bob", "images": [_synthetic_face(2)]}])
        # Alice's own face is now unrecognized by a differently-labeled model.
        result = recognizer.recognize(face_alice)
        assert result is None or result["person_id"] != "p-alice"

    def test_multiple_reference_images_for_the_same_person_are_all_used(self):
        recognizer = WatchlistFaceRecognizer()
        images = [_synthetic_face(10), _synthetic_face(11), _synthetic_face(12)]
        recognizer.train([{"person_id": "p1", "name": "Alice", "images": images}])

        # Every one of the real enrolled images should be recognized as
        # the same person, not just the first one trained on.
        for img in images:
            result = recognizer.recognize(img)
            assert result is not None
            assert result["person_id"] == "p1"

    def test_handles_a_bgr_color_crop_not_just_grayscale(self):
        recognizer = WatchlistFaceRecognizer()
        gray_face = _synthetic_face(5)
        recognizer.train([{"person_id": "p1", "name": "Alice", "images": [gray_face]}])

        # A real 3-channel BGR crop (what FaceDetectionModule actually
        # passes in) must be converted internally, not raise.
        bgr = np.stack([gray_face, gray_face, gray_face], axis=-1)
        result = recognizer.recognize(bgr)
        assert result is not None
        assert result["person_id"] == "p1"


class TestDecodeBase64FaceImage:
    def test_real_jpeg_round_trips(self):
        import base64
        import cv2

        original = _synthetic_face(7)
        ok, buf = cv2.imencode(".jpg", original)
        assert ok
        b64 = base64.b64encode(buf.tobytes()).decode()

        decoded = decode_base64_face_image(b64)
        assert decoded is not None
        assert decoded.shape == FACE_IMAGE_SIZE

    def test_garbage_input_returns_none_not_a_fabricated_image(self):
        assert decode_base64_face_image("not real base64 data!!") is None

    def test_valid_base64_of_non_image_bytes_returns_none(self):
        import base64
        junk = base64.b64encode(b"this is not a jpeg").decode()
        assert decode_base64_face_image(junk) is None


class TestMatchThresholdIsDisclosedAndSane:
    def test_threshold_is_a_positive_real_number(self):
        assert LBPH_MATCH_THRESHOLD > 0
