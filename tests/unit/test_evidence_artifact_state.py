from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.api.events import derive_artifact_state, get_evidence_image
from backend.models.orm import EvidencePackage, Event


def _event(**overrides):
    values = {
        "id": "event-1",
        "camera_id": "cam-border-01",
        "camera": SimpleNamespace(owning_command_id="COMMAND_A"),
        "evidence_clip_ref": None,
        "object_key": None,
        "content_hash": None,
        "storage_status": "CREATED",
        "storage_provider": "local",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _package():
    return SimpleNamespace(event_id="event-1")


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self.value


class _Session:
    def __init__(self, event, package):
        self.event = event
        self.package = package

    def query(self, model):
        if model is Event:
            return _Query(self.event)
        if model is EvidencePackage:
            return _Query(self.package)
        raise AssertionError(f"Unexpected query model: {model}")


def test_artifact_state_distinguishes_metadata_pending_and_available():
    assert derive_artifact_state(_event(), _package()) == "METADATA_ONLY"
    assert derive_artifact_state(
        _event(evidence_clip_ref="pending.jpg.enc"), _package()
    ) == "SYNCING"
    assert derive_artifact_state(
        _event(storage_status="UPLOADING"), _package()
    ) == "SYNCING"
    assert derive_artifact_state(
        _event(
            storage_status="AVAILABLE",
            storage_provider="s3",
            object_key="evidence/cam-border-01/event-1.jpg.enc",
            content_hash="a" * 64,
        ),
        _package(),
    ) == "AVAILABLE"


@pytest.mark.asyncio
async def test_metadata_only_image_is_terminal_and_not_retryable():
    event = _event()
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    user = SimpleNamespace(id="user-1")

    with patch("backend.api.events.enforce_command_access"):
        with pytest.raises(HTTPException) as exc_info:
            await get_evidence_image(request, event.id, _Session(event, _package()), user)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == {
        "code": "METADATA_ONLY",
        "message": "NO_BINARY_ARTIFACT",
    }


@pytest.mark.asyncio
async def test_pending_binary_keeps_425_retry_semantics():
    event = _event(evidence_clip_ref="pending.jpg.enc")
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    user = SimpleNamespace(id="user-1")

    with patch("backend.api.events.enforce_command_access"):
        with pytest.raises(HTTPException) as exc_info:
            await get_evidence_image(request, event.id, _Session(event, _package()), user)

    assert exc_info.value.status_code == 425


@pytest.mark.asyncio
async def test_available_binary_retrieval_is_unchanged():
    event = _event(
        storage_status="AVAILABLE",
        object_key="evidence/event-1.jpg",
        content_hash="b" * 64,
    )
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    user = SimpleNamespace(id="user-1")
    storage = MagicMock()
    storage.get_object.return_value = b"jpeg-bytes"

    with patch("backend.api.events.enforce_command_access"), \
         patch("backend.api.events.get_evidence_storage", return_value=storage), \
         patch("backend.api.events.audit"):
        response = await get_evidence_image(
            request, event.id, _Session(event, _package()), user
        )

    assert response.status_code == 200
    assert response.body == b"jpeg-bytes"
    assert response.media_type == "image/jpeg"
    storage.get_object.assert_called_once_with(event.object_key)
