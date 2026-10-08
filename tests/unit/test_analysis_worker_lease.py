"""Exact-run lease reconciliation and bounded edge transport regression tests."""
import asyncio
from types import SimpleNamespace
from queue import Queue

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.models.orm import AnalysisRunSummary, AnalysisWorkerLease, Base
from backend.api import dashboard
from backend.services import analysis_worker_lease as lease_service
from backend.services import video_storage
from edge.main import EdgePipeline
from edge.demo_runner import _persist_durable_eof


SOURCE = "11111111-1111-4111-8111-111111111111"
RUN = "22222222-2222-4222-8222-222222222222"
BOOT = "33333333-3333-4333-8333-333333333333"


def _control():
    return {
        "camera_id": "cam-border-01", "session_id": SOURCE,
        "analysis_generation": 8, "latest_analysis_session_id": RUN,
        "analysis_state": "ACTIVE", "scenario": "normal",
    }


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _summary(db):
    summary = AnalysisRunSummary(
        analysis_session_id=RUN, camera_id="cam-border-01", stream_id=SOURCE,
        analysis_generation=8, first_telemetry_at=900, last_telemetry_at=1000,
        final_frame_index=1725, final_video_time=57.47,
    )
    db.add(summary)
    db.commit()
    return summary


def _heartbeat(db, *, boot=BOOT, phase="RUNNING", started=900, now=1000):
    return lease_service.record_heartbeat(db, {
        "camera_id": "cam-border-01", "boot_id": boot,
        "instance_id": "edge-instance-1", "worker_started_at": started,
        "phase": phase,
        "stream_id": SOURCE if phase != "IDLE" else None,
        "analysis_session_id": RUN if phase != "IDLE" else None,
        "analysis_generation": 8 if phase != "IDLE" else None,
        "last_frame_index": 1725 if phase != "IDLE" else None,
        "last_video_time": 57.47 if phase != "IDLE" else None,
    }, now=now)


def test_fresh_matching_lease_keeps_live_run():
    db = _db()
    summary = _summary(db)
    lease = _heartbeat(db)
    assert lease_service.interruption_reason(_control(), lease, summary, now=1010) is None


def test_missing_worker_lease_interrupts_only_after_long_grace():
    db = _db()
    summary = _summary(db)
    assert lease_service.interruption_reason(_control(), None, summary, now=1100) is None
    assert lease_service.interruption_reason(_control(), None, summary, now=1301) == "worker_lease_missing"


def test_expired_lease_interrupts_exact_run_and_preserves_history(monkeypatch):
    db = _db()
    _summary(db)
    _heartbeat(db)
    mutations = []
    monkeypatch.setattr(lease_service, "interrupt_active_session", lambda *args, **kw: mutations.append((args, kw)) or {**_control(), "analysis_state": "INTERRUPTED", "scenario": "paused"})
    monkeypatch.setattr(lease_service, "audit", lambda *args, **kw: None)
    settled = lease_service.reconcile_stale_run(db, "cam-border-01", _control(), now=1200)
    assert settled["analysis_state"] == "INTERRUPTED"
    assert mutations[0][0] == ("cam-border-01", SOURCE, 8)
    summary = db.get(AnalysisRunSummary, RUN)
    assert summary.interruption_reason == "worker_lease_expired"
    assert summary.completed_at is None
    assert (summary.final_frame_index, summary.final_video_time) == (1725, 57.47)


def test_replacement_idle_instance_interrupts_old_run_without_touching_camera_2(monkeypatch):
    db = _db()
    _summary(db)
    _heartbeat(db)
    _heartbeat(db, boot="44444444-4444-4444-8444-444444444444", phase="IDLE", started=1050, now=1051)
    assert lease_service.interruption_reason(_control(), db.get(AnalysisWorkerLease, "cam-border-01"), db.get(AnalysisRunSummary, RUN), now=1052) == "edge_instance_terminated"
    assert db.get(AnalysisWorkerLease, "cam-checkpoint-01") is None


def test_idle_same_boot_after_failed_pipeline_interrupts_without_claiming_eof():
    db = _db()
    summary = _summary(db)
    _heartbeat(db)
    _heartbeat(db, phase="IDLE", started=900, now=1051)
    assert summary.worker_boot_id == BOOT
    assert lease_service.interruption_reason(
        _control(), db.get(AnalysisWorkerLease, "cam-border-01"), summary, now=1052,
    ) == "worker_exited_during_analysis"


def test_failed_eof_delivery_is_interrupted_with_truthful_reason():
    db = _db()
    summary = _summary(db)
    lease = _heartbeat(db, phase="FAILED_EOF", now=1051)
    assert lease_service.interruption_reason(_control(), lease, summary, now=1052) == "completion_not_persisted"


def test_new_worker_cannot_reclaim_with_older_boot_time():
    db = _db()
    _heartbeat(db, boot=BOOT, phase="IDLE", started=1050, now=1051)
    _heartbeat(db, boot="44444444-4444-4444-8444-444444444444", started=900, now=1052)
    assert db.get(AnalysisWorkerLease, "cam-border-01").boot_id == BOOT


def test_protected_heartbeat_cannot_claim_another_camera():
    from fastapi import HTTPException
    db = _db()
    payload = {
        "camera_id": "cam-border-01", "boot_id": BOOT,
        "worker_started_at": 900, "phase": "IDLE",
    }
    try:
        asyncio.run(dashboard.post_internal_worker_heartbeat(
            payload, SimpleNamespace(edge_id="cam-checkpoint-01"), db,
        ))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("cross-camera heartbeat was accepted")
    assert db.get(AnalysisWorkerLease, "cam-border-01") is None


