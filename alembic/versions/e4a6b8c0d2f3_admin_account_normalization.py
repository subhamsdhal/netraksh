"""Normalize the production primary administrator account.

Revision ID: e4a6b8c0d2f3
Revises: d3f5a7b9c1e2
"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from backend.security.auth import hash_password


revision: str = "e4a6b8c0d2f3"
down_revision: Union[str, Sequence[str], None] = "d3f5a7b9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


STALE_USERNAME = "admin"
WORKING_USERNAME = "admin_eval"
LEGACY_USERNAME = "admin_legacy_disabled"


def upgrade() -> None:
    connection = op.get_bind()
    # This production-only data repair has nothing to transform on a fresh
    # installation. User provisioning runs after ALL schema migrations.
    # Check the entire table so partial/unexpected account sets still fail.
    if connection.execute(sa.text("SELECT 1 FROM users LIMIT 1")).first() is None:
        return

    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD is required for admin account normalization")

    rows = connection.execute(
        sa.text(
            """
            SELECT id, username, role, is_active
            FROM users
            WHERE username IN (:stale_username, :working_username, :legacy_username)
            FOR UPDATE
            """
        ),
        {
            "stale_username": STALE_USERNAME,
            "working_username": WORKING_USERNAME,
            "legacy_username": LEGACY_USERNAME,
        },
    ).mappings().all()

    rows_by_username = {row["username"]: row for row in rows}
    if len(rows) != 2:
        raise RuntimeError("Expected exactly the stale and working admin accounts")
    if STALE_USERNAME not in rows_by_username:
        raise RuntimeError("Expected stale admin account is missing")
    if WORKING_USERNAME not in rows_by_username:
        raise RuntimeError("Expected working admin_eval account is missing")
    if LEGACY_USERNAME in rows_by_username:
        raise RuntimeError("admin_legacy_disabled already exists")

    stale_user = rows_by_username[STALE_USERNAME]
    working_user = rows_by_username[WORKING_USERNAME]
    if working_user["role"] != "ADMIN" or working_user["is_active"] is not True:
        raise RuntimeError("admin_eval must be an active ADMIN before normalization")

    stale_result = connection.execute(
        sa.text(
            """
            UPDATE users
            SET username = :legacy_username,
                is_active = false
            WHERE id = :stale_id
              AND username = :stale_username
            """
        ),
        {
            "legacy_username": LEGACY_USERNAME,
            "stale_id": stale_user["id"],
            "stale_username": STALE_USERNAME,
        },
    )
    if stale_result.rowcount != 1:
        raise RuntimeError("Failed to retire exactly one stale admin account")

    working_result = connection.execute(
        sa.text(
            """
            UPDATE users
            SET username = :stale_username,
                hashed_password = :hashed_password,
                role = 'ADMIN',
                is_active = true
            WHERE id = :working_id
              AND username = :working_username
            """
        ),
        {
            "stale_username": STALE_USERNAME,
            "hashed_password": hash_password(admin_password),
            "working_id": working_user["id"],
            "working_username": WORKING_USERNAME,
        },
    )
    if working_result.rowcount != 1:
        raise RuntimeError("Failed to normalize exactly one working admin account")


def downgrade() -> None:
    raise RuntimeError("Admin account normalization is intentionally irreversible")
