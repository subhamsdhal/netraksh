from edge.evidence.packager import EvidencePackager


class _KeyManager:
    private_key_path = "key"


class _ChainStore:
    pass


def test_evidence_packager_keeps_source_and_analysis_identities_separate(tmp_path):
    packager = EvidencePackager(
        camera_id="cam-border-01",
        stream_id="durable-source-session",
        analysis_session_id="analysis-run-1",
        key_manager=_KeyManager(),
        chain_store=_ChainStore(),
        clip_storage_dir=str(tmp_path),
    )

    assert packager.stream_id == "durable-source-session"
    assert packager.analysis_session_id == "analysis-run-1"


def test_replay_run_identity_is_not_used_as_durable_source_identity(tmp_path):
    first = EvidencePackager(
        camera_id="cam-border-01",
        stream_id="durable-source-session",
        analysis_session_id="analysis-run-1",
        key_manager=_KeyManager(),
        chain_store=_ChainStore(),
        clip_storage_dir=str(tmp_path / "first"),
    )
    second = EvidencePackager(
        camera_id="cam-border-01",
        stream_id="durable-source-session",
        analysis_session_id="analysis-run-2",
        key_manager=_KeyManager(),
        chain_store=_ChainStore(),
        clip_storage_dir=str(tmp_path / "second"),
    )

    assert first.stream_id == second.stream_id
    assert first.analysis_session_id != second.analysis_session_id