def test_completed_run_is_never_interrupted():
    db = _db()
    summary = _summary(db)
    summary.completed_at = 1010
    db.commit()
    lease = _heartbeat(db, phase="IDLE", started=1050, now=1051)
    assert lease_service.interruption_reason(_control(), lease, summary, now=1200) is None


def test_late_eof_cannot_overwrite_historically_interrupted_run(monkeypatch):
    current = {**_control(), "analysis_state": "INTERRUPTED", "scenario": "paused"}
    monkeypatch.setattr(video_storage, "get_valid_active_session", lambda _camera_id: current)
    assert video_storage.complete_active_session(
        "cam-border-01", SOURCE, 8, {"latest_analysis_session_id": RUN},
    ) is None


def test_real_persisted_eof_can_recover_lost_control_acknowledgement(monkeypatch):
    db = _db()
    summary = _summary(db)
    summary.completed_at = 1010
    summary.tracking_sample_count = 100
    db.commit()
    completed = []
    monkeypatch.setattr(lease_service, "complete_active_session", lambda *args, **kw: completed.append((args, kw)) or {**_control(), "analysis_state": "COMPLETED"})
    monkeypatch.setattr(lease_service, "audit", lambda *args, **kw: None)
    settled = lease_service.reconcile_stale_run(db, "cam-border-01", _control(), now=1021)
    assert settled["analysis_state"] == "COMPLETED"
    assert completed[0][0][:3] == ("cam-border-01", SOURCE, 8)
    assert completed[0][0][3]["latest_analysis_session_id"] == RUN


def test_eof_recovery_requires_real_durable_timeline(monkeypatch):
    db = _db()
    summary = _summary(db)
    summary.completed_at = 1010
    summary.tracking_sample_count = 0
    db.commit()
    monkeypatch.setattr(lease_service, "complete_active_session", lambda *_args, **_kw: (_ for _ in ()).throw(AssertionError("no timeline")))
    assert lease_service.reconcile_stale_run(db, "cam-border-01", _control(), now=1021) == _control()


def test_completion_rejects_an_old_run_id_for_same_generation(monkeypatch):
    current = {**_control(), "analysis_state": "ACTIVE"}
    monkeypatch.setattr(video_storage, "get_valid_active_session", lambda _camera_id: current)
    assert video_storage.complete_active_session(
        "cam-border-01", SOURCE, 8,
        {"latest_analysis_session_id": "another-run"},
    ) is None


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def _transport_pipeline():
    pipeline = EdgePipeline.__new__(EdgePipeline)
    pipeline.camera_id = "cam-border-01"
    pipeline.stream_id = RUN
    pipeline.analysis_generation = 8
    pipeline._last_tracking_persist_log_at = 0.0
    pipeline._tracking_metrics = {"produced": 0, "transmitted": 0, "dropped": 0, "errors": 0}
    pipeline._edge_auth_headers = lambda: {}
    return pipeline


def test_transient_502_retries_same_sample_without_stopping_worker(monkeypatch):
    pipeline = _transport_pipeline()
    calls = []
    client = SimpleNamespace(post=lambda *_args, **_kw: calls.append(1) or _Response(502 if len(calls) == 1 else 202))
    monkeypatch.setattr("edge.main.time.sleep", lambda *_args: None)
    assert pipeline._post_tracking_with_retry(client, "https://backend.test/system/tracking-frame", {"frame_index": 5}) is True
    assert len(calls) == 2
    assert pipeline._tracking_metrics == {"produced": 0, "transmitted": 1, "dropped": 0, "errors": 1}


def test_persistent_502_is_bounded_and_truthfully_counted(monkeypatch):
    pipeline = _transport_pipeline()
    calls = []
    client = SimpleNamespace(post=lambda *_args, **_kw: calls.append(1) or _Response(502))
    monkeypatch.setattr("edge.main.time.sleep", lambda *_args: None)
    assert pipeline._post_tracking_with_retry(client, "https://backend.test/system/tracking-frame", {"frame_index": 5}) is False
    assert len(calls) == 5
    assert pipeline._tracking_metrics == {"produced": 0, "transmitted": 0, "dropped": 1, "errors": 5}


def test_tracking_queue_remains_bounded_and_reports_eviction():
    pipeline = _transport_pipeline()
    pipeline.tracking_queue = Queue(maxsize=2)
    for frame in (1, 2, 3):
        pipeline._queue_tracking_payload({"frame_index": frame})
    assert pipeline.tracking_queue.qsize() == 2
    assert [pipeline.tracking_queue.get_nowait()["frame_index"] for _ in range(2)] == [2, 3]
    assert pipeline._tracking_metrics["dropped"] == 1


def test_eof_callback_retries_exact_generation_after_502(monkeypatch):
    import httpx

    requests = []

    class Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, _url, **kwargs):
            requests.append(kwargs["json"].copy())
            return _Response(502 if len(requests) == 1 else 200)

    monkeypatch.setattr(httpx, "Client", Client)
    monkeypatch.setattr("edge.demo_runner.time.sleep", lambda *_args: None)
    payload = {
        "camera_id": "cam-border-01", "video_session_id": SOURCE,
        "analysis_session_id": RUN, "analysis_generation": 8,
        "final_frame_index": 1725, "final_video_time": 57.47,
    }
    assert _persist_durable_eof("https://backend.test", "test-token", payload) is True
    assert requests == [payload, payload]
