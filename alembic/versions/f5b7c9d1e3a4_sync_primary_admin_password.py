"""Synchronize the primary production administrator password hash.

Revision ID: f5b7c9d1e3a4
Revises: e4a6b8c0d2f3
"""

from __future__ import annotations

import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from backend.security.auth import hash_password


revision: str = "f5b7c9d1e3a4"
down_revision: Union[str, Sequence[str], None] = "e4a6b8c0d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PRIMARY_USERNAME = "admin"
REMOVED_USERNAME = "admin_eval"
LEGACY_USERNAME = "admin_legacy_disabled"


def upgrade() -> None:
    connection = op.get_bind()
    # No historical password exists before fresh-install user provisioning.
    # Any populated user table retains the original production guards below.
    if connection.execute(sa.text("SELECT 1 FROM users LIMIT 1")).first() is None:
        return

    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        raise RuntimeError("ADMIN_PASSWORD is required for primary admin password synchronization")

    primary_rows = connection.execute(
        sa.text(
            """
            SELECT id, username, role, is_active
            FROM users
            WHERE username = :primary_username
              AND is_active = true
            FOR UPDATE
            """
        ),
        {"primary_username": PRIMARY_USERNAME},
    ).mappings().all()
    if len(primary_rows) != 1:
        raise RuntimeError("Expected exactly one active primary admin account")

    primary = primary_rows[0]
    if primary["role"] != "ADMIN" or primary["is_active"] is not True:
        raise RuntimeError("Primary admin must be an active ADMIN")

    guard_rows = connection.execute(
        sa.text(
            """
            SELECT id, username, role, is_active
            FROM users
            WHERE username IN (:removed_username, :legacy_username)
            FOR UPDATE
            """
        ),
        {
            "removed_username": REMOVED_USERNAME,
            "legacy_username": LEGACY_USERNAME,
        },
    ).mappings().all()
    guards = {row["username"]: row for row in guard_rows}
    if REMOVED_USERNAME in guards:
        raise RuntimeError("admin_eval must not exist before password synchronization")
    if set(guards) != {LEGACY_USERNAME}:
        raise RuntimeError("Expected exactly one legacy disabled admin account")
    if guards[LEGACY_USERNAME]["is_active"] is not False:
        raise RuntimeError("admin_legacy_disabled must remain inactive")

    update_result = connection.execute(
        sa.text(
            """
            UPDATE users
            SET hashed_password = :hashed_password
            WHERE id = :primary_id
              AND username = :primary_username
              AND role = 'ADMIN'
              AND is_active = true
            """
        ),
        {
            "hashed_password": hash_password(admin_password),
            "primary_id": primary["id"],
            "primary_username": PRIMARY_USERNAME,
        },
    )
    if update_result.rowcount != 1:
        raise RuntimeError("Failed to update exactly one primary admin password hash")


def downgrade() -> None:
    raise RuntimeError("Primary admin password synchronization is intentionally irreversible")
