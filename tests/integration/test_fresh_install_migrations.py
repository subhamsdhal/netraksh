"""Real migration tests; optional PostgreSQL uses disposable local schemas only.

Set NETRAKSH_TEST_POSTGRES_URL to a loopback database named netraksh_test*.
No production database or source-account credentials belong in this suite.
"""
import importlib.util
import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
REPAIRS = (
    "e4a6b8c0d2f3_admin_account_normalization",
    "f5b7c9d1e3a4_sync_primary_admin_password",
    "a6c8e0f2b4d6_deactivate_stale_bootstrap_users",
)


@pytest.fixture(params=["sqlite", "postgresql"])
def migrated_db(request, tmp_path, monkeypatch):
    cleanup = None
    if request.param == "postgresql":
        raw = os.environ.get("NETRAKSH_TEST_POSTGRES_URL")
        if not raw:
            pytest.skip("local PostgreSQL test URL not configured")
        url = sa.engine.make_url(raw)
        assert url.host in {"127.0.0.1", "localhost"}
        assert url.database.startswith("netraksh_test")
        admin = sa.create_engine(url)
        schema = "migration_test_" + uuid.uuid4().hex
        with admin.begin() as conn:
            conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        cleanup = (admin, schema)
        url = url.update_query_dict({"options": f"-csearch_path={schema}"})
    else:
        url = sa.engine.make_url(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    engine = sa.create_engine(url)
    try:
        yield engine, config
    finally:
        engine.dispose()
        if cleanup:
            admin, schema = cleanup
            with admin.begin() as conn:
                conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


def test_empty_database_full_chain_then_staging_bootstrap_and_login(migrated_db, monkeypatch):
    engine, config = migrated_db
    command.upgrade(config, "head")
    from backend.models.orm import Base, User
    inspector = sa.inspect(engine)
    for table in Base.metadata.sorted_tables:
        assert table.name in inspector.get_table_names()
        actual = {c["name"] for c in inspector.get_columns(table.name)}
        assert set(table.columns.keys()) <= actual, table.name
    with engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT count(*) FROM users")) == 0
        assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()

    from backend.config import settings
    import backend.database.session as database
    import backend.main as main
    from backend.security.auth import bootstrap_users, verify_password
    from fastapi.testclient import TestClient
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessions)
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(settings, "ENV", "staging")
    monkeypatch.setattr(settings, "BOOTSTRAP_USERS", True)
    monkeypatch.setattr(settings, "ADMIN_USERNAME", "staging_admin")
    monkeypatch.setattr(settings, "ADMIN_PASSWORD", "isolated-test-admin-password")
    monkeypatch.setattr(settings, "INITIAL_OPERATOR_USERNAME", "staging_operator")
    monkeypatch.setattr(settings, "INITIAL_AUDITOR_USERNAME", "staging_auditor")
    monkeypatch.setattr(settings, "EDGE_AUTH_TOKEN", "local-test-edge-token-0123456789abcdef")
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert ready.json()["database"] == "connected"
        login = client.post("/auth/token", data={"username": "staging_admin", "password": settings.ADMIN_PASSWORD})
        assert login.status_code == 200
        assert login.json()["role"] == "ADMIN"
        with sessions() as db:
            before = [(u.id, u.username, u.hashed_password) for u in db.query(User).order_by(User.username)]
            assert len(before) == 3
            assert verify_password(settings.ADMIN_PASSWORD, db.query(User).filter_by(username="staging_admin").one().hashed_password)
            bootstrap_users(db)
            assert before == [(u.id, u.username, u.hashed_password) for u in db.query(User).order_by(User.username)]
        monkeypatch.setattr(settings, "BOOTSTRAP_USERS", False)
        assert client.post("/auth/token", data={"username": "staging_admin", "password": settings.ADMIN_PASSWORD}).status_code == 200
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert conn.scalar(sa.text("SELECT count(*) FROM users")) == 3
        for table in ("events", "evidence_packages", "evidence_chain", "analysis_run_summaries", "analysis_telemetry", "sync_queue"):
            assert conn.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 0


