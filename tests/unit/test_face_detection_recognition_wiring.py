"""
NETRAKSH — Unit tests for FaceDetectionModule's wiring to a real
WatchlistFaceRecognizer (edge/rules/modules.py::_attempt_recognition).

Uses a minimal real stand-in recognizer object (not cv2 itself — that's
tests/unit/test_face_recognition.py's job) to test this module's own
integration logic in isolation: does it call the recognizer with the
right crop, does it merge a real match into the result dict, does it
leave the result unchanged when there's nothing to recognize.
"""
import numpy as np
import pytest

from edge.rules.modules import FaceDetectionModule
from shared.schemas import BoundingBox, Point, Polygon, ZoneSchema


class _FakeRecognizer:
    """A real, controllable stand-in — not cv2 — with the exact interface
    FaceDetectionModule actually calls."""

    def __init__(self, trained=True, match=None):
        self._trained = trained
        self._match = match
        self.calls = []

    def is_trained(self):
        return self._trained

    def recognize(self, face_crop):
        self.calls.append(face_crop.shape)
        return self._match


def _verification_zone() -> ZoneSchema:
    return ZoneSchema(
        zone_id="verify-1", camera_id="cam-1", name="Checkpoint", zone_type="verification",
        polygon=Polygon(points=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1), Point(x=0, y=1)]),
        owning_command_id="COMMAND_A",
    )


def _person_crop() -> np.ndarray:
    return (np.random.RandomState(1).rand(120, 80, 3) * 255).astype(np.uint8)


class TestAttemptRecognitionNoOp:
    def test_no_recognizer_leaves_result_unchanged(self):
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=None)
        result = {"event_type": "FACE_DETECTED", "face_bbox": BoundingBox(x1=10, y1=10, x2=40, y2=40)}
        module._attempt_lbph_recognition(result, _person_crop())
        assert "face_match_person_id" not in result

    def test_untrained_recognizer_leaves_result_unchanged(self):
        fake = _FakeRecognizer(trained=False)
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=fake)
        result = {"event_type": "FACE_DETECTED", "face_bbox": BoundingBox(x1=10, y1=10, x2=40, y2=40)}
        module._attempt_lbph_recognition(result, _person_crop())
        assert "face_match_person_id" not in result
        assert fake.calls == []  # never even called recognize() on an untrained recognizer

    def test_no_face_bbox_leaves_result_unchanged(self):
        fake = _FakeRecognizer(trained=True, match={"person_id": "p1", "name": "Alice", "confidence": 10.0})
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=fake)
        result = {"event_type": "FACE_DETECTED"}  # no face_bbox key at all
        module._attempt_lbph_recognition(result, _person_crop())
        assert "face_match_person_id" not in result

    def test_degenerate_bbox_leaves_result_unchanged(self):
        """A face_bbox that doesn't crop to any real pixels (x2<=x1) must
        not crash or fabricate a match."""
        fake = _FakeRecognizer(trained=True, match={"person_id": "p1", "name": "Alice", "confidence": 10.0})
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=fake)
        result = {"event_type": "FACE_DETECTED", "face_bbox": BoundingBox(x1=50, y1=50, x2=50, y2=50)}
        module._attempt_lbph_recognition(result, _person_crop())
        assert "face_match_person_id" not in result

    def test_no_real_match_leaves_result_unchanged(self):
        fake = _FakeRecognizer(trained=True, match=None)
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=fake)
        result = {"event_type": "FACE_DETECTED", "face_bbox": BoundingBox(x1=10, y1=10, x2=40, y2=40)}
        module._attempt_lbph_recognition(result, _person_crop())
        assert "face_match_person_id" not in result
        assert len(fake.calls) == 1  # did genuinely attempt recognition


