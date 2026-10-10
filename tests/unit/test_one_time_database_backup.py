from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import one_time_database_backup as backup
from backend.config import settings
from shared.crypto import NONCE_SIZE


def _decrypt_envelope(envelope: bytes, private_key) -> bytes:
    magic = backup._ARCHIVE_MAGIC
    assert envelope.startswith(magic)
    key_size_start = len(magic)
    key_size = int.from_bytes(envelope[key_size_start:key_size_start + 2], "big")
    wrapped_start = key_size_start + 2
    wrapped = envelope[wrapped_start:wrapped_start + key_size]
    encrypted = envelope[wrapped_start + key_size:]
    data_key = private_key.decrypt(
        wrapped,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=backup._OAEP_LABEL,
        ),
    )
    return AESGCM(data_key).decrypt(
        encrypted[:NONCE_SIZE], encrypted[NONCE_SIZE:], None
    )


def test_envelope_is_authenticated_and_decrypts_only_for_recipient():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    raw_dump = b"pg_dump bytes that must never leave the server in plaintext"

    envelope = backup._encrypt_archive(raw_dump, public_key)

    assert raw_dump not in envelope
    assert _decrypt_envelope(envelope, private_key) == raw_dump
    tampered = bytearray(envelope)
    tampered[-1] ^= 1
    with pytest.raises(Exception):
        _decrypt_envelope(bytes(tampered), private_key)


def test_export_is_disabled_by_default():
    old = (
        settings.DB_BACKUP_EXPORT_ENABLED,
        settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY,
        settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH,
    )
    backup._EXPORT_CONSUMED = False
    settings.DB_BACKUP_EXPORT_ENABLED = False
    settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY = None
    settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH = 0
    try:
        with pytest.raises(HTTPException) as error:
            backup.export_database_backup(_admin=object())
        assert error.value.status_code == 404
    finally:
        settings.DB_BACKUP_EXPORT_ENABLED, settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY, settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH = old


def test_http_export_requires_authenticated_admin():
    app = FastAPI()
    app.include_router(backup.router)
    assert "/api/admin/database-backup" not in app.openapi()["paths"]
    response = TestClient(app).get("/api/admin/database-backup")
    assert response.status_code == 401


def test_pg_dump_receives_credentials_only_in_child_environment(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        settings,
        "DATABASE_URL",
        "postgresql://backup_user:unit-test-secret@db.example.invalid:5432/netraksh_stage?sslmode=require",
    )

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout=b"custom archive")

    monkeypatch.setattr(backup.subprocess, "run", fake_run)
    assert backup._dump_database() == b"custom archive"
    assert captured["args"] == ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--compress=6"]
    child_env = captured["kwargs"]["env"]
    assert child_env["PGPASSWORD"] == "unit-test-secret"
    assert "DATABASE_URL" not in child_env
    assert "unit-test-secret" not in " ".join(captured["args"])
    assert captured["kwargs"]["stderr"] == backup.subprocess.DEVNULL


def test_export_is_single_use_and_returns_encrypted_response(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    old = (
        settings.DB_BACKUP_EXPORT_ENABLED,
        settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY,
        settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH,
    )
    backup._EXPORT_CONSUMED = False
    settings.DB_BACKUP_EXPORT_ENABLED = True
    settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY = public_key
    settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH = int(time.time()) + 600
    monkeypatch.setattr(backup, "_dump_database", lambda: b"verified test dump")
    try:
        response = backup.export_database_backup(_admin=object())
        assert response.media_type == "application/octet-stream"
        assert response.headers["cache-control"] == "no-store, private"
        assert response.headers["content-disposition"].endswith('"netraksh-stage-encrypted.backup"')
        assert b"verified test dump" not in response.body
        assert _decrypt_envelope(response.body, private_key) == b"verified test dump"
        with pytest.raises(HTTPException) as error:
            backup.export_database_backup(_admin=object())
        assert error.value.status_code == 410
    finally:
        backup._EXPORT_CONSUMED = False
        settings.DB_BACKUP_EXPORT_ENABLED, settings.DB_BACKUP_RECIPIENT_PUBLIC_KEY, settings.DB_BACKUP_EXPORT_DEADLINE_EPOCH = old
