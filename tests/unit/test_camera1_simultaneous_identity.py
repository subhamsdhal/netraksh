"""Camera 1 must not collapse two simultaneous detections into one ID."""

from types import SimpleNamespace
import time

import numpy as np

from edge.main import EdgePipeline
from edge.tracking.continuity_guard import TrackContinuityGuard, compute_histogram
from shared.schemas import BoundingBox


def _track(track_id, box):
    return SimpleNamespace(track_id=track_id, bbox=box, trajectory=[box.centroid])


def _pipeline():
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.camera_id = "cam-border-01"
    pipeline.adapter = SimpleNamespace(source_kind="LOCAL_FINITE_FILE", preserve_finite_frames=True)
    pipeline.continuity_guard = TrackContinuityGuard()
    pipeline._track_id_map = {}
    pipeline._known_track_ids = set()
    pipeline._track_last_snapshot = {}
    return pipeline


def test_existing_remap_cannot_hide_second_visible_person():
    pipeline = _pipeline()
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    left = BoundingBox(x1=580, y1=250, x2=618, y2=355)
    right = BoundingBox(x1=620, y1=250, x2=655, y2=355)
    pipeline._track_id_map = {13: 11}
    pipeline._known_track_ids = {11}
    pipeline._track_last_snapshot = {11: {"centroid": right.centroid}}

    tracks = [_track(13, left), _track(11, right)]
    pipeline._apply_continuity_guard(tracks, frame)

    assert [track.track_id for track in tracks] == [13, 11]
    assert pipeline._track_id_map[13] == 13
    assert len({track.track_id for track in tracks}) == len(tracks)

    next_tracks = [_track(13, left), _track(11, right)]
    pipeline._apply_continuity_guard(next_tracks, frame)
    assert [track.track_id for track in next_tracks] == [13, 11]


def test_lost_pool_cannot_reassociate_to_person_active_in_same_packet():
    pipeline = _pipeline()
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    frame[250:355, 580:655] = (20, 40, 100)
    left = BoundingBox(x1=580, y1=250, x2=618, y2=355)
    right = BoundingBox(x1=620, y1=250, x2=655, y2=355)
    pipeline._known_track_ids = {11}
    pipeline._track_last_snapshot = {11: {"centroid": right.centroid}}
    pipeline.continuity_guard.remember_lost(
        11, compute_histogram(frame, right), right.centroid, [right.centroid],
        now=time.time(),
    )
    tracks = [_track(13, left), _track(11, right)]

    pipeline._apply_continuity_guard(tracks, frame)

    assert [track.track_id for track in tracks] == [13, 11]
    assert len({track.track_id for track in tracks}) == len(tracks)


def test_remapped_id_cannot_steal_new_native_id_not_yet_known():
    pipeline = _pipeline()
    frame = np.zeros((720, 960, 3), dtype=np.uint8)
    left = BoundingBox(x1=580, y1=250, x2=618, y2=355)
    right = BoundingBox(x1=620, y1=250, x2=655, y2=355)
    pipeline._track_id_map = {13: 11}
    pipeline._track_last_snapshot = {11: {"centroid": right.centroid}}
    tracks = [_track(13, left), _track(11, right)]

    pipeline._apply_continuity_guard(tracks, frame)

    assert [track.track_id for track in tracks] == [13, 11]
    assert len({track.track_id for track in tracks}) == len(tracks)
