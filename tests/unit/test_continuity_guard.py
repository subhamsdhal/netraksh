"""
NETRAKSH — Unit tests for edge/tracking/continuity_guard.py
(Track Continuity Guard — architecture v4 §4, v3/v4 Risk #2 mitigation).
"""
import numpy as np
import pytest

from edge.tracking.continuity_guard import TrackContinuityGuard, compute_histogram
from shared.schemas import BoundingBox, Point


def _hist(seed: float, shape=(30, 32)) -> np.ndarray:
    """A deterministic, valid float32 'histogram'-shaped array for testing
    match/no-match logic without needing real image data. Two calls with the
    same seed are identical (perfect match); different seeds are very
    different distributions (no match)."""
    rng = np.random.RandomState(int(seed * 1000))
    arr = rng.rand(*shape).astype(np.float32)
    return arr


class TestRememberAndResolve:
    def test_matching_histogram_and_close_centroid_resolves(self):
        guard = TrackContinuityGuard()
        h = _hist(1.0)
        guard.remember_lost(
            track_id=7, histogram=h, centroid=Point(x=100, y=100),
            trajectory=[Point(x=95, y=95), Point(x=100, y=100)], now=0.0,
        )
        match = guard.resolve_new_track(histogram=h, centroid=Point(x=105, y=102), now=1.0)
        assert match is not None
        matched_id, trajectory = match
        assert matched_id == 7
        assert len(trajectory) == 2

    def test_resolved_entry_is_removed_from_pool(self):
        guard = TrackContinuityGuard()
        h = _hist(1.0)
        guard.remember_lost(7, h, Point(x=100, y=100), [], now=0.0)
        guard.resolve_new_track(h, Point(x=100, y=100), now=1.0)
        assert guard.get_pool_size() == 0

    def test_dissimilar_histogram_does_not_resolve(self):
        guard = TrackContinuityGuard()
        guard.remember_lost(7, _hist(1.0), Point(x=100, y=100), [], now=0.0)
        match = guard.resolve_new_track(_hist(99.0), Point(x=100, y=100), now=1.0)
        assert match is None

    def test_far_away_centroid_does_not_resolve_even_with_identical_histogram(self):
        guard = TrackContinuityGuard(max_centroid_distance=50.0)
        h = _hist(1.0)
        guard.remember_lost(7, h, Point(x=0, y=0), [], now=0.0)
        match = guard.resolve_new_track(h, Point(x=1000, y=1000), now=1.0)
        assert match is None

    def test_no_lost_tracks_never_resolves(self):
        guard = TrackContinuityGuard()
        match = guard.resolve_new_track(_hist(1.0), Point(x=0, y=0), now=0.0)
        assert match is None

    def test_none_histogram_is_never_remembered(self):
        guard = TrackContinuityGuard()
        guard.remember_lost(7, None, Point(x=0, y=0), [], now=0.0)
        assert guard.get_pool_size() == 0

    def test_none_histogram_never_resolves(self):
        guard = TrackContinuityGuard()
        guard.remember_lost(7, _hist(1.0), Point(x=0, y=0), [], now=0.0)
        match = guard.resolve_new_track(None, Point(x=0, y=0), now=1.0)
        assert match is None

    def test_picks_best_match_among_multiple_candidates(self):
        guard = TrackContinuityGuard()
        target = _hist(1.0)
        guard.remember_lost(1, _hist(50.0), Point(x=100, y=100), [], now=0.0)  # dissimilar
        guard.remember_lost(2, target, Point(x=102, y=101), [], now=0.0)       # the real match
        match = guard.resolve_new_track(target, Point(x=103, y=100), now=1.0)
        assert match is not None
        assert match[0] == 2


class TestExpiry:
    def test_entry_expires_after_ttl(self):
        guard = TrackContinuityGuard(lost_pool_ttl_seconds=5.0)
        guard.remember_lost(7, _hist(1.0), Point(x=0, y=0), [], now=0.0)
        expired = guard.expire_stale(now=10.0)
        assert expired == [7]
        assert guard.get_pool_size() == 0

    def test_entry_not_expired_within_ttl(self):
        guard = TrackContinuityGuard(lost_pool_ttl_seconds=5.0)
        guard.remember_lost(7, _hist(1.0), Point(x=0, y=0), [], now=0.0)
        expired = guard.expire_stale(now=2.0)
        assert expired == []
        assert guard.get_pool_size() == 1

    def test_expired_entry_cannot_be_resolved(self):
        guard = TrackContinuityGuard(lost_pool_ttl_seconds=5.0)
        h = _hist(1.0)
        guard.remember_lost(7, h, Point(x=0, y=0), [], now=0.0)
        match = guard.resolve_new_track(h, Point(x=0, y=0), now=10.0)  # past TTL
        assert match is None


class TestComputeHistogram:
    def test_valid_crop_returns_histogram(self):
        frame = (np.random.rand(100, 100, 3) * 255).astype(np.uint8)
        bbox = BoundingBox(x1=10, y1=10, x2=50, y2=50)
        hist = compute_histogram(frame, bbox)
        assert hist is not None
        assert hist.shape == (30, 32)

    def test_out_of_bounds_bbox_clips_rather_than_crashes(self):
        frame = (np.random.rand(100, 100, 3) * 255).astype(np.uint8)
        bbox = BoundingBox(x1=-50, y1=-50, x2=200, y2=200)
        hist = compute_histogram(frame, bbox)
        assert hist is not None  # clipped to the frame, still a valid crop

    def test_degenerate_bbox_returns_none(self):
        frame = (np.random.rand(100, 100, 3) * 255).astype(np.uint8)
        bbox = BoundingBox(x1=1000, y1=1000, x2=1010, y2=1010)  # entirely outside frame
        hist = compute_histogram(frame, bbox)
        assert hist is None

    def test_identical_crops_produce_identical_histograms(self):
        frame = (np.random.rand(100, 100, 3) * 255).astype(np.uint8)
        bbox = BoundingBox(x1=10, y1=10, x2=50, y2=50)
        h1 = compute_histogram(frame, bbox)
        h2 = compute_histogram(frame, bbox)
        assert np.allclose(h1, h2)
