"""A completed Camera 2 replay must include a real final-frame detector anchor."""

from types import SimpleNamespace

import numpy as np

from edge.main import EdgePipeline


class _Worker:
    busy = False

    def __init__(self, pending=None):
        self.pending = pending
        self.submitted = []

    def poll_latest(self):
        packet, self.pending = self.pending, None
        return packet

    def submit(self, job):
        self.submitted.append(job)
        self.pending = SimpleNamespace(job=job, tracks=[], error=None)
        return True


def _packet(index):
    return SimpleNamespace(
        job=SimpleNamespace(frame_index=index, frame=np.zeros((2, 2, 3), dtype=np.uint8)),
        tracks=[], error=None,
    )


def test_camera2_eof_emits_real_pending_and_final_frames(monkeypatch):
    import edge.main as main

    monkeypatch.setattr(main, "enhance_for_detection", lambda frame, policy: frame)
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.camera_id = "cam-checkpoint-01"
    pipeline._last_detector_frame_index = 219
    frame = np.zeros((2, 2, 3), dtype=np.uint8)
    meta = SimpleNamespace(frame_index=240)
    condition = SimpleNamespace(condition="CLEAR_DAY")
    pipeline._last_finite_detector_frame = (frame, meta, object(), condition)
    pipeline.detector_worker = _Worker(_packet(220))
    pipeline.condition_router = SimpleNamespace(route=lambda _: object())
    pipeline.calibration = SimpleNamespace(get_threshold=lambda _: 0.45)
    pipeline._apply_continuity_guard = lambda tracks, image: tracks
    emitted = []
    pipeline._emit_detector_sample = lambda packet, tracks: emitted.append(packet.job.frame_index)

    pipeline._flush_finite_detector_at_eof()

    assert emitted == [220, 240]
    assert pipeline.detector_worker.submitted[0].frame is not frame
    assert pipeline.detector_worker.submitted[0].frame_index == 240
    assert pipeline._last_detector_frame_index == 240


def test_camera1_eof_does_not_submit_detector_job():
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.camera_id = "cam-border-01"
    pipeline._last_finite_detector_frame = (object(), object(), object(), object())
    pipeline.detector_worker = _Worker()

    pipeline._flush_finite_detector_at_eof()

    assert pipeline.detector_worker.submitted == []
