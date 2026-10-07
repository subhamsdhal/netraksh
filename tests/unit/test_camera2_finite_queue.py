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
