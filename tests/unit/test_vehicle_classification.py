"""
NETRAKSH — Unit tests for real vehicle sub-classification (SIH PS 26187:
"vehicle detection AND classification", not detection alone).

Does not exercise YOLO/ultralytics itself — _YOLO_VEHICLE_SUBTYPE_MAP is a
pure module-level dict, testable without loading the real model, same
posture as tests/unit/test_detector_tracker_config.py.
"""
import os
import tempfile
from datetime import datetime

import pytest

from edge.detection.detector import _YOLO_CLASS_MAP, _YOLO_VEHICLE_SUBTYPE_MAP
from edge.evidence.packager import EdgeKeyManager, EvidenceChainStore, EvidencePackager
from shared.constants import CameraHealthState, DecisionState, DetectionClass, SceneCondition, VehicleSubtype
from shared.schemas import BoundingBox, CameraHealthReport, ReliabilityDecision, SceneConditionReport, TrackData


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        yield d


@pytest.fixture
def key_manager(temp_dir):
    km = EdgeKeyManager(
        private_key_path=os.path.join(temp_dir, "test.key"),
        public_key_path=os.path.join(temp_dir, "test.pub"),
    )
    km.load_or_generate(allow_generate=True)
    return km


@pytest.fixture
def chain_store(temp_dir):
    return EvidenceChainStore(os.path.join(temp_dir, "test_chain.db"))


def _reliability():
    return ReliabilityDecision(
        decision_state=DecisionState.DETECTED,
        decision_reason="test",
        camera_health=CameraHealthState.OK,
        scene_condition=SceneCondition.CLEAR_DAY,
        detector_confidence=0.9,
        applied_threshold=0.45,
    )


def _health():
    return CameraHealthReport(
        camera_id="cam-veh", health_state=CameraHealthState.OK,
        health_reason="ok", health_timestamp=datetime.utcnow(),
    )


def _condition():
    return SceneConditionReport(
        camera_id="cam-veh", condition=SceneCondition.CLEAR_DAY,
        brightness_mean=128.0, contrast_std=50.0, glare_fraction=0.01,
    )


class TestYoloVehicleSubtypeMap:
    def test_every_vehicle_subtype_class_id_maps_to_vehicle_in_the_main_map(self):
        # Real invariant this whole feature depends on: every class id with
        # a real subtype must also resolve to DetectionClass.VEHICLE in the
        # existing map, or a "car" could show up with detection_class
        # something other than "vehicle" -- a real, silent inconsistency.
        for class_id in _YOLO_VEHICLE_SUBTYPE_MAP:
            assert _YOLO_CLASS_MAP[class_id] == DetectionClass.VEHICLE

    def test_known_coco_class_ids_map_to_the_correct_real_subtype(self):
        assert _YOLO_VEHICLE_SUBTYPE_MAP[2] == VehicleSubtype.CAR
        assert _YOLO_VEHICLE_SUBTYPE_MAP[3] == VehicleSubtype.MOTORCYCLE
        assert _YOLO_VEHICLE_SUBTYPE_MAP[5] == VehicleSubtype.BUS
        assert _YOLO_VEHICLE_SUBTYPE_MAP[7] == VehicleSubtype.TRUCK

    def test_person_class_id_has_no_vehicle_subtype(self):
        assert 0 not in _YOLO_VEHICLE_SUBTYPE_MAP

    def test_bicycle_class_id_has_no_vehicle_subtype(self):
        # COCO class 1 is bicycle. It must not be silently relabelled as a
        # person or vehicle by a runtime that does not support that class.
        assert 1 not in _YOLO_VEHICLE_SUBTYPE_MAP
        assert 1 not in _YOLO_CLASS_MAP
        assert _YOLO_CLASS_MAP[0] == DetectionClass.PERSON


class TestTrackDataVehicleSubtype:
    def test_defaults_to_none(self):
        track = TrackData(
            track_id=1, detection_class=DetectionClass.PERSON,
            bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), confidence=0.9,
        )
        assert track.vehicle_subtype is None

    def test_real_value_round_trips(self):
        track = TrackData(
            track_id=1, detection_class=DetectionClass.VEHICLE,
            bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), confidence=0.9,
            vehicle_subtype=VehicleSubtype.TRUCK,
        )
        assert track.vehicle_subtype == VehicleSubtype.TRUCK


class TestEvidencePackagerCarriesVehicleSubtype:
    def test_package_includes_real_vehicle_subtype_from_track(self, temp_dir, key_manager, chain_store):
        packager = EvidencePackager(
            camera_id="cam-veh", key_manager=key_manager, chain_store=chain_store,
            clip_storage_dir=os.path.join(temp_dir, "clips"),
        )
        track = TrackData(
            track_id=42, detection_class=DetectionClass.VEHICLE,
            bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), confidence=0.95,
            vehicle_subtype=VehicleSubtype.BUS,
        )

        ep, _seq = packager.package(
            track=track, reliability=_reliability(), health=_health(), condition=_condition(),
            zone_id="zone-1", event_overrides={}, frame=None,
        )
        assert ep.vehicle_subtype == VehicleSubtype.BUS
        assert ep.detection_class == DetectionClass.VEHICLE

    def test_package_leaves_vehicle_subtype_none_for_a_person_track(self, temp_dir, key_manager, chain_store):
        packager = EvidencePackager(
            camera_id="cam-veh2", key_manager=key_manager, chain_store=chain_store,
            clip_storage_dir=os.path.join(temp_dir, "clips2"),
        )
        track = TrackData(
            track_id=7, detection_class=DetectionClass.PERSON,
            bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), confidence=0.95,
        )

        ep, _seq = packager.package(
            track=track, reliability=_reliability(), health=_health(), condition=_condition(),
            zone_id="zone-1", event_overrides={}, frame=None,
        )
        assert ep.vehicle_subtype is None

    def test_package_leaves_vehicle_subtype_none_when_track_is_none(self, temp_dir, key_manager, chain_store):
        # The ABSTAIN/heartbeat path (edge/main.py) calls package() with
        # track=None -- must not raise on getattr(None, "vehicle_subtype", ...).
        packager = EvidencePackager(
            camera_id="cam-veh3", key_manager=key_manager, chain_store=chain_store,
            clip_storage_dir=os.path.join(temp_dir, "clips3"),
        )

        ep, _seq = packager.package(
            track=None, reliability=_reliability(), health=_health(), condition=_condition(),
            zone_id="zone-1", event_overrides={}, frame=None,
        )
        assert ep.vehicle_subtype is None
