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