class TestHaarCascadeRealLoad:
    """The actual fix: a real cascade XML is bundled in the repo
    (edge/detection/cascades/haarcascade_frontalface_default.xml) as a
    fallback for OpenCV builds (like this project's
    opencv-contrib-python-headless) that ship no cascade data files at all.
    Confirms real detection is actually possible in this environment now,
    not just that a missing one no longer crashes."""

    def test_face_detection_module_loads_a_real_non_empty_cascade(self):
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=None)
        assert module._face_cascade.empty() is False

    def test_bundled_cascade_file_loads_directly(self):
        import cv2
        from pathlib import Path

        bundled_path = (
            Path(__file__).resolve().parents[2] / "edge" / "detection" / "cascades" /
            "haarcascade_frontalface_default.xml"
        )
        assert bundled_path.exists()
        cascade = cv2.CascadeClassifier(str(bundled_path))
        assert cascade.empty() is False


class TestHaarCascadeEmptyClassifierDoesNotCrash:
    """Regression test for a real, previously-uncaught crash: on an OpenCV
    build whose data files don't include the bundled Haar cascade XML (e.g.
    opencv-contrib-python-headless, installed in this project for
    cv2.face/LBPH watchlist recognition -- see docs/LIMITATIONS.md),
    cv2.CascadeClassifier(...) silently constructs an EMPTY classifier.
    Calling detectMultiScale() on it raises a real cv2.error that, before
    this fix, crashed edge/main.py's entire real-time frame loop on the
    first person track inside a verification zone -- confirmed directly
    against demo/videos/vtest.avi, not hypothesized."""

    def test_empty_cascade_returns_none_instead_of_raising(self):
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=None)
        module._face_cascade = _EmptyCascade()  # force the real failure mode
        result = module._detect_haar(track=None, crop=_person_crop(), zone_id="verify-1")
        assert result is None

    def test_none_cascade_returns_none_instead_of_raising(self):
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=None)
        module._face_cascade = None
        result = module._detect_haar(track=None, crop=_person_crop(), zone_id="verify-1")
        assert result is None


class _EmptyCascade:
    """Stands in for a real cv2.CascadeClassifier that failed to load its
    XML file -- .empty() is the real, documented way OpenCV signals this."""

    def empty(self):
        return True

    def detectMultiScale(self, *args, **kwargs):
        raise AssertionError("must not be called on an empty cascade")


class TestAttemptRecognitionRealMatch:
    def test_a_real_match_is_merged_into_the_result_dict(self):
        fake = _FakeRecognizer(trained=True, match={"person_id": "p-42", "name": "Alice", "confidence": 12.5})
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=fake)
        result = {"event_type": "FACE_DETECTED", "track_id": 7, "face_bbox": BoundingBox(x1=10, y1=10, x2=40, y2=40)}

        module._attempt_lbph_recognition(result, _person_crop())

        assert result["face_match_person_id"] == "p-42"
        assert result["face_match_person_name"] == "Alice"
        assert result["face_match_confidence"] == 12.5
        # Everything else in the result dict is untouched.
        assert result["track_id"] == 7
        assert result["event_type"] == "FACE_DETECTED"

    def test_recognizer_receives_the_real_face_sub_crop_not_the_whole_person_crop(self):
        fake = _FakeRecognizer(trained=True, match={"person_id": "p1", "name": "Alice", "confidence": 5.0})
        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=fake)
        person_crop = _person_crop()  # 120x80
        result = {"event_type": "FACE_DETECTED", "face_bbox": BoundingBox(x1=10, y1=10, x2=40, y2=40)}

        module._attempt_lbph_recognition(result, person_crop)

        assert len(fake.calls) == 1
        h, w = fake.calls[0][:2]
        assert (h, w) == (30, 30)  # y2-y1, x2-x1 -- the real face sub-region, not the full 120x80 crop

    def test_recognizer_error_is_caught_and_leaves_result_unchanged(self):
        class _RaisingRecognizer:
            def is_trained(self):
                return True

            def recognize(self, face_crop):
                raise RuntimeError("simulated real failure")

        module = FaceDetectionModule(zones=[_verification_zone()], recognizer=_RaisingRecognizer())
        result = {"event_type": "FACE_DETECTED", "face_bbox": BoundingBox(x1=10, y1=10, x2=40, y2=40)}
        module._attempt_lbph_recognition(result, _person_crop())  # must not raise
        assert "face_match_person_id" not in result
