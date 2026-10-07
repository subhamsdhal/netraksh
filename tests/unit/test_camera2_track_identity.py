"""Camera 2 finite replay re-associates a continuous person after pose change."""

from types import SimpleNamespace

import numpy as np

from edge.main import EdgePipeline
from edge.tracking.continuity_guard import TrackContinuityGuard, compute_histogram
from shared.schemas import BoundingBox


def _pipeline(camera_id="cam-checkpoint-01"):
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.camera_id = camera_id
    pipeline.adapter = SimpleNamespace(source_kind="LOCAL_FINITE_FILE", preserve_finite_frames=True)
    pipeline.continuity_guard = TrackContinuityGuard()
    pipeline._track_id_map = {}
    pipeline._known_track_ids = {2}
    frame = np.zeros((540, 960, 3), dtype=np.uint8)
    frame[200:390, 390:520] = (35, 50, 65)
    old_box = BoundingBox(x1=411, y1=242, x2=484, y2=379)
    old_centroid = old_box.centroid
    pipeline._trajectories = {2: [old_centroid]}
    pipeline._track_last_snapshot = {2: {
        "histogram": compute_histogram(frame, old_box),
        "centroid": old_centroid,
    }}
    return pipeline, frame


def test_new_native_id_recovers_visible_prior_identity():
    pipeline, frame = _pipeline()
    new_box = BoundingBox(x1=412, y1=215, x2=504, y2=380)
    incoming = SimpleNamespace(track_id=4, bbox=new_box, trajectory=[new_box.centroid])

    pipeline._prime_camera2_lost_tracks([incoming])
    pipeline._apply_continuity_guard([incoming], frame)

    assert incoming.track_id == 2
    assert pipeline._track_id_map[4] == 2


def test_spatially_unrelated_person_keeps_new_identity():
    pipeline, frame = _pipeline()
    new_box = BoundingBox(x1=800, y1=200, x2=850, y2=350)
    incoming = SimpleNamespace(track_id=4, bbox=new_box, trajectory=[new_box.centroid])

    pipeline._prime_camera2_lost_tracks([incoming])
    pipeline._apply_continuity_guard([incoming], frame)

    assert incoming.track_id == 4


def test_camera1_continuity_order_is_unchanged():
    pipeline, frame = _pipeline(camera_id="cam-border-01")
    new_box = BoundingBox(x1=412, y1=215, x2=504, y2=380)
    incoming = SimpleNamespace(track_id=4, bbox=new_box, trajectory=[new_box.centroid])

    pipeline._prime_camera2_lost_tracks([incoming])

    assert pipeline.continuity_guard.get_pool_size() == 0
