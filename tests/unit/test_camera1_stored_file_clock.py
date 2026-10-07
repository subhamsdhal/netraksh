from edge.main import preserve_stored_file_frames


def test_both_stored_camera_files_backpressure_decoder():
    assert preserve_stored_file_frames("cam-border-01", "restored-stream")
    assert preserve_stored_file_frames("cam-checkpoint-01", "restored-stream")


def test_live_and_unknown_sources_keep_previous_queue_policy():
    assert not preserve_stored_file_frames("cam-border-01", None)
    assert not preserve_stored_file_frames("cam-checkpoint-01", None)
    assert not preserve_stored_file_frames("other-camera", "restored-stream")
