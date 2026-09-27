import asyncio
from unittest.mock import AsyncMock

from backend.api import system
from shared.schemas import LiveTelemetryPayload


class _Query:
    def filter(self, *args):
        return self

    def order_by(self, *args):
        return self

    def first(self):
        return None


class _Db:
    def query(self, *args):
        return _Query()

    def add(self, value):
        self.added = value

    def commit(self):
        self.committed = True


def _payload(sequence=1, generation=4, analysis_session_id="analysis-current"):
    return LiveTelemetryPayload(
        camera_id="cam-border-01",
        timestamp=1000.0 + sequence,
        processed_timestamp=1000.0 + sequence,
        sequence=sequence,
        stream_id="durable-source-session",
        analysis_session_id=analysis_session_id,
        analysis_generation=generation,
        tracks=[],
    )


def test_only_first_current_generation_telemetry_can_promote_waking_session(monkeypatch):
    system._latest_telemetry.clear()
    promoted = []
    monkeypatch.setattr(system, "broadcast_telemetry", AsyncMock())
    monkeypatch.setattr(
        system,
        "promote_active_session",
        lambda camera_id, session_id, generation, analysis_session_id: promoted.append(
            (camera_id, session_id, generation, analysis_session_id)
        ),
    )

    assert asyncio.run(system.post_telemetry(_payload(), _Db(), None)) == {"status": "ok"}
    assert promoted == [("cam-border-01", "durable-source-session", 4, "analysis-current")]

    # A stale packet is rejected before it can alter the durable lifecycle.
    assert asyncio.run(system.post_telemetry(_payload(sequence=1, generation=3, analysis_session_id="old"), _Db(), None)) == {
        "status": "ignored", "reason": "out_of_order"
    }
    assert len(promoted) == 1


def test_telemetry_snapshot_persists_the_real_run_identity(monkeypatch):
    system._latest_telemetry.clear()
    db = _Db()
    monkeypatch.setattr(system, "broadcast_telemetry", AsyncMock())
    monkeypatch.setattr(system, "promote_active_session", lambda *args: None)

    assert asyncio.run(system.post_telemetry(_payload(analysis_session_id="real-run"), db, None)) == {"status": "ok"}
    assert db.added.stream_id == "durable-source-session"
    assert db.added.analysis_session_id == "real-run"
    assert db.added.analysis_session_id != db.added.stream_id


def test_legacy_snapshot_never_substitutes_stream_as_run_identity(monkeypatch):
    legacy = type("Snapshot", (), {
        "camera_id": "cam-border-01", "stream_id": "durable-stream",
        "analysis_session_id": None, "timestamp": 42.0, "sequence": 5,
        "video_time": None, "frame_width": None, "frame_height": None,
        "analysis_state": "COMPLETED", "analysis_generation": None,
        "frame_index": None, "tracks_json": [],
    })()

    class _PersistedQuery(_Query):
        def first(self):
            return legacy

        def all(self):
            return [legacy]

    class _PersistedDb(_Db):
        def query(self, *args):
            return _PersistedQuery()

    system._latest_telemetry.clear()
    # A legacy persisted snapshot restores null rather than inventing the
    # durable source identity as a run identity.
    system._latest_telemetry.clear()
    restored = asyncio.run(system.latest_telemetry("cam-border-01", "durable-stream", _PersistedDb(), None))
    assert restored[0]["analysis_session_id"] is None
    assert restored[0]["stream_id"] == "durable-stream"
