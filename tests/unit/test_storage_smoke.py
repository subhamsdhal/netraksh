from types import SimpleNamespace

from backend.services.storage_smoke import _PAYLOAD, run_startup_storage_smoke_test


class FakeStorage:
    def __init__(self):
        self.objects = {}

    def put_object(self, key, data, content_type):
        self.objects[key] = data

    def head_object(self, key):
        return {"ContentLength": len(self.objects[key])}

    def get_object(self, key):
        return self.objects[key]

    def generate_signed_url(self, key, expires_in):
        return "https://example.invalid/signed"

    def delete_object(self, key):
        self.objects.pop(key, None)

    def object_exists(self, key):
        return key in self.objects


def test_s3_storage_smoke_uploads_downloads_and_cleans_up(monkeypatch):
    monkeypatch.setattr("backend.services.storage_smoke.settings.OBJECT_STORAGE_PROVIDER", "s3")
    storage = FakeStorage()

    result = run_startup_storage_smoke_test(
        storage=storage,
        fetch=lambda _: SimpleNamespace(status_code=200, content=_PAYLOAD, raise_for_status=lambda: None),
    )

    assert result is True
    assert storage.objects == {}


def test_storage_smoke_skips_non_s3_provider(monkeypatch):
    monkeypatch.setattr("backend.services.storage_smoke.settings.OBJECT_STORAGE_PROVIDER", "local")

    assert run_startup_storage_smoke_test(storage=FakeStorage()) is False
