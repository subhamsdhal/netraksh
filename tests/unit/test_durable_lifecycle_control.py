from edge.demo_runner import _apply_live_control, _durable_pipeline_allowed


class _Adapter:
    paused = True


class _SyncClient:
    def __init__(self):
        self.offline = None

    def set_simulate_offline(self, value):
        self.offline = value


def test_waking_paused_durable_control_never_starts_pipeline():
    assert not _durable_pipeline_allowed("source-session", "WAKING", "paused")
    assert not _durable_pipeline_allowed("source-session", "ACTIVE", "paused")


def test_waking_normal_durable_control_allows_pipeline_and_unpauses_adapter():
    adapter = _Adapter()
    sync = _SyncClient()

    assert _durable_pipeline_allowed("source-session", "WAKING", "normal")
    _apply_live_control(adapter, sync, "normal")

    assert adapter.paused is False
    assert sync.offline is False


def test_stop_control_pauses_live_adapter():
    adapter = _Adapter()
    adapter.paused = False
    sync = _SyncClient()

    _apply_live_control(adapter, sync, "paused")

    assert adapter.paused is True
    assert sync.offline is False
