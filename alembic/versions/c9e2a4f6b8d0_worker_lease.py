"""Persist exact edge worker ownership and interrupted run metadata.

Revision ID: c9e2a4f6b8d0
Revises: f8c1d4e7a2b5
"""
from alembic import op
import sqlalchemy as sa


revision = "c9e2a4f6b8d0"
down_revision = "f8c1d4e7a2b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, column_type in (
        ("interrupted_at", sa.Float()),
        ("interruption_reason", sa.String(64)),
        ("worker_boot_id", sa.String(36)),
        ("worker_instance_id", sa.String(128)),
        ("worker_started_at", sa.Float()),
        ("last_worker_heartbeat", sa.Float()),
    ):
        op.add_column("analysis_run_summaries", sa.Column(name, column_type, nullable=True))
    op.create_table(
        "analysis_worker_leases",
        sa.Column("camera_id", sa.String(36), primary_key=True),
        sa.Column("boot_id", sa.String(36), nullable=False),
        sa.Column("instance_id", sa.String(128)),
        sa.Column("registered_at", sa.Float(), nullable=False),
        sa.Column("worker_started_at", sa.Float(), nullable=False),
        sa.Column("last_heartbeat_at", sa.Float(), nullable=False),
        sa.Column("phase", sa.String(24), nullable=False),
        sa.Column("analysis_session_id", sa.String(36)),
        sa.Column("stream_id", sa.String(36)),
        sa.Column("analysis_generation", sa.Integer()),
        sa.Column("last_frame_index", sa.Integer()),
        sa.Column("last_video_time", sa.Float()),
    )


def downgrade() -> None:
    op.drop_table("analysis_worker_leases")
    for name in (
        "last_worker_heartbeat", "worker_started_at", "worker_instance_id",
        "worker_boot_id", "interruption_reason", "interrupted_at",
    ):
        op.drop_column("analysis_run_summaries", name)