def test_populated_production_repairs_preserve_identity_and_audit(migrated_db, monkeypatch):
    engine, config = migrated_db
    if engine.dialect.name != "postgresql":
        pytest.skip("production data repairs intentionally use PostgreSQL locking/ANY")
    command.upgrade(config, "d3f5a7b9c1e2")
    names = ["admin", "admin_eval", "operator", "auditor", "operator_eval", "auditor_eval", "unrelated"]
    with engine.begin() as conn:
        for name in names:
            role = "OPERATOR" if name.startswith("operator") else "AUDITOR" if name.startswith("auditor") else "ADMIN"
            conn.execute(sa.text("INSERT INTO users (id, username, hashed_password, role, command_id, is_active, created_at) VALUES (:id,:name,'fixture-hash',:role,'COMMAND_A',true,'2026-01-01')"), {"id": name + "-id", "name": name, "role": role})
        conn.execute(sa.text("INSERT INTO audit_logs (id,user_id,action,success) VALUES ('audit-fixture','admin_eval-id','FIXTURE',true)"))
    monkeypatch.setenv("ADMIN_PASSWORD", "isolated-historical-repair-password")
    command.upgrade(config, "head")
    from backend.security.auth import verify_password
    with engine.connect() as conn:
        rows = {r["username"]: dict(r) for r in conn.execute(sa.text("SELECT * FROM users")).mappings()}
        assert len(rows) == len(names)
        assert rows["admin"]["id"] == "admin_eval-id"
        assert rows["admin"]["is_active"] is True
        assert rows["admin"]["role"] == "ADMIN"
        assert verify_password("isolated-historical-repair-password", rows["admin"]["hashed_password"])
        assert rows["admin_legacy_disabled"]["id"] == "admin-id"
        assert rows["admin_legacy_disabled"]["is_active"] is False
        assert rows["admin_legacy_disabled"]["hashed_password"] == "fixture-hash"
        assert rows["unrelated"]["is_active"] is True
        assert rows["unrelated"]["hashed_password"] == "fixture-hash"
        for name in ("operator", "auditor", "operator_eval", "auditor_eval"):
            assert rows[name]["is_active"] is False
            assert rows[name]["hashed_password"] == "fixture-hash"
        assert all(r["command_id"] == "COMMAND_A" and r["last_login"] is None for r in rows.values())
        assert all(str(r["created_at"]).startswith("2026-01-01") for r in rows.values())
        assert conn.scalar(sa.text("SELECT user_id FROM audit_logs WHERE id='audit-fixture'")) == "admin_eval-id"
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert rows == {r["username"]: dict(r) for r in conn.execute(sa.text("SELECT * FROM users")).mappings()}


@pytest.mark.parametrize("repair", REPAIRS)
def test_guard_does_not_skip_populated_unrelated_or_partial_accounts(migrated_db, monkeypatch, repair):
    engine, config = migrated_db
    if engine.dialect.name != "postgresql":
        pytest.skip("production account guards use PostgreSQL")
    command.upgrade(config, "d3f5a7b9c1e2")
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO users (id,username,hashed_password,role,command_id,is_active) VALUES ('unrelated-id','unrelated','fixture-hash','AUDITOR','COMMAND_A',true)"))
    spec = importlib.util.spec_from_file_location(repair, ROOT / "alembic" / "versions" / (repair + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("ADMIN_PASSWORD", "isolated-test-password")
    with engine.begin() as conn:
        monkeypatch.setattr(module.op, "get_bind", lambda: conn)
        with pytest.raises(RuntimeError, match="Expected"):
            module.upgrade()
        assert conn.scalar(sa.text("SELECT count(*) FROM users")) == 1
        assert conn.scalar(sa.text("SELECT hashed_password FROM users")) == "fixture-hash"


def test_invalid_historical_accounts_roll_back_entire_repair_chain(migrated_db, monkeypatch):
    engine, config = migrated_db
    if engine.dialect.name != "postgresql":
        pytest.skip("transactional production repair uses PostgreSQL")
    command.upgrade(config, "d3f5a7b9c1e2")
    with engine.begin() as conn:
        for name in ("admin", "admin_eval"):
            conn.execute(sa.text("INSERT INTO users (id,username,hashed_password,role,command_id,is_active) VALUES (:id,:name,'fixture-hash','ADMIN','COMMAND_A',true)"), {"id": name + "-id", "name": name})
        before = [dict(r) for r in conn.execute(sa.text("SELECT * FROM users ORDER BY id")).mappings()]
    monkeypatch.setenv("ADMIN_PASSWORD", "isolated-rollback-test-password")
    # e4/f5 would succeed, but a6 must reject the missing stale-account set.
    with pytest.raises(RuntimeError, match="Expected production user set is incomplete"):
        command.upgrade(config, "head")
    with engine.connect() as conn:
        assert before == [dict(r) for r in conn.execute(sa.text("SELECT * FROM users ORDER BY id")).mappings()]
        assert conn.scalar(sa.text("SELECT version_num FROM alembic_version")) == "d3f5a7b9c1e2"
