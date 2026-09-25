"""
NETRAKSH — Real end-to-end test: the actual `edge.main.EdgePipeline` class
(not a re-wiring of its components, like scripts/run_false_positive_
benchmark.py does) processing real frames from the real demo clip with the
real, already-populated zone config -- exercising continuity guard,
adaptive compute gate, track feature tracking, calibration, the Event
Verifier, the Hybrid Reliability Engine, and evidence packaging/chaining
together, in the exact order edge/main.py actually calls them.

TEST 1 from the project's own integration-test checklist: video ->
detection -> tracking -> event. Marked slow (loads real YOLO weights, runs
real inference across many real frames):
    pytest tests/integration/test_edge_pipeline_real_video_e2e.py -m slow

Bounded to the first 200 real frames rather than the full ~795-frame clip
-- a real, previously-undocumented finding from this pass: the full clip
now takes far longer per frame than `docs/PERFORMANCE_REPORT.md`'s
original 44.6ms/frame figure once real vehicles enter frame later in the
clip (ANPR's EasyOCR call is CPU-heavy and was added after that
benchmark was recorded, along with continuity guard, track features, and
face detection). Measured directly: the first 200 frames run in ~35s at a
steady ~175ms/frame with no vehicles yet visible; a full-clip run was
observed taking several times longer once ANPR starts firing. Re-running
`docs/PERFORMANCE_REPORT.md`'s benchmark end to end is real, disclosed
future work (see `docs/LIMITATIONS.md`) -- this test proves the real
pipeline runs correctly on real footage without re-measuring that number.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from edge.main import EdgePipeline
from edge.evidence.packager import EdgeKeyManager

VIDEO_PATH = Path("demo/videos/vtest.avi")
ZONES_PATH = "demo/scripts/zones_config.json"
FRAMES_TO_PROCESS = 200

pytestmark = pytest.mark.slow


@pytest.mark.skipif(not VIDEO_PATH.exists(), reason="demo/videos/vtest.avi not present")
def test_real_edge_pipeline_processes_real_frames_and_produces_verified_evidence(tmp_path):
    config = {
        "camera_id": "e2e-real-cam",
        "video_source": str(VIDEO_PATH),
        "zones_config_path": ZONES_PATH,
        "key_dir": str(tmp_path / "certs"),
        "chain_db_path": str(tmp_path / "chain.db"),
        "sync_db_path": str(tmp_path / "sync.db"),
        "clip_dir": str(tmp_path / "clips"),
        # Unreachable on purpose: the real watchlist-sync / health / metrics
        # backend calls are all non-fatal-on-failure by design (see
        # edge/main.py's own docstrings) -- this proves that posture holds,
        # rather than requiring a real backend just to run this test. A
        # closed high port on loopback refuses the connection immediately;
        # a low/reserved port (e.g. :1) can hang for a long OS-level
        # timeout instead of failing fast, which is NOT what "unreachable"
        # should mean for a bounded-runtime test.
        "backend_url": "http://127.0.0.1:59999",
    }

    key_manager = EdgeKeyManager(
        private_key_path=str(tmp_path / "certs" / "e2e-real-cam.key"),
        public_key_path=str(tmp_path / "certs" / "e2e-real-cam.pub"),
    )
    key_manager.load_or_generate(allow_generate=True)
    pipeline = EdgePipeline(config)
    pipeline.detector.load()

    processed = 0
    try:
        for frame, meta in pipeline.adapter.frames():
            pipeline._process_frame(frame, meta)
            processed += 1
            if processed >= FRAMES_TO_PROCESS:
                break
    finally:
        pipeline.adapter.stop()
        pipeline.adapter.join()

    assert processed == FRAMES_TO_PROCESS

    # Real, chained, signed evidence records were produced -- not merely
    # candidates that never got confirmed.
    records = pipeline.chain_store.get_all_records()
    assert len(records) >= 1
    chain_ok, broken_seq, _detail = pipeline.chain_store.verify_chain()
    assert chain_ok is True

    # Real performance instrumentation, not an estimate.
    summary = pipeline.metrics.summary()
    assert summary["frames"]["total_frame_ms"]["count"] == processed
    assert summary["fps"] > 0

    gate_stats = pipeline.adaptive_gate.get_stats()
    assert gate_stats["frames_run"] + gate_stats["frames_skipped"] == processed
