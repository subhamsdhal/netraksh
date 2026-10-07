import time

import cv2
import numpy as np

from edge.ingestion.camera_adapter import CameraAdapter


def test_one_shot_finite_queue_backpressures_instead_of_losing_first_frame(tmp_path):
    path = tmp_path / "short.avi"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24.0, (32, 32)
    )
    assert writer.isOpened()
    for index in range(5):
        writer.write(np.full((32, 32, 3), index * 20, dtype=np.uint8))
    writer.release()

    adapter = CameraAdapter(
        source=str(path), max_queue_depth=1, preserve_finite_frames=True
    )
    try:
        adapter.start()
        deadline = time.monotonic() + 3.0
        while adapter.frames_received < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert adapter.frames_received >= 2

        _, first = adapter.get_frame(timeout=1.0)
        assert first is not None
        assert first.frame_index == 1
        assert adapter.frames_dropped == 0
    finally:
        adapter.stop()
        adapter.join()


def test_finite_queue_backpressure_does_not_reopen_or_rewind_source(tmp_path):
    path = tmp_path / "backpressured.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 24.0, (32, 32))
    assert writer.isOpened()
    for index in range(5):
        writer.write(np.full((32, 32, 3), index * 20, dtype=np.uint8))
    writer.release()

    adapter = CameraAdapter(
        source=str(path), max_queue_depth=1, preserve_finite_frames=True,
        frame_stall_timeout_seconds=0.05,
    )
    frames = []
    try:
        adapter.start()
        deadline = time.monotonic() + 3.0
        while adapter.frames_received < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert adapter.frames_received >= 2
        # This exceeds the stall timeout while the producer waits on a full
        # queue. It must not make a one-shot source reconnect from frame 1.
        time.sleep(0.2)
        deadline = time.monotonic() + 3.0
        while len(frames) < 5 and time.monotonic() < deadline:
            _, meta = adapter.get_frame(timeout=0.1)
            if meta is not None:
                frames.append(meta)
        assert [meta.frame_index for meta in frames] == [1, 2, 3, 4, 5]
        assert [meta.video_time_seconds for meta in frames] == sorted(
            meta.video_time_seconds for meta in frames
        )
        assert adapter.frames_dropped == 0
        deadline = time.monotonic() + 2.0
        while not adapter.eof_reached and time.monotonic() < deadline:
            time.sleep(0.01)
        assert adapter.eof_reached
    finally:
        adapter.stop()
        adapter.join()
