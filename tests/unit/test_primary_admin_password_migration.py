import importlib.util
from pathlib import Path

import pytest


_migration_path = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "f5b7c9d1e3a4_sync_primary_admin_password.py"
)
_spec = importlib.util.spec_from_file_location("primary_admin_password_migration", _migration_path)
migration = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(migration)


class _Result:
    def __init__(self, rows=None, rowcount=None):
        self._rows = rows or []
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Connection:
    def __init__(self, primary_rows, guard_rows, update_count=1):
        self._results = iter([
            _Result(primary_rows),
            _Result(guard_rows),
            _Result(rowcount=update_count),
        ])
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((str(statement), parameters))
        return next(self._results)


def _valid_primary():
    return [{"id": "admin-id", "username": "admin", "role": "ADMIN", "is_active": True}]


def _valid_legacy():
    return [{
        "id": "legacy-id",
        "username": "admin_legacy_disabled",
        "role": "ADMIN",
        "is_active": False,
    }]


def test_upgrade_changes_only_the_primary_password_hash(monkeypatch):
    connection = _Connection(_valid_primary(), _valid_legacy())
    monkeypatch.setenv("ADMIN_PASSWORD", "migration-test-password")
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(
        migration,
        "hash_password",
        lambda password: "test-hash" if password == "migration-test-password" else None,
    )

    migration.upgrade()

    update_sql, update_parameters = connection.calls[2]
    set_clause = update_sql.upper().split("SET", 1)[1].split("WHERE", 1)[0]
    assert "HASHED_PASSWORD" in set_clause
    for protected_column in (
        "USERNAME", "ROLE", "COMMAND_ID", "IS_ACTIVE", "CREATED_AT", "LAST_LOGIN",
    ):
        assert protected_column not in set_clause
    assert update_parameters == {
        "hashed_password": "test-hash",
        "primary_id": "admin-id",
        "primary_username": "admin",
    }


@pytest.mark.parametrize("value", [None, ""])
def test_upgrade_fails_before_database_access_when_password_is_missing(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("ADMIN_PASSWORD", value)
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: pytest.fail("database must not be accessed without ADMIN_PASSWORD"),
    )

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD is required"):
        migration.upgrade()


def test_upgrade_rejects_admin_eval(monkeypatch):
    guards = _valid_legacy() + [{
        "id": "removed-id",
        "username": "admin_eval",
        "role": "ADMIN",
        "is_active": True,
    }]
    connection = _Connection(_valid_primary(), guards)
    monkeypatch.setenv("ADMIN_PASSWORD", "migration-test-password")
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    with pytest.raises(RuntimeError, match="admin_eval must not exist"):
        migration.upgrade()

    assert len(connection.calls) == 2


def test_upgrade_requires_inactive_legacy_account(monkeypatch):
    legacy = _valid_legacy()
    legacy[0]["is_active"] = True
    connection = _Connection(_valid_primary(), legacy)
    monkeypatch.setenv("ADMIN_PASSWORD", "migration-test-password")
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    with pytest.raises(RuntimeError, match="must remain inactive"):
        migration.upgrade()

    assert len(connection.calls) == 2


def test_upgrade_requires_exactly_one_updated_row(monkeypatch):
    connection = _Connection(_valid_primary(), _valid_legacy(), update_count=0)
    monkeypatch.setenv("ADMIN_PASSWORD", "migration-test-password")
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration, "hash_password", lambda _password: "test-hash")

    with pytest.raises(RuntimeError, match="exactly one"):
        migration.upgrade()


def test_downgrade_is_intentionally_irreversible():
    with pytest.raises(RuntimeError, match="intentionally irreversible"):
        migration.downgrade()
