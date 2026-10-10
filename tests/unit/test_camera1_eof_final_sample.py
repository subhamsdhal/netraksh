"""Camera 1 stored-video EOF must durably persist its real terminal sample."""
from types import SimpleNamespace

import httpx

from edge.main import EdgePipeline


FINAL_SAMPLE = {
    "camera_id": "cam-border-01",
    "stream_id": "source-1",
    "analysis_session_id": "run-1",
    "analysis_generation": 3,
    "sequence": 701,
    "frame_index": 2385,
    "video_time": 79.4666667,
    "tracks": [],
}


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def _final_persistence_pipeline():
    pipeline = object.__new__(EdgePipeline)
    pipeline._final_authoritative_sample = dict(FINAL_SAMPLE)
    pipeline._backend_url = "https://backend.test"
    pipeline.sync_client = SimpleNamespace(_ca_cert=None, _client_cert=None)
    pipeline._tracking_metrics = {"produced": 0, "transmitted": 0, "dropped": 0, "errors": 0}
    pipeline._last_tracking_persist_log_at = 0.0
    pipeline.stream_id = "run-1"
    pipeline.analysis_generation = 3
    pipeline.camera_id = "cam-border-01"
    pipeline.timeline_incomplete = False
    pipeline._edge_auth_headers = lambda: {}
    return pipeline


def test_camera1_final_sample_retries_transient_502_and_waits_for_ack(monkeypatch):
    requests = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, **kwargs):
            requests.append(kwargs["json"].copy())
            return _Response(502 if len(requests) == 1 else 202)

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr("edge.main.time.sleep", lambda *_args: None)
    pipeline = _final_persistence_pipeline()

    assert pipeline._persist_final_authoritative_sample() is True
    assert requests == [FINAL_SAMPLE, FINAL_SAMPLE]
    assert pipeline._tracking_metrics["transmitted"] == 1
    assert pipeline.timeline_incomplete is False


def test_camera1_final_sample_timeout_is_bounded_and_not_acknowledged(monkeypatch):
    requests = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, **kwargs):
            requests.append(kwargs["json"].copy())
            return _Response(502)

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr("edge.main.time.sleep", lambda *_args: None)
    pipeline = _final_persistence_pipeline()

    assert pipeline._persist_final_authoritative_sample() is False
    assert len(requests) == 5
    assert pipeline._tracking_metrics["dropped"] == 1
    assert pipeline.timeline_incomplete is True


def test_optional_telemetry_failure_does_not_block_final_sample(monkeypatch):
    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, **_kwargs):
            return _Response(202)

    monkeypatch.setattr(httpx, "Client", Client)
    pipeline = _final_persistence_pipeline()
    pipeline._telemetry_metrics = {"produced": 2, "dropped": 1, "errors": 1}

    assert pipeline._persist_final_authoritative_sample() is True
    assert pipeline._telemetry_metrics["errors"] == 1
    assert pipeline.timeline_incomplete is False


def test_camera1_2385_frame_eof_flush_uses_actual_final_image(monkeypatch):
    frame = SimpleNamespace(copy=lambda: frame)
    meta = SimpleNamespace(
        frame_index=2385,
        video_time_seconds=79.4666667,
        timestamp=79.4666667,
        fps_declared=30.0,
        width=640,
        height=360,
    )
    packet_holder = {"packet": None}

    class Worker:
        busy = False

        def poll_latest(self):
            packet, packet_holder["packet"] = packet_holder["packet"], None
            return packet

        def submit(self, job):
            packet_holder["packet"] = SimpleNamespace(
                error=None, job=job, tracks=[], detector_ms=2.0,
            )
            return True

    pipeline = object.__new__(EdgePipeline)
    pipeline.camera_id = "cam-border-01"
    pipeline.adapter = SimpleNamespace(source_kind="LOCAL_FINITE_FILE", preserve_finite_frames=True)
    pipeline._last_finite_detector_frame = (frame, meta, object(), SimpleNamespace(condition="CLEAR_DAY"))
    pipeline._last_detector_frame_index = 2376
    pipeline._final_authoritative_sample = None
    pipeline.detector_worker = Worker()
    pipeline.condition_router = SimpleNamespace(route=lambda condition: condition)
    pipeline._detector_confidence_threshold = lambda _condition: 0.4
    pipeline._detector_new_track_threshold = lambda _condition: None
    pipeline._prime_stored_lost_tracks = lambda _tracks: None
    pipeline._apply_continuity_guard = lambda tracks, _frame: tracks
    emitted = {}

    def emit(packet, tracks, *, enqueue=True):
        emitted.update(frame_index=packet.job.frame_index, video_time=packet.job.meta.video_time_seconds)
        emitted["enqueue"] = enqueue
        pipeline._final_authoritative_sample = {
            "frame_index": packet.job.frame_index,
            "video_time": packet.job.meta.video_time_seconds,
        }
        return pipeline._final_authoritative_sample

    pipeline._emit_detector_sample = emit
    monkeypatch.setattr("edge.main.enhance_for_detection", lambda image, _policy: image)

    assert pipeline._flush_camera1_final_sample_at_eof() is True
    assert emitted == {"frame_index": 2385, "video_time": 79.4666667, "enqueue": False}
    assert pipeline._last_detector_frame_index == 2385
