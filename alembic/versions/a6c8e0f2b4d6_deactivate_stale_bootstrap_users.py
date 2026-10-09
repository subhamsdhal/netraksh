"""Deactivate unused production bootstrap accounts.

Revision ID: a6c8e0f2b4d6
Revises: f5b7c9d1e3a4

The primary administrator and the retained legacy administrator are guarded
but never modified.  Only the four discovered never-used non-admin bootstrap
accounts are deactivated, preserving their rows and associated audit history.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a6c8e0f2b4d6"
down_revision: Union[str, Sequence[str], None] = "f5b7c9d1e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRIMARY_ADMIN = "admin"
LEGACY_ADMIN = "admin_legacy_disabled"
STALE_ACCOUNTS = {
    "operator": "OPERATOR",
    "auditor": "AUDITOR",
    "operator_eval": "OPERATOR",
    "auditor_eval": "AUDITOR",
}


def upgrade() -> None:
    connection = op.get_bind()
    # Fresh installations have no historical bootstrap accounts to retire.
    # Never skip validation merely because the named accounts are missing.
    if connection.execute(sa.text("SELECT 1 FROM users LIMIT 1")).first() is None:
        return

    guarded_names = [PRIMARY_ADMIN, LEGACY_ADMIN, *STALE_ACCOUNTS]
    rows = connection.execute(
        sa.text(
            """
            SELECT username, role, is_active, last_login
            FROM users
            WHERE username = ANY(:usernames)
            FOR UPDATE
            """
        ),
        {"usernames": guarded_names},
    ).mappings().all()
    users = {row["username"]: row for row in rows}

    if set(users) != set(guarded_names):
        raise RuntimeError("Expected production user set is incomplete; refusing stale-account change")
    if users[PRIMARY_ADMIN]["role"] != "ADMIN" or users[PRIMARY_ADMIN]["is_active"] is not True:
        raise RuntimeError("Primary admin must remain an active ADMIN")
    if users[LEGACY_ADMIN]["role"] != "ADMIN" or users[LEGACY_ADMIN]["is_active"] is not False:
        raise RuntimeError("Legacy admin must remain an inactive ADMIN")

    for username, expected_role in STALE_ACCOUNTS.items():
        row = users[username]
        if row["role"] != expected_role:
            raise RuntimeError(f"Unexpected role for stale account {username}")
        if row["is_active"] is not True:
            raise RuntimeError(f"Stale account {username} is not active as expected")
        if row["last_login"] is not None:
            raise RuntimeError(f"Stale account {username} has login history; refusing deactivation")

    result = connection.execute(
        sa.text(
            """
            UPDATE users
            SET is_active = false
            WHERE username = ANY(:usernames)
              AND is_active = true
              AND last_login IS NULL
            """
        ),
        {"usernames": list(STALE_ACCOUNTS)},
    )
    if result.rowcount != len(STALE_ACCOUNTS):
        raise RuntimeError("Failed to deactivate exactly four stale bootstrap accounts")


def downgrade() -> None:
    raise RuntimeError("Stale-account deactivation is intentionally irreversible")
